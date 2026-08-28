#!/usr/bin/env python3
"""delete_tweets.py — delete our own tweets by id, with a paper trail.

Deletion is irreversible, so nothing happens without --confirm, and every
removed item's queue record moves to deleted/ instead of vanishing.

Usage:
  python delete_tweets.py <tweet_id> [<tweet_id> ...]            # dry run
  python delete_tweets.py <tweet_id> [...] --confirm             # actually delete
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _twikit_patch  # noqa: F401
from twikit import Client  # type: ignore

from _paths import bot_home  # noqa: E402

DATA = bot_home()
POSTED_DIR = DATA / "posted"
DELETED_DIR = DATA / "deleted"
LOG_FILE = DATA / "logs" / "delete.log"
COOKIES_PATH = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES", str(DATA / "cookies" / "cdpilot_dev.json")))
LANG = os.environ.get("CDPILOT_TWIKIT_LANG", "en-US")


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _record_for(tweet_id: str):
    for f in POSTED_DIR.glob("*.json"):
        try:
            if str(json.loads(f.read_text()).get("tweet_id")) == str(tweet_id):
                return f
        except Exception:
            continue
    return None


async def main() -> None:
    ids = [a for a in sys.argv[1:] if not a.startswith("--")]
    confirm = "--confirm" in sys.argv
    if not ids:
        print(__doc__)
        sys.exit(1)

    plan = [(tid, _record_for(tid)) for tid in ids]
    for tid, rec in plan:
        label = rec.name if rec else "no local record"
        print(f"{'DELETE' if confirm else 'would delete'} {tid} ({label})")
    if not confirm:
        print("\nDry run — pass --confirm to delete.")
        return

    client = Client(LANG)
    client.load_cookies(str(COOKIES_PATH))
    DELETED_DIR.mkdir(parents=True, exist_ok=True)

    ok, fail = 0, 0
    for tid, rec in plan:
        try:
            await client.delete_tweet(tid)
        except Exception as e:
            fail += 1
            _log(f"delete {tid} FAILED: {e!r}")
            continue
        ok += 1
        _log(f"deleted {tid}")
        if rec:
            item = json.loads(rec.read_text())
            item["deleted_at"] = int(time.time())
            (DELETED_DIR / rec.name).write_text(
                json.dumps(item, ensure_ascii=False, indent=2))
            rec.unlink()
        await asyncio.sleep(3)  # spacing, not a burst

    print(json.dumps({"deleted": ok, "failed": fail}))


if __name__ == "__main__":
    asyncio.run(main())
