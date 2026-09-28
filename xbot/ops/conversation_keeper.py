#!/usr/bin/env python3
"""conversation_keeper.py — answer the people who answered us.

The account's doctrine says it sustains discussions, but the only path for a
reply-to-us was a Telegram decision card: if nobody tapped it, the conversation
died. Firing one reply into someone's thread and never returning is publishing,
not discussing.

Sustaining is not ping-pong, so this is deliberately bounded:
  - at most MAX_DEPTH of our replies per person per window; after that a human
    continues or it ends
  - fresh only: answering a two-day-old reply reads as a bot catching up
  - the drafting model may return SKIP, and often should
  - off-limits topics are refused even when someone drags us into them
  - "Claude ile üretim hikâyeleri" threads are Nadir's to answer (content-pillars)

Usage:
  python conversation_keeper.py            # dry run: show what it would answer
  python conversation_keeper.py --apply    # queue the replies
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import bot_home  # noqa: E402
from _relevance import off_limits  # noqa: E402
import _notify  # noqa: E402

DATA = bot_home()
INBOX_DIR = DATA / "inbox"
QUEUE_DIR = DATA / "queue"
POSTED_DIR = DATA / "posted"
LOG_FILE = DATA / "logs" / "conversation.log"

MAX_DEPTH = int(os.environ.get("CDPILOT_CONV_MAX_DEPTH", "2"))
FRESH_HOURS = int(os.environ.get("CDPILOT_CONV_FRESH_H", "20"))
DEPTH_WINDOW_H = 48
DAILY_CAP = int(os.environ.get("CDPILOT_CONV_DAILY_CAP", "4"))
# Threads born from this pillar are answered by Nadir, not the bot.
NADIR_ONLY_PREFIXES = ("bts-", "claude-story-", "story-")


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    sys.stderr.write(msg + "\n")


def _our_replies_to(author: str, hours: int = DEPTH_WINDOW_H) -> int:
    """How many replies we already sent this person recently."""
    cutoff = time.time() - hours * 3600
    n = 0
    handle = author.lstrip("@").lower()
    for f in POSTED_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if d.get("kind") != "reply" or (d.get("posted_at") or 0) < cutoff:
            continue
        if handle in (d.get("to") or "").lower():
            n += 1
    return n


def _replies_queued_today() -> int:
    start = time.time() - (time.time() % 86400)
    n = 0
    for d in (QUEUE_DIR, POSTED_DIR):
        for f in d.glob("*.json"):
            try:
                item = json.loads(f.read_text())
            except Exception:
                continue
            if item.get("source") == "conversation_keeper" and \
                    (item.get("approved_at") or 0) >= start:
                n += 1
    return n


def _is_nadirs_thread(item: dict) -> bool:
    parent = str(item.get("in_reply_to_status_id") or "")
    if not parent:
        return False
    for f in POSTED_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        ids = [str(d.get("tweet_id"))] + [str(i) for i in (d.get("tweet_ids") or [])]
        if parent in ids:
            return str(d.get("id", "")).startswith(NADIR_ONLY_PREFIXES)
    return False


def candidates() -> list[dict]:
    if not INBOX_DIR.exists():
        return []
    fresh_cutoff = time.time() - FRESH_HOURS * 3600
    out = []
    for f in sorted(INBOX_DIR.glob("*.json")):
        try:
            item = json.loads(f.read_text())
        except Exception:
            continue
        if item.get("status") != "new" or not item.get("is_reply_to_us"):
            continue
        if (item.get("created_at") or 0) < fresh_cutoff:
            item["_skip"] = "stale"
        elif off_limits(item.get("text", "")):
            item["_skip"] = f"off-limits:{off_limits(item.get('text', ''))}"
        elif _our_replies_to(item.get("author", "")) >= MAX_DEPTH:
            item["_skip"] = f"depth: already replied {MAX_DEPTH}x to {item.get('author')}"
        elif _is_nadirs_thread(item):
            item["_skip"] = "Nadir's thread (production-story pillar)"
        item["_file"] = str(f)
        out.append(item)
    return out


def _mark(item: dict, status: str, note: str = "") -> None:
    f = Path(item["_file"])
    try:
        d = json.loads(f.read_text())
    except Exception:
        return
    d["status"] = status
    if note:
        d["keeper_note"] = note
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--timeout", type=int, default=120)
    args = p.parse_args()

    queued = 0
    room = DAILY_CAP - _replies_queued_today()
    results = []
    for item in candidates():
        if item.get("_skip"):
            results.append({"author": item.get("author"), "action": "skip",
                            "why": item["_skip"]})
            if args.apply:
                _mark(item, "skipped", item["_skip"])
            continue
        if room <= 0:
            results.append({"author": item.get("author"), "action": "defer",
                            "why": f"daily cap {DAILY_CAP} reached"})
            continue
        if not args.apply:
            results.append({"author": item.get("author"), "action": "would answer",
                            "text": (item.get("text") or "")[:90]})
            room -= 1
            continue

        from reply_drafter import draft  # imported late: pulls in twikit
        res = draft(item.get("text", ""), author=item.get("author"),
                    lang=None, timeout=args.timeout)
        if res.get("skip"):
            _mark(item, "skipped", "model chose SKIP")
            results.append({"author": item.get("author"), "action": "skip",
                            "why": "model chose SKIP"})
            continue
        if res.get("fallback") or not res.get("draft"):
            results.append({"author": item.get("author"), "action": "defer",
                            "why": "no engine produced a reply"})
            continue

        now = int(time.time())
        qid = f"conv-{item['tweet_id']}"
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        (QUEUE_DIR / f"{qid}.json").write_text(json.dumps({
            "id": qid,
            "kind": "reply",
            "to": item.get("tweet_url"),
            "text": res["draft"],
            "context": f"sustaining a conversation with {item.get('author')}",
            "source": "conversation_keeper",
            "status": "pending",
            "approved_at": now,
            "scheduled_time": now + 90,
        }, ensure_ascii=False, indent=2))
        _mark(item, "answered", qid)
        _log(f"queued {qid} → {item.get('author')}: {res['draft'][:80]}")
        results.append({"author": item.get("author"), "action": "queued",
                        "text": res["draft"]})
        queued += 1
        room -= 1

    deferred = [r for r in results if r["action"] == "defer"
                and str(r.get("why", "")).startswith("daily cap")]
    if args.apply and deferred:
        # Cap reached → no action, one info push (the mention push already
        # carried each tweet's link).
        _notify.notify(f"Sohbet: {len(deferred)} yanıt ertelendi",
                       f"Günlük sınır {DAILY_CAP} doldu: "
                       + ", ".join(str(r.get("author")) for r in deferred[:8]),
                       url=f"https://x.com/{_notify.HANDLE}/with_replies",
                       priority="dusuk", tags=["pause_button"])

    print(json.dumps({"queued": queued, "results": results},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
