#!/usr/bin/env python3
"""Failed item'ı pending'e revert + scheduled_time +5dk yap."""
import json
from datetime import datetime, timedelta, timezone

QFILE = "/opt/cdpilot-twitter-bot/queue/2026-05-19.json"

with open(QFILE) as f:
    d = json.load(f)

TZ = timezone(timedelta(hours=3))
new_time = (datetime.now(TZ) + timedelta(minutes=5)).replace(microsecond=0)

changed = 0
for p in d["posts"]:
    if p.get("status") == "failed":
        p["status"] = "pending"
        p["error"] = None
        p["scheduled_time"] = new_time.isoformat()
        changed += 1
        print(f"Requeued: {p['id'][:8]} → {p['scheduled_time']}")

with open(QFILE, "w") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)

print(f"Changed {changed} item(s)")
