---
name: browser
description: Use for ANY task in the user's web browser: doing things on sites ("find me a flat on idealista", "check my account", "fill this form"), searching/comparing listings or flights, extracting data from pages, screenshots, logged-in or bot-protected sites. Always runs in the user's own visible Chrome (their cookies, their logins). Routes: URL/HTTP first, jev-ultrafast to decide clicks, browser-harness (bh) to extract, Jev classify.py for judgments over extracted items, Python for exact math. Use agent-browser only for testing public pages in a clean, cookie-less browser.
---

# browser: everything in the user's real Chrome

The user wants to **watch it happen in their own Chrome**: it has their cookies and remote debugging is already set up. Never use a headless or separate browser for their tasks. Every tab you open must be in front (`activate_tab`), and leave result tabs open.

Two tools, both on the same Chrome:
- `~/.claude/skills/browser/bh`: browser-harness (Python helpers over CDP, run via heredoc). You drive.
- `~/.claude/skills/browser/jev.py`: jev-ultrafast, an autonomous goal-to-done agent (TypeSafe Jev via OpenRouter). It drives.

## Pick the route (cheapest that works)

1. **URL / HTTP first.** No browser if a plain fetch answers it (`curl`, WebFetch). For search sites, encode filters in the URL and open that: idealista `.../venta-viviendas/barcelona/sants-montjuic/hostafrancs/con-precio-hasta_500000/`, Google Flights `?q=...`, Amazon `s?k=...&rh=...`. Look at what URL the site produces after filtering once; it is usually stable.
2. **jev** for short, interactive goals on normal pages: open an article, log a simple form, click through a wizard. Fast (~300 ms/decision) and cheap (~$0.0003/decision).
3. **Step mode (bh)** when jev blocks, the site has custom dropdowns/date pickers/infinite lists, or you need data back. You observe, act, and extract yourself.

Mix them: URL to land on the right page, jev or bh to interact, bh to extract.

## Step mode (bh)

```bash
~/.claude/skills/browser/bh <<'PY'
new_tab("https://example.com")       # once per task; later calls reuse the attached tab
activate_tab(current_tab())           # user watches
wait_for_load()
print(page_info())
print(js("document.body.innerText.slice(0, 3000)"))
PY
```

Helpers are pre-imported: `new_tab, activate_tab, current_tab, list_tabs, switch_tab, goto_url, wait_for_load, wait_for_element, wait_for_network_idle, page_info, js, click_at_xy, type_text, fill_input, press_key, scroll, capture_screenshot(path), upload_file, http_get, cdp`.

- **Find things**: `js(...)` with querySelectorAll returning JSON, or `cdp("Accessibility.getFullAXTree")` filtered in Python (it is huge; never print it raw).
- **Click**: get the element's box center via `js` (`getBoundingClientRect`), then `click_at_xy(x, y)`, then verify with `js`/`page_info()`. Match the target by its exact label/text; never fall back to "some button near there" (that nearly clicked Google Flights' "Clear Stops" once). If no label matches, screenshot and look.
- **Grids and charts** (date grids, calendars, price graphs): a screenshot is often the fastest way to read them. Pages jev opened render at 1120 px wide, so screenshot pixels scale to page coordinates by `1120 / image width of the page area`.
- **Extract**: one `js` call that maps the result cards to `{title, price, href, ...}` and returns `JSON.stringify(...)`. Paginate by following the "next" link's `href` with `goto_url`. Save to the scratchpad, then filter in Python.
- **Screenshot** (to check visual state yourself): `capture_screenshot("/path/in/scratchpad.png")`, then Read the file.
- **Language**: the site's language matters for URL filters and site search terms (Spain: Spanish and Catalan). For deciding what an item *is*, use `classify.py`, not keyword lists.

## Who does what

Jev is a **decision model**, not a reader: it picks one option from options you give it, with calibrated probabilities. Split every task three ways:

| Work | Who |
|---|---|
| Turn pages into data (extract cards, read grids, paginate) | bh (code), screenshots when the DOM is opaque |
| Exact computation (cheapest, totals, sort, filter by number) | Python. Never ask a model for `min()` |
| Judgment over items (is this a real loft? which flight fits "no red-eye"? is this listing a duplicate/scam?) | **Jev via `classify.py`** |
| Choosing what to click next on a page | **jev** (`jev.py`), not hand-picked coordinates |
| Ambiguous user intent ("second week", which trade-off matters) | Claude, or ask the user |

