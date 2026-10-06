"""Search Idealista for apartments and return a ranked shortlist.

URL for price + location (deterministic), browser-harness to extract every listing,
optional Jev classify for judgment filters (real terrace? genuine listing?), then rank
by price in code. Connects to whatever Chrome/Chromium browser-harness is pointed at
(BU_CDP_URL on the VPS; local Chrome on a laptop). Page traffic uses that browser's
network path, so a residential proxy belongs on the browser, not here.

  uv run --project <repo> --env-file .env python apartment_search.py \
    --operation sale --location barcelona/sants-montjuic/hostafrancs --max-price 500000 \
    --classify-question 'Is this a genuine loft or duplex, judging the actual space not marketing words?' \
    --choice loft='Open-plan loft / converted space / double height' \
    --choice duplex='Two levels: duplex, internal stairs, usable mezzanine' \
    --choice standard='One level, incl. studios only marketed as loft' \
    --keep loft,duplex --limit 10

Default output is a Markdown shortlist (for Hermes to relay); --json emits the raw list.
"""

import argparse
import json
import re
import sys
import time

from browser_harness import helpers
from browser_harness.admin import ensure_daemon

OPERATIONS = {"sale": "venta-viviendas", "rent": "alquiler-viviendas"}

# Navigation is locked to Idealista: the initial URL and every pagination link read
# from the (untrusted) page DOM must stay on these hosts, so a spoofed/compromised page
# cannot redirect the headless browser at internal or arbitrary targets.
ALLOWED_HOST_SUFFIXES = ("idealista.com", "idealista.it", "idealista.pt")
DESC_CAP = 800  # cap untrusted listing text sent to the classifier (injection/cost bound)


def host_ok(url):
    """Cheap pre-navigation gate. scrape() additionally checks the browser's own
    resolved URL, which is authoritative against parser differentials and redirects."""
    from urllib.parse import urlparse

    if not isinstance(url, str) or any(c in url for c in "\\ \t\n\r"):
        return False  # browsers normalize backslashes/whitespace; urlparse does not -> reject
    pr = urlparse(url)
    if pr.scheme not in ("http", "https"):  # no file:/data:/javascript:/ftp:
        return False
    host = (pr.hostname or "").lower().rstrip(".")  # trailing-dot normalized like a browser
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)

# One atomic read of the visible result cards.
EXTRACT_JS = r"""JSON.stringify({
  total: (document.querySelector('h1')||{}).innerText || document.title,
  blocked: !!document.querySelector('iframe[src*="captcha-delivery"],iframe[src*="recaptcha"]')
           || (!document.querySelector('article.item') && /captcha|robot|unusual traffic/i.test(document.body.innerText)),
  next: (document.querySelector('.pagination .next a')||{}).href || null,
  items: [...document.querySelectorAll('article.item')].map(a => ({
    title:   (a.querySelector('.item-link')||{}).innerText || '',
    href:    (a.querySelector('.item-link')||{}).href || '',
    price:   ((a.querySelector('.item-price')||{}).innerText || '').split('\n')[0].trim(),
    details: [...a.querySelectorAll('.item-detail')].map(d => d.innerText).join(' · '),
    desc:    (a.querySelector('.item-description')||{}).innerText || ''
  })).filter(i => i.href)
})"""


def build_url(args):
    if args.start_url:
        return args.start_url
    op = OPERATIONS[args.operation]
    filters = []
    if args.max_price:
        filters.append(f"precio-hasta_{args.max_price}")
    if args.min_price:
        filters.append(f"precio-desde_{args.min_price}")
    seg = f"/con-{','.join(filters)}" if filters else ""
    return f"https://www.idealista.com/{op}/{args.location.strip('/')}/{seg}/".replace("//", "/").replace("https:/", "https://")


def price_num(s):
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


def beds_num(details):
    m = re.search(r"(\d+)\s*hab", details or "")
    return int(m.group(1)) if m else None


def size_num(details):
    m = re.search(r"(\d+)\s*m", details or "")
    return int(m.group(1)) if m else None


