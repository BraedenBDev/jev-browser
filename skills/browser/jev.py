"""Run one jev-ultrafast goal in the user's Chrome and print a JSON report.

uv run --project ~/Developer/jev-browser --env-file ~/Developer/jev-browser/.env \
  python ~/.claude/skills/browser/jev.py --url URL --goal 'goal' [--text-chars 4000]
"""

import argparse
import json
import sys

import jev_ultrafast.model as model
from jev_ultrafast import Agent

# Keep the last text-helper reply so an intermittent "no valid field value" failure is diagnosable.
last_text_reply = None
_post_json = model.post_json


def _spy(url, key, body):
    global last_text_reply
    result = _post_json(url, key, body)
    if url.endswith("/chat/completions"):
        choice = (result.get("choices") or [{}])[0]
        last_text_reply = {"content": choice.get("message", {}).get("content"), "finish": choice.get("finish_reason"),
                           "provider": result.get("provider")}
    return result


model.post_json = _spy

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--goal", action="append", required=True, help="Repeat for an ordered list of goals.")
parser.add_argument("--text-chars", type=int, default=4000, help="Visible page text to return (0 = none).")
args = parser.parse_args()

state, error = None, None
try:
    # No context manager: the tab stays open so the user can see the result.
    agent = Agent(args.url, args.goal)
    state = agent.snapshot()
    for state in agent.run():
        pass
except Exception as e:  # report partial progress instead of a bare traceback
    error = f"{type(e).__name__}: {e}"

page = (state or {}).get("page", {})
report = {
    "status": "error" if error else (state or {}).get("status"),
    "error": error,
    **({"text_reply": last_text_reply} if error and "Text helper" in error else {}),
    "elapsed_ms": (state or {}).get("elapsed_ms"),
    "actions": [
        {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in (state or {}).get("history", [])
    ],
    "url": page.get("url"),
    "title": page.get("title"),
    "text": (page.get("text") or "")[: args.text_chars],
}
print(json.dumps(report, ensure_ascii=False, indent=1))
sys.exit(0 if report["status"] == "done" else 1)
