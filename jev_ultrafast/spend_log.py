"""Local spend ledger for Control Room usage tracking.

jev/OpenRouter cost and context.dev credit balance are appended to ~/.jev-browser/spend.jsonl
by the runtime; vps/spend-collector.py rolls it up and pushes quotas to Control Room.
Logging is fail-safe: it never raises into the caller. The rollup lives in spend-collector.py
(which runs under system python3 and cannot import this package); keep the ledger schema
{ts, kind, usd | credits_remaining | credits_consumed} in sync with it.
"""
import json
import os
import time

LEDGER = os.path.expanduser("~/.jev-browser/spend.jsonl")
try:  # once, not per call
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
except OSError:
    pass


def log_spend(kind, **fields):
    """kind='jev' with usd=<float>, or kind='context' with credits_remaining/credits_consumed."""
    try:
        with open(LEDGER, "a") as f:
            f.write(json.dumps({"ts": round(time.time(), 3), "kind": kind, **fields}) + "\n")
    except Exception:
        pass
