#!/bin/sh
# Snapshot the managed Chrome profile (cookies, logins, state) to a protected tarball,
# excluding caches so it stays small. Stops Chrome briefly for a consistent cookie DB.
# Keeps the 5 most recent snapshots. Run by hand or from a cron/timer.
set -u
BASE="$HOME/.jev-browser"
OUT="$BASE/backups"
mkdir -p "$OUT"
chmod 700 "$BASE" "$OUT"
TS=$(date +%Y%m%d-%H%M)
systemctl --user stop jev-chrome.service 2>/dev/null
sleep 2
tar czf "$OUT/chrome-profile-$TS.tgz" -C "$BASE" \
  --exclude='chrome-profile/*/Cache' \
  --exclude='chrome-profile/*/Code Cache' \
  --exclude='chrome-profile/*/GPUCache' \
  --exclude='chrome-profile/*/DawnGraphiteCache' \
  --exclude='chrome-profile/*/DawnWebGPUCache' \
  --exclude='chrome-profile/*/Service Worker/CacheStorage' \
  --exclude='chrome-profile/*/component_crx_cache' \
  --exclude='chrome-profile/*/extensions_crx_cache' \
  chrome-profile
chmod 600 "$OUT"/*.tgz 2>/dev/null
systemctl --user start jev-chrome.service 2>/dev/null
ls -1t "$OUT"/chrome-profile-*.tgz | tail -n +6 | xargs -r rm -f
ls -lh "$OUT/chrome-profile-$TS.tgz"
