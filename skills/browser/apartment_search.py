"""Search Idealista for apartments and return a ranked shortlist.

Fetch path (--via):
  context  (default): context.dev /web/extract returns structured listings and transparently
           handles DataDome, which hard-blocks the VPS browser. Runs under Agent Vault, which
           injects the context.dev key (header placeholder __context_dev_api_key__).
  browser          : the jev-browser Chrome over CDP (works on sites without DataDome-grade
           protection; blocked on Idealista from the VPS).

Either way: price + location are deterministic in the URL, Jev classify judges the listings,
ranking is exact code.

  uv run --project <repo> --env-file .env python apartment_search.py \
    --operation sale --location barcelona/sants-montjuic/hostafrancs --max-price 500000 \
    --classify-question '...' --choice loft='...' --choice duplex='...' --choice standard='...' \
    --keep loft,duplex --limit 10

Default output is a Markdown shortlist (for Hermes to relay); --json emits the raw list.
"""

import argparse
import json
import os
import re
import sys
import time

OPERATIONS = {"sale": "venta-viviendas", "rent": "alquiler-viviendas"}
ALLOWED_HOST_SUFFIXES = ("idealista.com", "idealista.it", "idealista.pt")
DESC_CAP = 800  # cap untrusted listing text sent to the classifier

LISTING_SCHEMA = {
    "type": "object",
    "properties": {
        "listings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Listing title"},
                    "price_eur": {"type": "number", "description": "Asking price in euros"},
                    "size_m2": {"type": "number", "description": "Size in square metres"},
                    "rooms": {"type": "number", "description": "Bedrooms (habitaciones)"},
                    "url": {"type": "string", "description": "Full idealista.com/inmueble/<id>/ URL"},
                    "description": {"type": "string", "description": "Listing descriptive text"},
                },
                "required": ["title", "url"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["listings"],
    "additionalProperties": False,
}

# Browser fallback: one atomic read of the visible result cards.
EXTRACT_JS = r"""JSON.stringify({
  total: (document.querySelector('h1')||{}).innerText || document.title,
  blocked: !!document.querySelector('iframe[src*="captcha-delivery"],iframe[src*="recaptcha"]')
           || (!document.querySelector('article.item') && /captcha|robot|unusual traffic|uso indebido/i.test(document.body.innerText)),
  next: (document.querySelector('.pagination .next a')||{}).href || null,
  items: [...document.querySelectorAll('article.item')].map(a => ({
    title:   (a.querySelector('.item-link')||{}).innerText || '',
    href:    (a.querySelector('.item-link')||{}).href || '',
    price:   ((a.querySelector('.item-price')||{}).innerText || '').split('\n')[0].trim(),
    details: [...a.querySelectorAll('.item-detail')].map(d => d.innerText).join(' · '),
    desc:    (a.querySelector('.item-description')||{}).innerText || ''
  })).filter(i => i.href)
})"""


def host_ok(url):
    from urllib.parse import urlparse

    if not isinstance(url, str) or any(c in url for c in "\\ \t\n\r"):
        return False
    pr = urlparse(url)
    if pr.scheme not in ("http", "https"):
        return False
    host = (pr.hostname or "").lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def build_url(args):
    if args.start_url:
        return args.start_url
    op = OPERATIONS[args.operation]
    filters = []
    if args.max_price:
        filters.append(f"precio-hasta_{args.max_price}")
    if args.min_price:
        filters.append(f"precio-desde_{args.min_price}")
    seg = f"con-{','.join(filters)}/" if filters else ""
    return f"https://www.idealista.com/{op}/{args.location.strip('/')}/{seg}"


def page_url(base, n):
    return base if n == 1 else base.rstrip("/") + f"/pagina-{n}.html"


def price_num(s):
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


def beds_num(details):
    m = re.search(r"(\d+)\s*hab", details or "")
    return int(m.group(1)) if m else None


def size_num(details):
    m = re.search(r"(\d+)\s*m", details or "")
    return int(m.group(1)) if m else None


def norm(listing):
    """context.dev listing -> the common item shape (price_eur/beds/size already structured)."""
    price = listing.get("price_eur")
    rooms, size = listing.get("rooms"), listing.get("size_m2")
    details = " · ".join(x for x in (f"{int(rooms)} hab." if rooms else "", f"{int(size)} m²" if size else "") if x)
    return {
        "title": listing.get("title") or "", "href": listing.get("url") or "",
        "price": f"{int(price):,}€".replace(",", ".") if price else "",
        "details": details, "desc": listing.get("description") or "",
        "price_eur": int(price) if price else None,
        "beds": int(rooms) if rooms else None, "size_m2": int(size) if size else None,
    }


