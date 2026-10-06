"""Classify extracted items with Jev (TypeSafe System One via OpenRouter): one choice + probabilities per item.

uv run --project ~/Developer/jev-browser --env-file ~/Developer/jev-browser/.env \
  python ~/.claude/skills/browser/classify.py --items items.json --fields title,desc,details \
  --question 'What kind of home is this?' \
  --choice loft='Open-plan loft, converted/industrial space, double height' \
  --choice other='Anything else' --out classified.json

items.json is a JSON list of objects. Each item's selected fields become Jev's `state`; Jev picks one --choice.
Prints a summary; --out writes every item with `jev: {choice, confidence, probabilities}` added.
"""

import argparse
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--items", required=True)
parser.add_argument("--fields", required=True, help="Comma-separated item fields to send as state.")
parser.add_argument("--question", required=True)
parser.add_argument("--choice", action="append", required=True, help="key='description' (repeat, at least 2).")
parser.add_argument("--out")
parser.add_argument("--workers", type=int, default=8)
args = parser.parse_args()

criteria = dict(c.split("=", 1) for c in args.choice)
if len(criteria) < 2:
    raise SystemExit("Give at least two --choice options.")
fields = args.fields.split(",")
items = json.load(open(args.items))
base = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")
client = httpx.Client(timeout=30)  # HTTP/1.1: a shared HTTP/2 connection breaks under threads
cost = 0.0


def classify(item):
    global cost
    body = {
        "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        "state": {f: item.get(f) for f in fields},
        "questions": {"q": {"type": "choice", "instructions": args.question, "criteria": criteria}},
    }
    r = None
    for _ in range(3):
        try:
            r = client.post(f"{base}/v1/systemone", json=body, headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"})
        except httpx.HTTPError:
            continue
        if r.status_code not in {429, 502, 503, 529}:
            break
    if r is None or r.is_error:
        return {**item, "jev": {"error": f"HTTP {r.status_code if r else 'connection failed'}"}}
    data = r.json()
    cost += data.get("usage", {}).get("cost", 0) or 0
    a = data["answers"]["q"]
    return {**item, "jev": {k: a[k] for k in ("choice", "confidence", "probabilities")}}


with ThreadPoolExecutor(args.workers) as pool:
    results = list(pool.map(classify, items))

if args.out:
    json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=1)
counts = Counter(r["jev"].get("choice", "error") for r in results)
print(json.dumps({"items": len(results), "counts": dict(counts), "cost_usd": round(cost, 5), "out": args.out}))
