#!/usr/bin/env python3
"""crisis_check.py — engagement drop / shadowban auto-detector.

Triggers (any):
  - Today's average impressions < 40% of 7-day baseline (≥3 days history needed)
  - Total daily engagement (likes+replies+rt+bookmark) drops > 60% vs baseline
  - Followers count drops vs yesterday

Action (if triggered):
  - Set FREEZE flag in DATA/state/crisis-freeze.flag
  - Poster checks this flag and refuses to post when set
  - Telegram alert to Nadir with details + recovery suggestions

Detection only (Phase 1) — recovery handled by crisis-playbook skill manually.

Env: CDPILOT_XBOT_DATA  default ~/cdpilot-twitter-data

CLI: python crisis_check.py [--clear]   # --clear lifts freeze
"""
from __future__ import annotations
import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import bot_home  # noqa: E402

DATA = bot_home()
ANALYTICS = DATA / "analytics"
FREEZE_FLAG = DATA / "state" / "crisis-freeze.flag"
LOG_FILE = DATA / "logs" / "crisis.log"
TELEGRAM_BRIDGE = Path(__file__).parent / "telegram_bridge.py"

DROP_THRESHOLD = 0.60  # 60% drop vs baseline triggers
IMPR_FLOOR = 0.40


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _telegram_send(text: str) -> None:
    try:
        import subprocess
        subprocess.run([sys.executable, str(TELEGRAM_BRIDGE), "send", text],
                       timeout=15, check=False)
    except Exception as e:
        _log(f"telegram send failed: {e}")


def _load_analytics_history() -> list[dict]:
    """Last 14 days of analytics JSONs (oldest → newest)."""
    out: list[dict] = []
    if not ANALYTICS.exists():
        return out
    today = datetime.now(timezone.utc).date()
    for n in range(13, -1, -1):
        d = today - timedelta(days=n)
        f = ANALYTICS / f"{d.isoformat()}.json"
        if f.exists():
            try:
                out.append(json.loads(f.read_text()))
            except ValueError:
                continue
    return out


def _aggregate(record: dict) -> dict:
    """Sum tweet metrics for a day record."""
    tweets = record.get("tweets") or []
    likes = sum(t.get("likes", 0) for t in tweets)
    replies = sum(t.get("replies", 0) for t in tweets)
    rt = sum(t.get("rt", 0) for t in tweets)
    quotes = sum(t.get("quotes", 0) for t in tweets)
    bookmarks = sum(t.get("bookmarks", 0) for t in tweets)
    views = sum(t.get("views", 0) for t in tweets)
    return {
        "date": record.get("date"),
        "tweets_tracked": record.get("tweets_tracked", len(tweets)),
        "followers": record.get("followers", 0),
        "likes": likes, "replies": replies, "rt": rt,
        "quotes": quotes, "bookmarks": bookmarks, "views": views,
        "total_engagement": likes + replies + rt + quotes + bookmarks,
    }


def check() -> dict:
    history = _load_analytics_history()
    if len(history) < 4:
        _log(f"insufficient history ({len(history)} days), skip check")
        return {"triggered": False, "reason": "insufficient_history"}

    daily = [_aggregate(r) for r in history]
    today = daily[-1]
    baseline = daily[-8:-1] if len(daily) >= 8 else daily[:-1]  # last 7 prior days

    triggered = False
    reasons: list[str] = []

    # Engagement drop
    base_eng = [d["total_engagement"] for d in baseline if d["total_engagement"] > 0]
    if base_eng:
        median_eng = statistics.median(base_eng)
        if median_eng > 0 and today["total_engagement"] < median_eng * (1 - DROP_THRESHOLD):
            triggered = True
            reasons.append(
                f"engagement drop: today={today['total_engagement']} "
                f"vs median={median_eng:.0f} (>{int(DROP_THRESHOLD*100)}% down)"
            )

    # Impression drop
    base_views = [d["views"] for d in baseline if d["views"] > 0]
    if base_views:
        median_views = statistics.median(base_views)
        if median_views > 0 and today["views"] < median_views * IMPR_FLOOR:
            triggered = True
            reasons.append(
                f"impressions floor: today={today['views']} "
                f"vs median={median_views:.0f} (<{int(IMPR_FLOOR*100)}%)"
            )

    # Follower drop
    if len(daily) >= 2:
        yesterday = daily[-2]
        if today["followers"] < yesterday["followers"]:
            triggered = True
            reasons.append(
                f"follower drop: {yesterday['followers']} → {today['followers']}"
            )

    result = {
        "triggered": triggered,
        "reasons": reasons,
        "today": today,
        "baseline_median_engagement": (
            statistics.median(base_eng) if base_eng else 0
        ),
    }

    if triggered:
        FREEZE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        FREEZE_FLAG.write_text(json.dumps({
            "triggered_at": int(time.time()),
            "reasons": reasons,
        }, indent=2))
        _log(f"🔴 CRISIS TRIGGERED: {reasons}")
        _telegram_send(
            "🔴 CRISIS DETECT — posting frozen.\n\n"
            + "\n".join(f"• {r}" for r in reasons)
            + "\n\nNext: crisis-playbook skill ile manuel inceleme. "
            "Düzeldikten sonra: python crisis_check.py --clear"
        )
    else:
        _log(f"OK · today_eng={today['total_engagement']} · followers={today['followers']}")

    return result


def clear() -> None:
    if FREEZE_FLAG.exists():
        FREEZE_FLAG.unlink()
        _log("freeze flag cleared")
        _telegram_send("🟢 Crisis freeze kaldırıldı — posting yeniden aktif.")
    else:
        _log("no freeze to clear")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--clear", action="store_true", help="lift freeze flag")
    args = p.parse_args()
    if args.clear:
        clear()
    else:
        result = check()
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
