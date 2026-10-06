#!/bin/sh
# Turn the VPS Chrome's residential proxy (IPRoyal, via jev-proxy relay) on or off.
#
#   off (default)  Chrome goes direct (datacenter IP). Burns NO residential traffic.
#                  Fine for general browsing and for context.dev-handled sites (DataDome).
#   on             Chrome routes ALL traffic through the relay -> IPRoyal residential.
#                  Costs GB (incl. Chrome background networking). Use only when a task needs
#                  a residential IP that context.dev can't cover.
#
# Changing it restarts Chrome (the proxy is a launch flag).
set -u
ENVF="$HOME/jev-browser/vps/chrome.env"
mkdir -p "$(dirname "$ENVF")"
case "${1:-status}" in
  on)
    printf 'JEV_PROXY=127.0.0.1:13128\n' > "$ENVF"; chmod 600 "$ENVF"
    systemctl --user restart jev-chrome.service
    echo "proxy ON  -> residential (Chrome restarted). Watch usage: Control Room 'IPRoyal' quota." ;;
  off)
    : > "$ENVF"; chmod 600 "$ENVF"
    systemctl --user restart jev-chrome.service
    echo "proxy OFF -> direct datacenter IP (Chrome restarted). No residential traffic." ;;
  status)
    if grep -q '^JEV_PROXY=.' "$ENVF" 2>/dev/null; then echo "proxy: ON (residential)"; else echo "proxy: OFF (direct)"; fi ;;
  *)
    echo "usage: proxy.sh on|off|status"; exit 1 ;;
esac
