---
name: apartment-search
description: Search Idealista for apartments/flats to buy or rent and return a ranked shortlist with judgment filters (real loft/duplex, terrace, etc). Runs the jev-browser stack in headless Chromium on this VPS.
version: 0.1.0
platforms: [linux]
related_skills: [flight-shopping, product-price-monitor, portal-watch]
metadata:
  hermes:
    tags: [browser, property, idealista, search, jev]
---

# apartment-search

Find apartments on Idealista and hand back a ranked shortlist. Price and location go in the URL (deterministic); everything judgmental (is it a genuine loft, a real terrace, a sensible listing) is decided by Jev over the extracted text; ranking is exact code. Runs in the VPS headless Chromium (`jev-chrome.service`, CDP on 127.0.0.1:9333) and reaches OpenRouter through Agent Vault.

## When to use

- Braeden asks to find/compare flats or houses on Idealista (buy or rent), or to watch an area for new matches.
- Not for a single known listing URL (just open it) or for non-Idealista portals (not yet supported).

## Run it

```sh
cd ~/jev-browser && BU_CDP_URL=http://127.0.0.1:9333 vps/run-wrapped.sh \
  ~/.local/bin/uv run --project ~/jev-browser --env-file ~/jev-browser/.env \
  python skills/browser/apartment_search.py \
    --operation sale --location barcelona/sants-montjuic/hostafrancs --max-price 500000 \
    --min-beds 2 --min-size 60 \
    --classify-question 'Is this a genuine loft or duplex? Judge the actual space from the listing (Spanish/Catalan), not marketing words; a tiny studio called estilo loft is not a loft.' \
    --choice loft='Genuine loft: open-plan, converted/industrial space, high ceilings or double height' \
    --choice duplex='Two levels: duplex, internal stairs, or a usable mezzanine (altillo)' \
    --choice standard='Regular flat/atico/studio on one level, incl. units only marketed as loft' \
    --keep loft,duplex --limit 10
```

Prints a Markdown shortlist (price, listing, details, link) to relay to Braeden; add `--json` for structured output. `vps/run-wrapped.sh` supplies the brokered OpenRouter key; inside a Hermes job the vault session is already present.

### Arguments

- `--operation sale|rent`, `--location <slug>`, `--max-price` / `--min-price` build the URL. Or pass a full `--start-url`.
- Numeric post-filters: `--min-beds`, `--min-size`, `--max-size` (parsed from each card).
- Judgment filter (optional): `--classify-question` + two or more `--choice key='description'`, then `--keep key1,key2`. Below `--min-confidence` (default 0.70) a match is counted but not shown.
- `--pages` (default 5) caps listing pages read; `--limit` caps results shown.

### Location slug

Idealista encodes the area in the path, e.g. `barcelona/sants-montjuic/hostafrancs` or `.../el-poble-sec-parc-de-montjuic`. If unsure, open the area once on idealista.com with the browser skill and copy the path between the operation segment and the filters.

### Writing good criteria

Describe each `--choice` concretely and include a catch-all "standard/other" option. Terse criteria score real matches low (a duplex scored 55% on "two levels" but 95%+ on the fuller wording above), so err toward detail. Treat the sub-threshold count in the note as "worth a manual look".

## Delivery / scheduling

Relay the Markdown table to Braeden (Telegram). To watch an area, wrap this in a cron like `portal-watch`: keep a seen-set of listing hrefs between runs and only message new matches.

## Dependencies and failure modes

- **Residential proxy required for the VPS.** Idealista runs DataDome; from the VPS datacenter IP it serves a bot challenge and the script exits with `Bot challenge ... Needs a residential proxy`. The proxy lives on the browser: set `JEV_PROXY=host:port` in `~/jev-browser/vps/chrome.env` (whitelist this VPS's public IP with the provider so no inline credentials are needed) and `systemctl --user restart jev-chrome`. Verify with the browser skill that an IP-check page shows a Spain residential IP before relying on results.
- **Chromium down:** `systemctl --user status jev-chrome`; it auto-restarts.
- **Headless fingerprint:** a residential IP is necessary but may not be sufficient; if challenges persist after the proxy, the next lever is browser fingerprint hardening.
- `done`/results are not proof a listing is current; Idealista listings can be stale or duplicated across agencies.
