# Learnings (jev-browser fork, 2026-10-06)

Field notes from setting up jev-ultrafast as an all-purpose browser skill for Claude Code on macOS (Chrome 154). The skill itself is in [`skills/browser/`](../skills/browser/SKILL.md).

## Running Jev through OpenRouter

- TypeSafe's `/v1/systemone` API is served by OpenRouter: base URL `https://openrouter.ai/api`, model `~typesafe/jev-latest`, OpenRouter key as the bearer token. The same request body works unchanged.
- That model does not appear in OpenRouter's model list. The listed `typesafe/jev-router` is a different product: a chat router that picks another LLM (a test call was served by `openai/gpt-6-luna`). It has no choice/probability API.
- Source: TypeSafe SDK docs, "Configuring the base URL" (found via Context7 `/websites/typesafe_ai`).
- Setup here: `TYPESAFE_BASE_URL=https://openrouter.ai/api`, `TYPESAFE_MODEL=~typesafe/jev-latest`, `TYPESAFE_API_KEY=<OpenRouter key>`. The text helper (`inception/mercury-2.5`, reasoning off) uses the same key.
- Cost: about $0.00006 per decision (~1,500 input tokens). A 60-action runaway loop cost about $0.02.

## Jev is a decision model, not a reader

Split every browser task:

| Work | Tool |
|---|---|
| Page to data (cards, grids, pagination) | browser-harness `js(...)`; screenshots when the DOM is opaque |
| Exact computation (cheapest, totals) | Python |
| Judgment over items | Jev via `skills/browser/classify.py` |
| What to click next | jev agent (`skills/browser/jev.py`) |
| Ambiguous intent | Claude or the user |

Evidence, Idealista Sants-Montjuïc (1,113 listings under 500k EUR), "is this a real loft or duplex?":
- Keyword regex (dúplex, loft, doble altura, altillo...): 52 matches, including 13 small studios only marketed as "estilo loft", and missed a "tríplex".
- Jev, one systemone request per listing: 36 s, $0.027. Excluded all marketing-only lofts, found the tríplex, kept the same 35 real duplexes. Its three disagreements with regex had probabilities 0.52 to 0.64: treat under ~0.7 as "check manually".

## Agent behavior

- **Background tab looked like headless.** Upstream opens its tab with `background=True` and the example closes it at the end, so the user sees nothing. This fork opens it in the foreground; the skill runner leaves it open.
- **Custom dropdowns cause loops.** On Idealista's price "Máx" control, jev alternated "open dropdown" and "click the list" for all 60 actions (each step changed the page, so the 3-no-change guard never fired). This fork marks `blocked` when the last 6 non-wait actions use at most 2 distinct actions: the same run now stops in 6 steps / 2.3 s.
- **Where jev shines:** single, well-labelled interactions. Google Flights "open the Date grid" took 1 action, 1.4 s.
- **URL filters beat interaction** for search sites: Idealista `.../hostafrancs/con-precio-hasta_500000/`, Google Flights `?q=Flights from BCN to DXB on 2027-01-11 returning 2027-01-18 nonstop&curr=EUR&hl=en`.

## Chrome connection (browser-harness)

- One-time: enable `chrome://inspect/#remote-debugging`. Without it the daemon log says `DevToolsActivePort not found`.
- Chrome may show "Allow remote debugging?" when the daemon (re)connects; `browser-harness mac-approve` clicks it.
- Bot protection: Idealista serves a DataDome challenge (empty title/text, `captcha-delivery.com` iframe). The user solves it once in the visible tab; the cookie then covers automated tabs in the same profile.
- `list_tabs()` includes tabs marked with the 🐴 title prefix (harness-attached). When switching to the agent's tab, filter on URL *and* exclude the marker, or you attach to the wrong one.
- Pages opened by jev render at 1120 px wide (device metrics override), which matters when mapping screenshot pixels to click coordinates.

## Open issues

- **Intermittent `Input.dispatchMouseEvent timed out after 5s`** (~1 in 3 jev runs, also ~3 in 11 isolated clicks). Not explained by window visibility or minimizing. The click may or may not land.
- **Intermittent "Text helper returned no valid field value"** (2 occurrences, not reproducible in 13 retries). `skills/browser/jev.py` now records the raw reply as `text_reply` when it happens.
- **Shared HTTP/2 `httpx.Client` across threads** fails with `ReadError: [Errno 35]` under parallel load; `classify.py` uses HTTP/1.1.
- **Click by label, never by position fallback.** A "nearest button" fallback once targeted Google Flights' "Clear Stops" behind a modal.