def scrape(url, max_pages):
    ensure_daemon()
    helpers.new_tab(url)
    try:
        helpers.activate_tab(helpers.current_tab())
    except Exception:
        pass
    helpers.wait_for_load()
    items, seen, header = [], set(), ""
    for page in range(max_pages):
        # Authoritative guard: trust the browser's resolved URL (post-parse, post-redirect),
        # not the pre-navigation string, so a parser differential or redirect cannot smuggle
        # us off Idealista before we read or trust the page.
        landed = (helpers.page_info() or {}).get("url", "")
        if not host_ok(landed):
            raise RuntimeError(f"Navigated off Idealista to {landed!r}; aborting.")
        time.sleep(3)  # politeness; heavy crawling re-triggers bot protection
        data = json.loads(helpers.js(EXTRACT_JS))
        if page == 0:
            header = data["total"]
        if data["blocked"]:
            raise RuntimeError(f"Bot challenge on page {page + 1} ({header!r}). Needs a residential proxy / solved check.")
        for it in data["items"]:
            if it["href"] not in seen:
                seen.add(it["href"])
                items.append(it)
        nxt = data["next"]
        if not nxt or not host_ok(nxt):  # cheap pre-filter; the landed-URL check above is authoritative
            break
        helpers.goto_url(nxt)
        helpers.wait_for_load()
    return header, items


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start-url", help="Full Idealista search URL (overrides the builder).")
    p.add_argument("--operation", choices=OPERATIONS, default="sale")
    p.add_argument("--location", help="Idealista location slug, e.g. barcelona/sants-montjuic/hostafrancs")
    p.add_argument("--max-price", type=int)
    p.add_argument("--min-price", type=int)
    p.add_argument("--pages", type=int, default=5, help="Max listing pages to read.")
    p.add_argument("--min-size", type=int)
    p.add_argument("--max-size", type=int)
    p.add_argument("--min-beds", type=int)
    p.add_argument("--classify-question")
    p.add_argument("--choice", action="append", default=[], help="key='description' (repeat).")
    p.add_argument("--keep", help="Comma-separated choice keys to keep (default: all).")
    p.add_argument("--min-confidence", type=float, default=0.7)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if not args.start_url and not args.location:
        p.error("need --location or --start-url")

    url = build_url(args)
    if not host_ok(url):
        p.error(f"refusing non-Idealista URL: {url}")
    try:
        header, items = scrape(url, args.pages)
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e), "url": url}) if args.json
              else f"**Search failed.** {e}\nURL: {url}")
        sys.exit(1)

    # structured fields + numeric post-filters
    for it in items:
        it["price_eur"], it["beds"], it["size_m2"] = price_num(it["price"]), beds_num(it["details"]), size_num(it["details"])
    kept = [it for it in items if
            (args.min_size is None or (it["size_m2"] or 0) >= args.min_size)
            and (args.max_size is None or (it["size_m2"] or 1e9) <= args.max_size)
            and (args.min_beds is None or (it["beds"] or 0) >= args.min_beds)]

    note = ""
    cost = 0.0
    if args.classify_question and args.choice:
        from classify import classify_items
        criteria = dict(c.split("=", 1) for c in args.choice)
        for it in kept:  # bound untrusted listing text fed to the classifier
            it["desc"] = (it["desc"] or "")[:DESC_CAP]
        kept, cost = classify_items(kept, ["title", "desc", "details"], args.classify_question, criteria)
        keep_keys = set((args.keep or ",".join(criteria)).split(","))
        uncertain = [it for it in kept if it["jev"].get("choice") in keep_keys and (it["jev"].get("confidence") or 0) < args.min_confidence]
        kept = [it for it in kept if it["jev"].get("choice") in keep_keys and (it["jev"].get("confidence") or 0) >= args.min_confidence]
        if uncertain:
            note = f"\n\n_{len(uncertain)} more matched below {args.min_confidence:.0%} confidence (not shown)._"

    kept.sort(key=lambda it: it["price_eur"] or 1e12)
    top = kept[: args.limit]

    if args.json:
        print(json.dumps({"status": "ok", "url": url, "header": header, "found": len(items),
                          "matched": len(kept), "classify_cost_usd": cost, "results": top}, ensure_ascii=False, indent=1))
        return

    if not top:
        print(f"No matches. Read {len(items)} listings from {header!r}.\nURL: {url}{note}")
        return
    lines = [f"**{len(kept)} matches** (showing {len(top)}), from {header!r}:", "", "| Price | Listing | Details | Link |", "|---|---|---|---|"]
    for it in top:
        verdict = f" ({it['jev']['choice']} {it['jev']['confidence']:.0%})" if "jev" in it else ""
        title = it["title"].replace("|", "/")[:60]
        lines.append(f"| {it['price']} | {title}{verdict} | {it['details'][:45]} | {it['href']} |")
    cost_line = f"\n\nRead {len(items)} listings; Jev classify ${cost}." if cost else f"\n\nRead {len(items)} listings."
    print("\n".join(lines) + cost_line + note)


if __name__ == "__main__":
    main()
