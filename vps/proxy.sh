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
PORT=13128
mkdir -p "$(dirname "$ENVF")" "$(dirname "$AUDIT")"

apply() {  # $1=env line (empty => proxy off)  $2=audit  $3=telegram title  $4=level  $5=stdout
  if [ -n "$1" ]; then printf '%s\n' "$1" > "$ENVF"; else : > "$ENVF"; fi
  chmod 600 "$ENVF"
  systemctl --user restart jev-chrome.service
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$2" >> "$AUDIT"
  "$HOME/.local/bin/ops-notify" --topic spend --level "$4" --source jev-proxy --title "$3" >/dev/null 2>&1 || true
  echo "$5"
}

case "${1:-status}" in
  on)
    reason="${2:-}"
    [ -z "$reason" ] && { echo "REFUSED: 'on' needs a reason authorized by Braeden. usage: proxy.sh on \"<reason>\""; exit 2; }
    apply "JEV_PROXY=127.0.0.1:$PORT" "ON  reason=$reason" \
      "Residential proxy turned ON (burns IPRoyal GB) - $reason" warning \
      "proxy ON -> residential (Chrome restarted). Reason: $reason. Turn OFF when done." ;;
  off)
    apply "" "OFF reason=${2:-task done}" \
      "Residential proxy turned OFF (back to datacenter IP)" info \
      "proxy OFF -> direct datacenter IP (Chrome restarted)." ;;
  status)
    if grep -q '^JEV_PROXY=.' "$ENVF" 2>/dev/null; then echo "proxy: ON (residential)"; else echo "proxy: OFF (direct)"; fi ;;
  *)
    echo "usage: proxy.sh on \"<reason>\" | off | status"; exit 1 ;;
esac
