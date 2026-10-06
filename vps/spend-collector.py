#!/usr/bin/env python3
"""Roll up jev spend + context.dev credits from the local ledger and push them to Control Room
as two quota windows: jev $/day budget and context.dev credits/month. Control Room's existing
quota-alert logic then warns and pages Telegram at 90%+. The ingest token is read from the
control-room unit's own environment; nothing secret is written to disk."""
import datetime
import json
import os
import subprocess
import urllib.request

CONTROL_ROOM = os.environ.get("CONTROL_ROOM_URL", "http://127.0.0.1:8780")
JEV_DAILY_BUDGET = float(os.environ.get("JEV_DAILY_BUDGET_USD", "2"))
CONTEXT_MONTHLY_CREDITS = int(os.environ.get("CONTEXT_MONTHLY_CREDITS", "7500"))
LEDGER = os.path.expanduser("~/.jev-browser/spend.jsonl")


def rollup(now=None):
    """Self-contained (no jev_ultrafast import, so system python3 can run it)."""
    now = now or datetime.datetime.now(datetime.timezone.utc).timestamp()
    day0 = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()
    jev_usd, jev_calls, ctx_rem, ctx_ts = 0.0, 0, None, None
    try:
        with open(LEDGER) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("kind") == "jev" and r.get("ts", 0) >= day0:
                    jev_usd += float(r.get("usd") or 0)
                    jev_calls += 1
                elif r.get("kind") == "context" and r.get("credits_remaining") is not None:
                    if ctx_ts is None or r["ts"] > ctx_ts:
                        ctx_rem, ctx_ts = r["credits_remaining"], r["ts"]
    except FileNotFoundError:
        pass
    return {"jev_usd_today": round(jev_usd, 6), "jev_calls_today": jev_calls,
            "context_credits_remaining": ctx_rem, "context_observed_at": ctx_ts}


def ingest_token():
    tok = os.environ.get("USAGE_INGEST_TOKEN")
    if tok:
        return tok
    pid = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "--value", "control-room.service"],
                         capture_output=True, text=True).stdout.strip()
    for part in open(f"/proc/{pid}/environ", "rb").read().split(b"\0"):
        if part.startswith(b"USAGE_INGEST_TOKEN="):
            return part.split(b"=", 1)[1].decode()
    raise SystemExit("USAGE_INGEST_TOKEN not found (control-room not running?)")


def main():
    r = rollup()
    now = datetime.datetime.now(datetime.timezone.utc)
    midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    jev_pct = min(100, r["jev_usd_today"] / JEV_DAILY_BUDGET * 100) if JEV_DAILY_BUDGET else 0
    quotas = [{
        "id": "jev-spend", "plan": f"${JEV_DAILY_BUDGET:.2f}/day budget",
        "details": [f"${r['jev_usd_today']:.4f} of ${JEV_DAILY_BUDGET:.2f} today ({r['jev_calls_today']} calls)"],
        "windows": [{"label": "Daily spend", "used_percent": jev_pct,
                     "reset_at": midnight.isoformat(), "window_seconds": 86400}],
    }]
    rem = r["context_credits_remaining"]
    if rem is not None:
        used = max(0, CONTEXT_MONTHLY_CREDITS - rem)
        first_next = (now.replace(day=1) + datetime.timedelta(days=32)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0)
        quotas.append({
            "id": "context-dev", "plan": f"Developer · {CONTEXT_MONTHLY_CREDITS:,} credits/mo",
            "details": [f"{used:,} of {CONTEXT_MONTHLY_CREDITS:,} credits used; {rem:,} left"],
            "windows": [{"label": "Monthly credits", "used_percent": min(100, used / CONTEXT_MONTHLY_CREDITS * 100),
                         "reset_at": first_next.isoformat(), "window_seconds": 2592000}],
        })
    body = json.dumps({"quotas": quotas, "activity": []}).encode()
    req = urllib.request.Request(f"{CONTROL_ROOM}/api/usage/ingest/quotas", data=body,
                                 headers={"Content-Type": "application/json", "x-usage-token": ingest_token()},
                                 method="POST")
    resp = json.load(urllib.request.urlopen(req, timeout=15))
    print(f"pushed {resp} | jev ${r['jev_usd_today']} today | context credits left {rem}")


if __name__ == "__main__":
    main()