Don't substitute regex/keyword matching for a judgment call: marketing words ("estilo loft") fool it, and paraphrases slip past it. Jev reads Spanish/Catalan fine.

## classify.py (Jev judgments over extracted items)

```bash
uv run --project ~/Developer/jev-browser --env-file ~/Developer/jev-browser/.env \
  python ~/.claude/skills/browser/classify.py --items items.json --fields title,desc,details \
  --question 'Is this home a real loft or duplex? Judge the actual space, not marketing words.' \
  --choice loft='Genuine loft: open-plan, converted space, double height' \
  --choice duplex='Two levels: dúplex, internal stairs, usable mezzanine' \
  --choice standard='One level, including small units only marketed as loft' \
  --out classified.json
```

One Jev request per item, 8 in parallel. Measured: 1,113 Idealista listings in 36 s for $0.027. Each item gets `jev: {choice, confidence, probabilities}`. Write criteria as concrete descriptions, include an explicit "none of these" choice, and treat probabilities under ~0.7 as "check manually" (report them as uncertain, don't silently include).

## jev

```bash
uv run --project ~/Developer/jev-browser --env-file ~/Developer/jev-browser/.env \
  python ~/.claude/skills/browser/jev.py --url 'https://start.page' --goal 'One narrow goal. Say when to stop.'
```

JSON report: `status` (`done`/`blocked`/`error`), `actions`, final `url`, `title`, visible `text` (`--text-chars N`, default 4000). Exit 0 only on `done`. The tab opens in front and stays open.

- Start URL as close to the goal as possible (route 1). Concrete values, explicit stop condition ("Stop when results are visible. Do not contact anyone.").
- It stops itself when it repeats a 1-2 action cycle for 6 steps (e.g. reopening a dropdown). On `blocked`, switch to step mode on the same page; don't rerun the same goal.
- It cannot handle iframes, shadow DOM, canvas, uploads, pop-up tabs, nested scroll containers. Go straight to step mode for those.
- `done` is its opinion. Verify from the returned text, or with bh.

## Return the answer, not "done"

Finish every task by extracting the actual result (listings with price/size/link, the confirmation number, the value asked for) and give it to the user as a short table or list. Open the best few results as tabs (`open -a "Google Chrome" URL` or `new_tab`) so they can look. State coverage honestly: how many items were read, what was filtered on, and what wasn't checked.

## Safety

- It is the user's real profile. Before anything that buys, sends, posts, books, deletes, submits a form to a third party, or changes settings: confirm first. Exploratory goals say "do not submit/contact/purchase".
- Passwords, MFA, payment details: never type them. Ask the user to do it in the visible tab.
- Don't auto-retry anything that may have mutated state.
- Heavy crawling (dozens of page loads) can re-trigger bot protection: keep ~3 s between pages and stop if a challenge appears.

## Bot checks and logins

A page with an empty title/text and a `captcha-delivery.com` (DataDome), Cloudflare, or reCAPTCHA iframe is a challenge. Bring that tab to the front, ask the user to solve it (or log in), wait for their "done", then continue in the same tab. Their cookie then covers jev and bh too.

## Connection

- `~/.claude/skills/browser/bh --doctor`: needs `daemon alive` and `active browser connections` ok (cloud auth FAIL is irrelevant).
- `DevToolsActivePort not found`: run `open -a "Google Chrome" "chrome://inspect/#remote-debugging"` and ask the user to switch the toggle on.
- "Allow remote debugging?" popup: while the command waits, run `~/.claude/skills/browser/bh mac-approve` in a separate call; don't rerun. `accessibility-required` means ask the user once to grant the terminal Accessibility access.
- Log: `~/.config/browser-harness/tmp/bu-default.log`.

## Known intermittent failures (Chrome 154, 2026-10-06)

- `Input.dispatchMouseEvent timed out after 5s waiting for the daemon` (jev, ~1 in 3 runs, cause unknown). The click may or may not have landed. Read-only goal: retry once; otherwise continue in step mode after checking the page.
- `Text helper returned no valid field value; nothing typed.` Rare. Safe to retry. The report's `text_reply` shows the raw model output; note it.

## When agent-browser instead

Only for testing public pages in a clean, logged-out browser (QA of a deployed site, checking what a new visitor sees). It has none of the user's cookies and isn't visible to them.
