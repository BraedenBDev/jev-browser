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
from concurrent.futures import ThreadPoolExecutor

import httpx


def classify_items(items, fields, question, criteria, workers=8):
    """Return items with a `jev` verdict added. criteria: {choice_key: description}."""
    base = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")
    model = os.environ.get("TYPESAFE_MODEL", "jev-latest")
    key = os.environ["TYPESAFE_API_KEY"]
    client = httpx.Client(timeout=30)  # HTTP/1.1: a shared HTTP/2 connection breaks under threads
    totals = {"cost": 0.0}

    def one(item):
        body = {
            "model": model,
            "state": {f: item.get(f) for f in fields},
            "questions": {"q": {"type": "choice", "instructions": question, "criteria": criteria}},
        }
        r = None
        for _ in range(3):
            try:
                r = client.post(f"{base}/v1/systemone", json=body, headers={"Authorization": f"Bearer {key}"})
            except httpx.HTTPError:
                continue
            if r.status_code not in {429, 502, 503, 529}:
                break
        if r is None or r.is_error:
            return {**item, "jev": {"error": f"HTTP {r.status_code if r else 'connection failed'}"}}
        data = r.json()
        totals["cost"] += data.get("usage", {}).get("cost", 0) or 0
        a = data["answers"]["q"]
        return {**item, "jev": {k: a[k] for k in ("choice", "confidence", "probabilities")}}

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(one, items))
    client.close()
    return results, round(totals["cost"], 5)


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
