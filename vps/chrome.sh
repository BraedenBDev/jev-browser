#!/bin/sh
# Headless Chromium for jev-browser on the VPS. CDP on 127.0.0.1:9333.
# Page traffic (not the CDP control channel) routes through JEV_PROXY when set,
# e.g. a Spain residential endpoint. --proxy-server takes host:port only; use the
# provider's IP-whitelist auth (whitelist this VPS's public IP) so no credentials
# are needed in the URL. chrome.env (loaded by the systemd unit) carries JEV_PROXY.
set -u
CHROME=$(ls -d "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux*/chrome | tail -1)
PROFILE="$HOME/.jev-browser/chrome-profile"
mkdir -p "$PROFILE"
PROXY=""
# With a proxy set, route ALL traffic through it (<-loopback> removes Chromium's implicit
# localhost bypass) so a general-purpose browsing agent cannot reach this VPS's own internal
# services (127.0.0.1, 169.254.169.254, RFC1918) no matter where a page or goal steers it.
# The residential proxy is on an external network and cannot reach the box's loopback/private
# ranges, so this is the egress deny that keeps the general skill from doing SSRF internally.
[ -n "${JEV_PROXY:-}" ] && PROXY="--proxy-server=${JEV_PROXY} --proxy-bypass-list=<-loopback>"
exec "$CHROME" --headless=new --no-sandbox --disable-gpu \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port="${JEV_CDP_PORT:-9333}" \
  --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check \
  --disable-background-networking --disable-dev-shm-usage \
  --window-size=1280,900 $PROXY about:blank
