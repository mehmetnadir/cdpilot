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
# A freeze blocks ALL posting, so the drop rules stay disarmed until the baseline
# carries real signal. On a young account an empty history reads as a collapse —
# and a freeze nobody notices is how posting died for 6 weeks in 2026-08.
MIN_BASELINE_DAYS = 3      # baseline days that actually tracked tweets
MIN_FOLLOWERS_FOR_DROP = 25  # below this, ordinary churn is noise, not a shadowban


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


def _to_int(v) -> int:
    """Snapshots may carry str metrics (X returns view_count as a string)."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0


def _aggregate(record: dict) -> dict:
    """Sum tweet metrics for a day record.

    daily_analytics writes the list under "tweet_metrics"; "tweets" is the legacy
    key kept for snapshots written before that rename.
    """
    tweets = record.get("tweet_metrics")
    if tweets is None:
        tweets = record.get("tweets") or []
    likes = sum(_to_int(t.get("likes")) for t in tweets)
    replies = sum(_to_int(t.get("replies")) for t in tweets)
    rt = sum(_to_int(t.get("rt")) for t in tweets)
    quotes = sum(_to_int(t.get("quotes")) for t in tweets)
    bookmarks = sum(_to_int(t.get("bookmarks")) for t in tweets)
    views = sum(_to_int(t.get("views")) for t in tweets)
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
    skipped: list[str] = []

    # Drop rules need a baseline that actually observed tweets; days where
    # analytics tracked nothing are absence of data, not absence of engagement.
    baseline_with_data = [d for d in baseline if d["tweets_tracked"] > 0]
    signal_ok = len(baseline_with_data) >= MIN_BASELINE_DAYS

    # Today must itself be measurable. daily_analytics only tracks posts inside
    # its 7-day window, so a quiet stretch empties that window and today reports
    # tweets_tracked=0 — no measurement, not a measurement of zero. Comparing
    # that against a baseline of busy days reads as a 100% collapse and freezes
    # posting, which then guarantees tomorrow's zero too.
    # 2026-09-08: exactly this fired. "engagement drop: today=0 vs median=4" and
    # "impressions floor: today=0 vs median=276" froze the account for 11 hours
    # while nothing was actually wrong. Same class as the C6 bug (absent data
    # read as a zero value), reintroduced here.
    today_measurable = today["tweets_tracked"] > 0
    if not today_measurable:
        signal_ok = False
        skipped.append(
            "drop rules disarmed: nothing tracked today — no posts inside the "
            "analytics window, so there is nothing to compare"
        )
    elif not signal_ok:
        skipped.append(
            f"drop rules disarmed: {len(baseline_with_data)}/{MIN_BASELINE_DAYS} "
            "baseline days with tracked tweets"
        )

    # Engagement drop
    base_eng = [d["total_engagement"] for d in baseline_with_data if d["total_engagement"] > 0]
    if signal_ok and base_eng:
        median_eng = statistics.median(base_eng)
        if median_eng > 0 and today["total_engagement"] < median_eng * (1 - DROP_THRESHOLD):
            triggered = True
            reasons.append(
                f"engagement drop: today={today['total_engagement']} "
                f"vs median={median_eng:.0f} (>{int(DROP_THRESHOLD*100)}% down)"
            )

    # Impression drop
    base_views = [d["views"] for d in baseline_with_data if d["views"] > 0]
    if signal_ok and base_views:
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
        f_now, f_prev = today["followers"], yesterday["followers"]
        # followers is None whenever the profile fetch failed — a failed read is
        # not a drop. And on a tiny account a single unfollow must not freeze posting.
        if isinstance(f_now, int) and isinstance(f_prev, int):
            if f_prev >= MIN_FOLLOWERS_FOR_DROP and f_now < f_prev - 1:
                triggered = True
                reasons.append(f"follower drop: {f_prev} → {f_now}")
            elif f_now < f_prev:
                skipped.append(
                    f"follower dip {f_prev} → {f_now} below noise floor "
                    f"(needs base ≥{MIN_FOLLOWERS_FOR_DROP} and >1 lost)"
                )

    result = {
        "triggered": triggered,
        "reasons": reasons,
        "skipped": skipped,
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
        _log(
            f"OK · today_eng={today['total_engagement']} · followers={today['followers']}"
            + (f" · skipped={skipped}" if skipped else "")
        )

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