def scrape_context(base, max_pages):
    import httpx

    key = os.environ.get("CONTEXT_DEV_API_KEY", "__context_dev_api_key__")  # broker injects the real one
    url_base = os.environ.get("CONTEXT_DEV_BASE_URL", "https://api.context.dev/v1").rstrip("/")
    verify = os.environ.get("SSL_CERT_FILE") or True  # Agent Vault MITM CA when wrapped
    # One crawl call: context.dev keeps the anti-bot session across result pages, which
    # independent per-page fetches do not (page 2 alone gets DataDome-404'd). maxDepth=1 lets
    # it follow pagination; it also tends to follow sort-order variants, so coverage is good
    # but not guaranteed exhaustive. --pages caps the crawl breadth.
    payload = {
        "url": base,
        "maxPages": max(max_pages, 1),
        "maxDepth": 1 if max_pages > 1 else 0,
        "instructions": ("Collect every property listing card from this search and its paginated "
                         "result pages (pagina-2.html, pagina-3.html, 'siguiente'). Do NOT follow "
                         "individual listing pages or help pages."),
        "schema": LISTING_SCHEMA,
    }
    with httpx.Client(timeout=200, verify=verify) as client:
        r = client.post(f"{url_base}/web/extract", json=payload, headers={"Authorization": f"Bearer {key}"})
    if r.is_error:
        raise RuntimeError(f"context.dev HTTP {r.status_code}: {r.text[:140]}")
    body = r.json()
    km = body.get("key_metadata") or {}
    if km.get("credits_remaining") is not None:
        try:
            from jev_ultrafast.spend_log import log_spend
            log_spend("context", credits_remaining=km.get("credits_remaining"), credits_consumed=km.get("credits_consumed"))
        except Exception:
            pass
    listings = ((body.get("data") or {}).get("listings")) or []
    items, seen = [], set()
    for L in listings:
        it = norm(L)
        # host_ok: the url is untrusted (whatever context.dev extracted) -> keep only Idealista
        # listing links, so a stray/injected URL cannot reach the relayed output.
        if it["href"] and host_ok(it["href"]) and "/inmueble/" in it["href"] and it["href"] not in seen:
            seen.add(it["href"])
            items.append(it)
    return f"{len(items)} listings via context.dev", items


def scrape_browser(url, max_pages):
    from browser_harness import helpers
    from browser_harness.admin import ensure_daemon

    ensure_daemon()
    helpers.new_tab(url)
    try:
        helpers.activate_tab(helpers.current_tab())
    except Exception:
        pass
    helpers.wait_for_load()
    items, seen, header = [], set(), ""
    for page in range(max_pages):
        landed = (helpers.page_info() or {}).get("url", "")
        if not host_ok(landed):
            raise RuntimeError(f"Navigated off Idealista to {landed!r}; aborting.")
        time.sleep(3)
        data = json.loads(helpers.js(EXTRACT_JS))
        if page == 0:
            header = data["total"]
        if data["blocked"]:
            raise RuntimeError(f"Bot challenge on page {page + 1} ({header!r}). Use --via context (DataDome).")
        for it in data["items"]:
            if it["href"] not in seen:
                seen.add(it["href"])
                it["price_eur"], it["beds"], it["size_m2"] = price_num(it["price"]), beds_num(it["details"]), size_num(it["details"])
                items.append(it)
        nxt = data["next"]
        if not nxt or not host_ok(nxt):
            break
        helpers.goto_url(nxt)
        helpers.wait_for_load()
    return header, items


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--via", choices=("context", "browser"), default="context",
                   help="context = context.dev (bypasses DataDome, default); browser = jev Chrome over CDP.")
    p.add_argument("--start-url")
    p.add_argument("--operation", choices=OPERATIONS, default="sale")
    p.add_argument("--location", help="Idealista slug, e.g. barcelona/sants-montjuic/hostafrancs")
    p.add_argument("--max-price", type=int)
    p.add_argument("--min-price", type=int)
    p.add_argument("--pages", type=int, default=5)
    p.add_argument("--min-size", type=int)
    p.add_argument("--max-size", type=int)
    p.add_argument("--min-beds", type=int)
    p.add_argument("--classify-question")
    p.add_argument("--choice", action="append", default=[])
    p.add_argument("--keep")
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
        header, items = (scrape_context if args.via == "context" else scrape_browser)(url, args.pages)
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e), "url": url}) if args.json
              else f"**Search failed** (via {args.via}). {e}\nURL: {url}")
        sys.exit(1)

    kept = [it for it in items if
            (args.min_size is None or (it["size_m2"] or 0) >= args.min_size)
            and (args.max_size is None or (it["size_m2"] or 1e9) <= args.max_size)
            and (args.min_beds is None or (it["beds"] or 0) >= args.min_beds)]

    note, cost = "", 0.0
    if args.classify_question and args.choice:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from classify import classify_items
        criteria = dict(c.split("=", 1) for c in args.choice)
        for it in kept:
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
        print(json.dumps({"status": "ok", "via": args.via, "url": url, "header": header, "found": len(items),
                          "matched": len(kept), "classify_cost_usd": cost, "results": top}, ensure_ascii=False, indent=1))
        return
    if not top:
        print(f"No matches. Read {len(items)} listings ({header}).\nURL: {url}{note}")
        return
    lines = [f"**{len(kept)} matches** (showing {len(top)}), {header}:", "", "| Price | Listing | Details | Link |", "|---|---|---|---|"]
    for it in top:
        verdict = f" ({it['jev']['choice']} {it['jev']['confidence']:.0%})" if "jev" in it else ""
        lines.append(f"| {it['price']} | {it['title'].replace('|', '/')[:60]}{verdict} | {it['details'][:45]} | {it['href']} |")
    tail = f"\n\nRead {len(items)} listings via {args.via}" + (f"; Jev classify ${cost}." if cost else ".")
    print("\n".join(lines) + tail + note)


if __name__ == "__main__":
    main()
