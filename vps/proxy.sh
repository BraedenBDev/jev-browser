#!/bin/sh
# Turn the VPS Chrome's residential proxy (IPRoyal, via jev-proxy relay) on or off.
#
#   off (default)  Chrome goes direct (datacenter IP). Burns NO residential traffic.
#   on <reason>    Chrome routes ALL traffic through IPRoyal residential (costs metered GB).
#
# Turning it ON requires Braeden's EXPLICIT authorization and a reason (audited + Telegram-
# alerted). Hermes must not turn it on autonomously. Turning it off is always safe. Changing
# it restarts Chrome (the proxy is a launch flag).
set -u
ENVF="$HOME/jev-browser/vps/chrome.env"
AUDIT="$HOME/.jev-browser/proxy-toggle.log"
mkdir -p "$(dirname "$ENVF")" "$(dirname "$AUDIT")"
note() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$1" >> "$AUDIT"; }
notify() { "$HOME/.local/bin/ops-notify" --topic spend --level "${2:-info}" --source jev-proxy --title "$1" >/dev/null 2>&1 || true; }

case "${1:-status}" in
  on)
    reason="${2:-}"
    if [ -z "$reason" ]; then
      echo "REFUSED: 'on' needs a reason authorized by Braeden. usage: proxy.sh on \"<reason>\""; exit 2
    fi
    printf 'JEV_PROXY=127.0.0.1:13128\n' > "$ENVF"; chmod 600 "$ENVF"
    systemctl --user restart jev-chrome.service
    note "ON  reason=$reason"
    notify "Residential proxy turned ON (burns IPRoyal GB) - $reason" warning
    echo "proxy ON -> residential (Chrome restarted). Reason: $reason. Turn OFF when done." ;;
  off)
    : > "$ENVF"; chmod 600 "$ENVF"
    systemctl --user restart jev-chrome.service
    note "OFF reason=${2:-task done}"
    notify "Residential proxy turned OFF (back to datacenter IP)" info
    echo "proxy OFF -> direct datacenter IP (Chrome restarted)." ;;
  status)
    if grep -q '^JEV_PROXY=.' "$ENVF" 2>/dev/null; then echo "proxy: ON (residential)"; else echo "proxy: OFF (direct)"; fi ;;
  *)
    echo "usage: proxy.sh on \"<reason>\" | off | status"; exit 1 ;;
esac
