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

## VPS deployment (Hermes, 2026-10-06)

Target: `vps-personal` (openclaw@srv1289614, Ubuntu 24.04, systemd --user with lingering on).

- **Headless Chromium** runs as a user service `jev-chrome.service` (`vps/chrome.sh` + `vps/jev-chrome.service`), CDP on 127.0.0.1:9333, `--no-sandbox` (kernel restricts unprivileged userns), auto-restart. browser-harness connects with `BU_CDP_URL=http://127.0.0.1:9333`.
- **OpenRouter via Agent Vault.** Secrets never sit in plaintext on this box; `agent-vault` is a MITM egress broker. The process holds only the placeholder `__openrouter_api_key__` (safe to write in `.env`); the broker swaps the real key into the header at egress to openrouter.ai (`services.yaml` lists the `openrouter` service). Run jev under `agent-vault run -- finish_env.sh ...` (`vps/run-wrapped.sh`). `finish_env.sh` sets `SSL_CERT_FILE` to a combined CA bundle; OpenSSL honors it, so httpx needs **no** code change (default verify works through the MITM). Proven: `systemone` returns 200 from TypeSafe through the broker.
- **Session auth:** `agent-vault run` needs a session; Hermes jobs already have `AGENT_VAULT_TOKEN`/`ADDR` in env. `run-wrapped.sh` borrows them from the running `hermes-gateway` unit for standalone runs (never writes them to disk). There's a pre-stubbed `JEV_OPENROUTER_API_KEY` placeholder too, if a Jev-specific key is ever wanted.
- **Skill:** `apartment-search` (Hermes skill at `skills/hermes/apartment-search/`, copied to `~/.hermes/skills/productivity/apartment-search/SKILL.md`). Built on `apartment_search.py` (URL + extract + `classify_items` + rank). Proven end to end on the Mac against real Idealista; on the VPS it runs, connects, and correctly fails with a bot-challenge message until a residential proxy is wired.
- **Separation:** only the Python process goes through the broker (for the key). Chromium is a separate service, so its page traffic is independent and is where the residential proxy attaches (`JEV_PROXY` in `vps/chrome.env`).
- **Open wire-points:** (1) IPRoyal residential proxy (IP-whitelist the VPS, Spain sticky endpoint) into `chrome.env`; (2) confirm Idealista loads through it from the VPS; (3) if challenges persist, fingerprint hardening.

## VPS egress boundary (general-purpose agent, SSRF)

The `browser` skill (jev/bh) is general-purpose by design: it browses wherever a goal or
page link leads, so it CANNOT be host-allowlisted (that is only right for a site-specific
extractor like `apartment_search.py`). On a VPS that means a steered or prompt-injected
agent could try to reach the box's own internals: the agent-vault broker (127.0.0.1:14321),
Hermes dashboards, the cloud metadata IP (169.254.169.254), RFC1918 hosts.

What is NOT a sufficient control:
- `--proxy-server` + `--proxy-bypass-list=<-loopback>` (in `chrome.sh`): defence in depth
  only. **Fail-open** (no proxy -> no protection) and **bypassable** (a proxy is a routing
  preference; WebRTC/DNS/non-HTTP paths route around it). Do not treat it as the boundary.
- Per-skill URL allowlists: correct for a single-site extractor, useless for a general agent.

The authoritative control is a **fail-closed network egress firewall scoped to the browser**,
applied as root. A box-wide drop to private ranges would break Hermes (it needs localhost
services), so it must be scoped to the Chromium process. Two ways, both a root/infra wire-point:

1. **Reuse agent-vault container isolation (preferred, lazy).** agent-vault's `run
   --isolation=container` already applies an iptables egress firewall (`--no-firewall` opts
   out, so it is default-on). Running the browsing stack there reuses a tested boundary
   instead of hand-rolled nft. Cost: Chromium moves into the container; CDP must be exposed
   to the host or the agent runs inside too. Architecture change -> confirm with Braeden.
2. **nftables scoped to the jev-chrome.service cgroup (standalone).** Drop egress from that
   cgroup to 127.0.0.0/8, 10/8, 172.16/12, 192.168/16, 169.254.0.0/16, ::1, fc00::/7,
   fe80::/10, allowing only the proxy endpoint + DNS. Match via `socket cgroupv2 level ...`
   for the unit's v2 cgroup. Version-sensitive; review and test before relying on it. Not
   written/tested here because this session is non-root.

Until one of these is in place, treat the VPS general agent as able to reach internal
services, and do not point it at untrusted pages on that box.

### agent-vault container isolation: tested, does NOT fit browsing (2026-10-06)

Empirically probed `agent-vault run --isolation=container` egress (v0.39.3): default-DENY
firewall (`-A OUTPUT -o lo ACCEPT`, `conntrack ESTABLISHED ACCEPT`, drop rest) plus a
transparent MITM proxy that allows only hosts in `scripts/agent-vault/services.yaml`
(tavily, openrouter, github, context-dev, ...), MITMing each for secret injection. Direct
egress to everything (example.com, 1.1.1.1, idealista.com, 127.0.0.1, 169.254.*, 10.*) all
returned 000. So it is an API-egress allowlist broker, not a network sandbox for a browser:
forcing a browser through it would need every site allowlisted AND the MITM breaks both the
IPRoyal CONNECT tunnel and the residential exit IP. Verdict: wrong tool for the general
(and the Idealista) browsing use.

Right boundary instead: a fail-closed egress firewall scoped to the Chromium cgroup/netns
that allows ONLY the IPRoyal endpoint (+DNS) and denies all else. Since all browsing must
exit via IPRoyal anyway, the only reachable destination is IPRoyal (which reaches arbitrary
sites), so "browse anywhere" works while internal SSRF is impossible. Needs root.

## DataDome on Idealista: residential + headful not enough (2026-10-06)

Built the full anti-block stack on the VPS and it still hard-blocks on Idealista's DataDome:
- Residential exit via IPRoyal relay: confirmed Barcelona IPs (MasMovil/Orange, postal 08007). WORKS.
- Headful Chromium under Xvfb (not --headless): webdriver=false, UA spoofed to Win Chrome. WORKS.
- WebGL: --disable-gpu gave a NULL context (instant bot tell); switched to SwiftShader
  (--use-angle=swiftshader --enable-unsafe-swiftshader) so a context exists.
- Result: DataDome interstitial from the FIRST request, no auto-redirect over 27s, every time.

Diagnosis: the block is first-contact, so it is fingerprint/IP-reputation, not IP rotation
(sticky session would not help). Remaining tells vanilla Chromium can't fix cheaply: SwiftShader
renderer (not a real GPU), TLS/JA3 of Chrome-for-Testing, canvas/audio fingerprint, and possibly
the IPRoyal pool being known to DataDome. Beating it needs a stealth stack that spoofs
canvas/WebGL/TLS (nodriver/patchright/camoufox or commercial anti-detect) or a DataDome-solving
API (context.dev/ZenRows/Bright Data Web Unlocker) or Idealista's official API. Not an
incremental-flag fix.

Everything built is reusable and works on sites without DataDome-grade protection: the VPS jev
stack, the vault-backed residential relay (vps/proxy_relay.py + jev-proxy.service), headful
Chromium (vps/chrome.sh), and the apartment-search skill. Idealista specifically is the wall.
