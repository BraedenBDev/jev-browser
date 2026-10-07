"""Classify items with Jev (TypeSafe System One via OpenRouter): one choice + probabilities per item.

Library:  from classify import classify_items
CLI:
  uv run --project ~/Developer/jev-browser --env-file .env \
    python classify.py --items items.json --fields title,desc,details \
    --question 'What kind of home is this?' \
    --choice loft='Open-plan loft, converted space, double height' \
    --choice other='Anything else' --out classified.json

items is a JSON list of objects; each item's selected fields become Jev's `state`.
Each result item gets `jev: {choice, confidence, probabilities}` (or `{error}`).
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

try:  # skill -> package import; logging is best-effort, so a missing package is harmless
    from jev_ultrafast.spend_log import log_spend
except Exception:
    def log_spend(*_a, **_k):
        pass


def classify_items(items, fields, question, criteria, workers=8):
    """Return (items with a `jev` verdict added, total cost). criteria: {choice_key: description}."""
    base = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")
    model = os.environ.get("TYPESAFE_MODEL", "jev-latest")
    key = os.environ["TYPESAFE_API_KEY"]
    client = httpx.Client(timeout=30)  # HTTP/1.1: a shared HTTP/2 connection breaks under threads

    def one(item):
        """-> (result_item, cost). No shared mutable state, so it is thread-safe."""
        body = {
            "model": model,
            "state": {f: item.get(f) for f in fields},
            "questions": {"q": {"type": "choice", "instructions": question, "criteria": criteria}},
        }
        r = None
        for attempt in range(3):
            try:
                r = client.post(f"{base}/v1/systemone", json=body, headers={"Authorization": f"Bearer {key}"})
            except httpx.HTTPError:
                r = None
            if r is not None and r.status_code not in {429, 502, 503, 529}:
                break
            if attempt < 2:
                time.sleep(0.5 * 2 ** attempt)  # back off before retrying a rate-limited/5xx call
        if r is None or r.is_error:
            return {**item, "jev": {"error": f"HTTP {r.status_code if r else 'connection failed'}"}}, 0.0
        try:  # a 200 with unexpected JSON must not crash the whole batch
            data = r.json()
            a = data["answers"]["q"]
            verdict = {k: a[k] for k in ("choice", "confidence", "probabilities")}
        except (ValueError, KeyError, TypeError) as e:
            return {**item, "jev": {"error": f"bad response: {type(e).__name__}"}}, 0.0
        return {**item, "jev": verdict}, (data.get("usage", {}).get("cost", 0) or 0)

    with ThreadPoolExecutor(workers) as pool:
        pairs = list(pool.map(one, items))
    client.close()
    results = [item for item, _ in pairs]
    cost = round(sum(c for _, c in pairs), 5)
    log_spend("jev", usd=cost, call="classify", n=len(items))
    return results, cost


def _main():
    import argparse
    from collections import Counter

    p = argparse.ArgumentParser()
    p.add_argument("--items", required=True)
    p.add_argument("--fields", required=True, help="Comma-separated item fields to send as state.")
    p.add_argument("--question", required=True)
    p.add_argument("--choice", action="append", required=True, help="key='description' (repeat, >=2).")
    p.add_argument("--out")
    p.add_argument("--workers", type=int, default=8)
    args = p.parse_args()

    criteria = dict(c.split("=", 1) for c in args.choice)
    if len(criteria) < 2:
        raise SystemExit("Give at least two --choice options.")
    items = json.load(open(args.items))
    results, cost = classify_items(items, args.fields.split(","), args.question, criteria, args.workers)
    if args.out:
        json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=1)
    counts = Counter(r["jev"].get("choice", "error") for r in results)
    print(json.dumps({"items": len(results), "counts": dict(counts), "cost_usd": cost, "out": args.out}))


if __name__ == "__main__":
    _main()
