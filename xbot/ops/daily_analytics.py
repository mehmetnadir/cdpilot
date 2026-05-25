#!/usr/bin/env python3
"""daily_analytics.py — kendi posted tweet'lerimizin metriklerini topla.

Cowork gece (22:00) invocation'da çağrılır. posted/ klasöründeki son N tweet'in
güncel engagement sayılarını twikit ile çeker, daily-log.md'ye günlük özet yazar.

Çıktı:
  ~/cdpilot-twitter-data/daily-log.md (append-only, günlük blok)
  ~/cdpilot-twitter-data/analytics/<date>.json (raw metrics)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
import _twikit_patch  # noqa: F401
from twikit import Client  # type: ignore

DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
POSTED_DIR = DATA / "posted"
ANALYTICS_DIR = DATA / "analytics"
DAILY_LOG = DATA / "daily-log.md"
COOKIES_PATH = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES",
    str(DATA / "cookies" / "cdpilot_dev.json"),
))
LANG = os.environ.get("CDPILOT_TWIKIT_LANG", "en-US")
HANDLE = os.environ.get("CDPILOT_HANDLE", "cdpilot_dev")
LOG_FILE = DATA / "logs" / "analytics.log"


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


async def _collect(days: int) -> dict:
    if not COOKIES_PATH.exists():
        _log(f"cookies missing: {COOKIES_PATH}")
        return {}
    client = Client(LANG)
    client.load_cookies(str(COOKIES_PATH))

    cutoff = time.time() - days * 86400
    posted_files = sorted(POSTED_DIR.glob("*.json"))
    metrics = []
    for f in posted_files:
        try:
            item = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        posted_at = item.get("posted_at", 0)
        if posted_at < cutoff:
            continue
        tid = item.get("tweet_id")
        if not tid:
            continue
        try:
            tw = await client.get_tweet_by_id(tid)
        except Exception as e:
            _log(f"get_tweet {tid} fail: {e}")
            continue
        metrics.append({
            "id": item["id"],
            "tweet_id": tid,
            "kind": item.get("kind"),
            "text": item.get("text", "")[:160],
            "url": item.get("tweet_url"),
            "posted_at": posted_at,
            "likes": getattr(tw, "favorite_count", 0) or 0,
            "replies": getattr(tw, "reply_count", 0) or 0,
            "rt": getattr(tw, "retweet_count", 0) or 0,
            "quotes": getattr(tw, "quote_count", 0) or 0,
            "bookmarks": getattr(tw, "bookmark_count", 0) or 0,
            "views": getattr(tw, "view_count", 0) or 0,
        })

    # Follower count
    try:
        me = await client.get_user_by_screen_name(HANDLE)
        followers = me.followers_count
        following = me.following_count
    except Exception:
        followers = None
        following = None

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": int(time.time()),
        "handle": HANDLE,
        "followers": followers,
        "following": following,
        "tweet_metrics": metrics,
    }


def _write_markdown(snapshot: dict) -> None:
    date = snapshot["date"]
    DAILY_LOG.parent.mkdir(parents=True, exist_ok=True)
    metrics = snapshot.get("tweet_metrics", [])
    metrics_sorted = sorted(metrics, key=lambda x: x.get("views", 0), reverse=True)

    lines = [f"\n## {date}\n"]
    lines.append(f"- **Followers:** {snapshot.get('followers')} (following {snapshot.get('following')})")
    lines.append(f"- **Tweets tracked:** {len(metrics)}")
    if metrics:
        total_views = sum(m["views"] for m in metrics)
        total_likes = sum(m["likes"] for m in metrics)
        total_replies = sum(m["replies"] for m in metrics)
        lines.append(f"- **Aggregate:** {total_views} views · {total_likes} likes · {total_replies} replies")
        lines.append("\n### Top engagement")
        for m in metrics_sorted[:5]:
            lines.append(f"- `{m['id']}` · {m['views']}v · {m['likes']}❤ · {m['replies']}💬 · {m['rt']}🔁")
            lines.append(f"  - {m['text']}")
            if m.get("url"):
                lines.append(f"  - {m['url']}")
    lines.append("")

    # Append (don't overwrite)
    with open(DAILY_LOG, "a") as f:
        f.write("\n".join(lines))


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7, help="how many days of posted tweets to track")
    args = p.parse_args()

    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = await _collect(args.days)
    if not snapshot:
        _log("no snapshot — cookies missing or no posts")
        return
    out = ANALYTICS_DIR / f"{snapshot['date']}.json"
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    _write_markdown(snapshot)
    _log(f"wrote {out} + appended {DAILY_LOG.name}")
    print(json.dumps({
        "date": snapshot["date"],
        "followers": snapshot.get("followers"),
        "tweets_tracked": len(snapshot.get("tweet_metrics", [])),
    }))


if __name__ == "__main__":
    asyncio.run(main())
