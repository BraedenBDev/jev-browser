"""Local spend ledger for Control Room usage tracking.

jev/OpenRouter cost and context.dev credit balance are appended to ~/.jev-browser/spend.jsonl
by the runtime; vps/spend-collector.py rolls it up and pushes quotas to Control Room.
Logging is fail-safe: it never raises into the caller.
"""
import datetime
import json
import os
import pathlib
import time

LEDGER = os.path.expanduser("~/.jev-browser/spend.jsonl")


def log_spend(kind, **fields):
    """kind='jev' with usd=<float>, or kind='context' with credits_remaining/credits_consumed."""
    try:
        p = pathlib.Path(LEDGER)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps({"ts": round(time.time(), 3), "kind": kind, **fields}) + "\n")
    except Exception:
        pass


def rollup(now=None):
    """{jev_usd_today, jev_calls_today, context_credits_remaining, context_observed_at}."""
    now = now or time.time()
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
