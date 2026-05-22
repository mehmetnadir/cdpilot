#!/usr/bin/env python3
"""mention_scraper.py — gelen mention/reply'leri çek + draft seed üret.

Twitter search üzerinden @cdpilot_dev geçen son tweet'leri tarar, daha önce
görülenleri elimine eder, yenilerini ~/cdpilot-twitter-data/inbox/<id>.json
olarak yazar. Cowork sabah/öğlen invocation'larında bu inbox'tan draft üretir.

Kullanım:
  python mention_scraper.py [--since N]   # N saat önceden bu yana
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from twikit import Client  # type: ignore

DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
INBOX_DIR = DATA / "inbox"
SEEN_FILE = DATA / "state" / "mentions-seen.json"
COOKIES_PATH = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES",
    str(DATA / "cookies" / "cdpilot_dev.json"),
))
LANG = os.environ.get("CDPILOT_TWIKIT_LANG", "en-US")
HANDLE = os.environ.get("CDPILOT_HANDLE", "cdpilot_dev")
LOG_FILE = DATA / "logs" / "mention-scraper.log"


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except (OSError, ValueError):
            return set()
    return set()


def _save_seen(seen: set) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Keep size bounded — last 5000
    arr = sorted(seen)[-5000:]
    SEEN_FILE.write_text(json.dumps(arr, indent=0))


async def _scrape(since_hours: int) -> int:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    if not COOKIES_PATH.exists():
        _log(f"cookies missing: {COOKIES_PATH}")
        return 0

    client = Client(LANG)
    client.load_cookies(str(COOKIES_PATH))

    seen = _load_seen()
    cutoff = time.time() - since_hours * 3600
    new_count = 0

    # Query: anyone mentioning us, excluding our own posts/quotes
    query = f"@{HANDLE} -from:{HANDLE}"
    try:
        tweets = await client.search_tweet(query, "Latest", count=40)
    except Exception as e:
        _log(f"search failed: {type(e).__name__}: {e}")
        return 0

    for tw in tweets:
        tid = str(tw.id)
        if tid in seen:
            continue
        # Filter by age
        try:
            created_ts = tw.created_at_datetime.timestamp()
        except Exception:
            created_ts = time.time()
        if created_ts < cutoff:
            continue

        author = tw.user.screen_name if tw.user else "unknown"
        text = tw.text or ""
        item = {
            "id": f"mention-{tid}",
            "tweet_id": tid,
            "author": f"@{author}",
            "text": text,
            "tweet_url": f"https://x.com/{author}/status/{tid}",
            "created_at": int(created_ts),
            "scraped_at": int(time.time()),
            "in_reply_to_status_id": getattr(tw, "in_reply_to", None),
            "is_reply_to_us": _is_reply_to_us(tw, HANDLE),
            "is_quote": getattr(tw, "is_quote_status", False),
            "status": "new",
        }
        (INBOX_DIR / f"{tid}.json").write_text(json.dumps(item, ensure_ascii=False, indent=2))
        seen.add(tid)
        new_count += 1
        _log(f"new mention {tid} from @{author}: {text[:80]}")

    _save_seen(seen)
    _log(f"scan complete — {new_count} new mentions")
    return new_count


def _is_reply_to_us(tw, our_handle: str) -> bool:
    """Best-effort check: is this tweet a reply specifically to one of our tweets?"""
    in_reply_user = getattr(tw, "in_reply_to_user", None) or getattr(tw, "in_reply_to_screen_name", None)
    if isinstance(in_reply_user, str):
        return in_reply_user.lower() == our_handle.lower()
    if hasattr(in_reply_user, "screen_name"):
        return in_reply_user.screen_name.lower() == our_handle.lower()
    return False


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--since", type=int, default=24, help="hours back to scan")
    args = p.parse_args()
    n = asyncio.run(_scrape(args.since))
    print(json.dumps({"new_mentions": n}))


if __name__ == "__main__":
    main()
