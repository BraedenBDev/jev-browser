#!/bin/sh
# Chromium for jev-browser on the VPS. CDP on 127.0.0.1:9333.
#
# Runs HEADFUL under Xvfb by default: --headless=new is fingerprinted by DataDome/Cloudflare
# even with a spoofed UA, whereas a real browser on a virtual display is far harder to flag.
# Set JEV_HEADLESS=1 to force true headless.
#
# Page traffic routes through JEV_PROXY when set (the residential relay); --proxy-bypass-list
# <-loopback> is defence-in-depth only (see vps/chrome.sh history / docs/learnings.md:
# the authoritative internal-SSRF boundary is a fail-closed cgroup/netns firewall).
set -u
CHROME=$(ls -d "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux*/chrome | tail -1)
PROFILE="$HOME/.jev-browser/chrome-profile"
mkdir -p "$PROFILE"
PROXY=""
[ -n "${JEV_PROXY:-}" ] && PROXY="--proxy-server=${JEV_PROXY} --proxy-bypass-list=<-loopback>"
UA="${JEV_UA:-Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36}"

set -- --no-sandbox \
  --use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader \
  --disable-blink-features=AutomationControlled \
  --user-agent="$UA" --lang=es-ES --accept-lang=es-ES,es \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port="${JEV_CDP_PORT:-9333}" \
  --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check \
  --disable-background-networking --disable-dev-shm-usage \
  --window-size=1280,900 $PROXY about:blank

if [ "${JEV_HEADLESS:-0}" = "1" ]; then
  exec "$CHROME" --headless=new "$@"
else
  exec xvfb-run -a --server-args="-screen 0 1280x900x24" "$CHROME" "$@"
fi
