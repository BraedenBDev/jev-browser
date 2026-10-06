#!/bin/sh
# Real Google Chrome for jev-browser, on the persistent Xvfb display (jev-xvfb.service) so you
# can VNC in (jev-vnc.service), log into sites and solve challenges once, and the profile keeps
# the cookies. Automation attaches to the SAME browser over CDP (127.0.0.1:9333).
#
# No --no-sandbox by default: the google-chrome .deb installs a SUID sandbox that works even
# with unprivileged userns restricted. Set JEV_NO_SANDBOX=1 only if Chrome won't start.
# WebGL uses SwiftShader (no GPU on the VPS); a manually-solved DataDome cookie is what carries
# past the fingerprint, which is why the VNC warm-up matters. Page traffic uses JEV_PROXY.
set -u
CHROME="$(command -v google-chrome-stable || echo /usr/bin/google-chrome-stable)"
PROFILE="$HOME/.jev-browser/chrome-profile"
mkdir -p "$PROFILE"
export DISPLAY="${JEV_DISPLAY:-:99}"
PROXY=""
[ -n "${JEV_PROXY:-}" ] && PROXY="--proxy-server=${JEV_PROXY} --proxy-bypass-list=<-loopback>"

set -- --use-angle=swiftshader --enable-unsafe-swiftshader \
  --disable-blink-features=AutomationControlled \
  --lang=es-ES --accept-lang=es-ES,es \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port="${JEV_CDP_PORT:-9333}" \
  --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check \
  --disable-dev-shm-usage --window-size=1280,900
[ -n "${JEV_UA:-}" ] && set -- "$@" --user-agent="$JEV_UA"
[ "${JEV_NO_SANDBOX:-0}" = "1" ] && set -- "$@" --no-sandbox

exec "$CHROME" "$@" $PROXY about:blank
