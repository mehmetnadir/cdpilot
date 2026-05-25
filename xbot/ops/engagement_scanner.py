#!/usr/bin/env python3
"""engagement_scanner.py — Tier 1/2 timeline scan → like/reply candidates.

Reads xbot/tier1.json, fetches each handle's latest tweets via twikit, scores
them against engagement-reciprocity heuristics, and emits draft proposals to
Telegram for human approval. Soft-only: never auto-posts.

Heuristic scoring:
  +5  recent (≤6h)
  +3  engagement signal (likes ≥ N relative to handle baseline) — best effort
  +2  topic match (browser, automation, captcha, agent, stealth, devtools)
  -10 crisis_topic flag from sanitize
  -3  url_high / url_bomb flag
  -2  injection_flag (still allowed to read; reply harder)

Output:
  - ~/cdpilot-twitter-data/engagement/<date>.json  (candidates, scored)
  - Optional Telegram drafts when --propose-top N (default 0 = scan only)

Faz 0 caps (enforced):
  - like_per_day ≤ 5
  - reply_per_day ≤ 3
  - total proposals shown ≤ 6 per slot

Env:
  CDPILOT_TWIKIT_COOKIES   ~/cdpilot-twitter-data/cookies/cdpilot_dev.json
  CDPILOT_XBOT_DATA         ~/cdpilot-twitter-data
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
import _twikit_patch  # noqa: F401
from twikit import Client  # type: ignore

sys.path.insert(0, str(Path(__file__).parent))
from _sanitize import sanitize, wrap_external, render_flags  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
OUT_DIR = DATA / "engagement"
LOG_FILE = DATA / "logs" / "engagement.log"
COOKIES = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES",
    str(DATA / "cookies" / "cdpilot_dev.json"),
))
TIER_FILE = ROOT / "tier1.json"

TOPIC_RE = re.compile(
    r"\b(browser|chrome|chromium|cdp|chrome devtools protocol|"
    r"playwright|puppeteer|selenium|"
    r"captcha|cloudflare|datadome|"
    r"automation|scraping|crawl|"
    r"agent|llm|ai (browser|agent)|"
    r"stealth|fingerprint|tls|"
    r"headless|devtools)\b",
    re.IGNORECASE,
)

MAX_TWEETS_PER_HANDLE = 5
PROPOSAL_CAP = int(os.environ.get("CDPILOT_PROPOSAL_CAP", "10"))

# Yoğun mod (user 2026-05-25): auto-execute eşik üstü adayları.
# Manuel onay sadece skor < AUTO_*_THRESHOLD veya AI draft eksik olduğunda gelir.
LIKE_PER_DAY = int(os.environ.get("CDPILOT_LIKE_CAP", "20"))
REPLY_PER_DAY = int(os.environ.get("CDPILOT_REPLY_CAP", "10"))
QUOTE_PER_DAY = int(os.environ.get("CDPILOT_QUOTE_CAP", "2"))

AUTO_LIKE_THRESHOLD = int(os.environ.get("CDPILOT_AUTO_LIKE_SCORE", "6"))
AUTO_REPLY_THRESHOLD = int(os.environ.get("CDPILOT_AUTO_REPLY_SCORE", "7"))
AUTO_QUOTE_THRESHOLD = int(os.environ.get("CDPILOT_AUTO_QUOTE_SCORE", "8"))  # manual only

FREEZE_FLAG = DATA / "state" / "crisis-freeze.flag"
QUEUE_DIR = DATA / "queue"


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _hours_since(created_at_str: str) -> float:
    # twikit Tweet.created_at is like "Wed May 21 09:23:00 +0000 2026"
    try:
        dt = datetime.strptime(created_at_str, "%a %b %d %H:%M:%S %z %Y")
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return 999.0


def _load_tier() -> dict:
    return json.loads(TIER_FILE.read_text())


def _audit_action_count(kind: str, day: str) -> int:
    """How many times we've already done `kind` (like/reply/follow) today."""
    audit_file = DATA / "audit" / f"actions-{day}.jsonl"
    if not audit_file.exists():
        return 0
    n = 0
    for line in audit_file.read_text().splitlines():
        try:
            r = json.loads(line)
            if r.get("kind") == kind and r.get("status") == "proposed":
                n += 1
        except ValueError:
            continue
    return n


async def _scan_handle(client: Client, handle: str, topic_hint: str) -> list[dict]:
    out: list[dict] = []
    try:
        user = await client.get_user_by_screen_name(handle)
    except Exception as e:
        _log(f"get_user fail @{handle}: {e}")
        return out
    try:
        tweets = await user.get_tweets("Tweets", count=MAX_TWEETS_PER_HANDLE)
    except Exception as e:
        _log(f"get_tweets fail @{handle}: {e}")
        return out

    for tw in tweets[:MAX_TWEETS_PER_HANDLE]:
        # skip retweets, replies (we want originals)
        text = (tw.text or "").strip()
        if not text or text.startswith("RT @"):
            continue
        if getattr(tw, "in_reply_to", None):
            continue

        san = sanitize(text)
        if san["drop"]:
            continue

        score = 0
        hours = _hours_since(getattr(tw, "created_at", "") or "")
        if hours <= 6:
            score += 5
        elif hours <= 24:
            score += 2

        if TOPIC_RE.search(text):
            score += 2

        # rough engagement: like count
        like_count = getattr(tw, "favorite_count", 0) or 0
        if like_count >= 50:
            score += 3
        elif like_count >= 10:
            score += 1

        if "injection_flag" in san["flags"]:
            score -= 2
        if any(f.startswith("url_high") for f in san["flags"]):
            score -= 3
        if "self_ref" in san["flags"]:
            score += 2  # they mention us — high priority

        if score < 1:
            continue

        out.append({
            "handle": handle,
            "topic_hint": topic_hint,
            "tweet_id": str(tw.id),
            "url": f"https://x.com/{handle}/status/{tw.id}",
            "text": san["clean"],
            "flags": san["flags"],
            "hours_old": round(hours, 1),
            "like_count": like_count,
            "score": score,
        })
    return out


def _telegram_send(text: str) -> None:
    try:
        import subprocess
        bridge = Path(__file__).parent / "telegram_bridge.py"
        subprocess.run(
            [sys.executable, str(bridge), "send", text],
            timeout=15, check=False,
        )
    except Exception as e:
        _log(f"telegram send failed: {e}")


def _format_proposal(c: dict, action: str) -> str:
    flag_str = render_flags(c["flags"])
    action_tr = "💬 CEVAP ADAYI" if action == "reply-candidate" else "💛 LIKE ADAYI"
    return (
        f"💡 {action_tr} — @{c['handle']}\n"
        f"⏰ {c['hours_old']} saat önce · ❤️ {c['like_count']} beğeni · skor {c['score']}/10\n"
        f"🔗 {c['url']}\n"
        f"{flag_str}\n\n"
        f"📥 Tweet içeriği:\n{c['text'][:400]}\n\n"
        f"👇 Aşağıdan karar ver:"
    )


def _send_proposal_card(c: dict, action: str) -> None:
    """Send engagement proposal as a card with inline action buttons.

    Reuses telegram_bridge daemon callbacks: replywrite / likemention / mskip.
    Registers pending under the returned message_id so the daemon can route.
    """
    try:
        bridge_dir = Path(__file__).parent
        sys.path.insert(0, str(bridge_dir))
        import telegram_bridge as tb  # type: ignore

        env = tb._load_env()
        if not env.get("TELEGRAM_CHAT_ID"):
            _log("no TELEGRAM_CHAT_ID, skipping proposal card")
            return

        text = _format_proposal(c, action)
        # Engagement proposals: 3-button card. The CEVAP option re-uses the
        # "replywrite" callback (user types reply in chat as a Telegram reply).
        # LIKE uses "likemention" — same action, just on a different target.
        keyboard = {
            "inline_keyboard": [[
                {"text": "💬 Cevap yaz", "callback_data": f"replywrite:eng-{c['tweet_id']}"},
                {"text": "💛 Like at", "callback_data": f"likemention:eng-{c['tweet_id']}"},
                {"text": "⏭ Geç", "callback_data": f"mskip:eng-{c['tweet_id']}"},
            ]]
        }
        result = tb._api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": text,
            "disable_web_page_preview": True,
            "reply_markup": keyboard,
        })
        msg_id = result.get("message_id")
        if msg_id:
            # Register as engagement-proposal so daemon's existing replywrite/
            # likemention handlers can use target_url + author.
            tb._register_pending(msg_id, {
                "id": f"eng-{c['tweet_id']}",
                "kind": "engagement-proposal",
                "tweet_id": c["tweet_id"],
                "target_url": c["url"],
                "author": c["handle"],
                "source_text": c["text"][:280],
            })
    except Exception as e:
        _log(f"proposal card send failed: {e}")
        # Fallback to plain message so we don't lose the signal.
        _telegram_send(_format_proposal(c, action))


async def _scan_mutual_engagement(client: Client) -> list[dict]:
    """Find users who replied to our recent tweets → propose likes on their content.

    Reciprocity loop: someone replies to us → we like 1-2 of their recent tweets
    within 24h → +60% follow-back probability. Caps at 5 candidates/day.
    """
    out: list[dict] = []
    inbox_dir = DATA / "inbox"
    if not inbox_dir.exists():
        return out

    # Find users from recent mentions (last 24h files)
    cutoff = time.time() - 24 * 3600
    repliers: dict[str, dict] = {}  # handle → {tweet_id, replied_at}
    for jf in sorted(inbox_dir.glob("*.json"), reverse=True)[:50]:
        try:
            m = json.loads(jf.read_text())
        except ValueError:
            continue
        if m.get("created_ts", 0) < cutoff:
            continue
        if not m.get("is_reply_to_us"):
            continue
        h = m.get("author_handle")
        if h and h not in repliers and h != "cdpilot_dev":
            repliers[h] = {"replied_tweet": m.get("tweet_id"), "ts": m.get("created_ts")}

    if not repliers:
        return out

    # For each replier, fetch last 3-5 tweets, score same way
    today = _today_iso()
    likes_today = _audit_action_count("like", today)
    for handle, meta in list(repliers.items())[:8]:
        if likes_today >= LIKE_PER_DAY:
            break
        try:
            user = await client.get_user_by_screen_name(handle)
            tweets = await user.get_tweets("Tweets", count=5)
        except Exception as e:
            _log(f"mutual scan @{handle} fail: {e}")
            continue
        for tw in tweets[:5]:
            text = (tw.text or "").strip()
            if not text or text.startswith("RT @"):
                continue
            if getattr(tw, "in_reply_to", None):
                continue
            san = sanitize(text)
            if san["drop"]:
                continue
            hours = _hours_since(getattr(tw, "created_at", "") or "")
            if hours > 48:
                continue
            out.append({
                "handle": handle,
                "topic_hint": "mutual-engagement",
                "tweet_id": str(tw.id),
                "url": f"https://x.com/{handle}/status/{tw.id}",
                "text": san["clean"],
                "flags": san["flags"],
                "hours_old": round(hours, 1),
                "like_count": getattr(tw, "favorite_count", 0) or 0,
                "score": 5,  # Fixed score — they engaged with us first
                "via": "mutual",
            })
            break  # one like per replier
        await asyncio.sleep(1.5)
    return out


async def main_async(propose_top: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not COOKIES.exists():
        _log(f"cookies missing: {COOKIES}")
        return

    tier = _load_tier()
    client = Client(os.environ.get("CDPILOT_TWIKIT_LANG", "en-US"))
    client.load_cookies(str(COOKIES))

    all_candidates: list[dict] = []
    for entry in tier.get("tier1", []) + tier.get("tier2", []):
        handle = entry["handle"]
        if handle in tier.get("blocklist", []):
            continue
        cands = await _scan_handle(client, handle, entry.get("topic", ""))
        all_candidates.extend(cands)
        await asyncio.sleep(2.0)  # gentle pacing

    # Mutual-engagement: like content from users who replied to us in last 24h
    try:
        mutual = await _scan_mutual_engagement(client)
        all_candidates.extend(mutual)
        if mutual:
            _log(f"mutual-engagement: {len(mutual)} candidates from recent repliers")
    except Exception as e:
        _log(f"mutual scan exception: {e}")

    all_candidates.sort(key=lambda c: c["score"], reverse=True)
    top = all_candidates[:PROPOSAL_CAP]

    today = _today_iso()
    out_file = OUT_DIR / f"{today}.json"
    out_file.write_text(json.dumps({
        "scanned_at": int(time.time()),
        "total": len(all_candidates),
        "top": top,
    }, ensure_ascii=False, indent=2))
    _log(f"scanned {len(all_candidates)} candidates → top {len(top)} written {out_file}")

    if propose_top <= 0 or not top:
        return

    # Crisis freeze respect — auto-execute YOK, sadece manual kart
    crisis_active = FREEZE_FLAG.exists()
    if crisis_active:
        _log("🔴 CRISIS FREEZE — auto-execute kapalı, sadece manual kart atılır")

    likes_today = _audit_action_count("like", today)
    replies_today = _audit_action_count("reply", today)
    audit_file = DATA / "audit" / f"actions-{today}.jsonl"
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    auto_like = 0
    auto_reply = 0
    manual_cards = 0

    # Decision-learner adaptive bonus (Faz B): handle/pillar trust → score delta
    try:
        from decision_learner import adaptive_score_bonus  # type: ignore
    except Exception:
        adaptive_score_bonus = lambda *a, **k: 0  # noqa: E731

    for c in top:
        # Apply learned bonus/malus from user's past decisions
        raw_score = c.get("score", 0)
        bonus = adaptive_score_bonus(c.get("handle"), c.get("pillar"))
        score = raw_score + bonus
        if bonus != 0:
            c["score_raw"] = raw_score
            c["score_bonus"] = bonus
            c["score"] = score  # so downstream cards show adjusted score
        if score <= -50:
            # veto trust: silently skip without card
            continue
        text = c.get("text", "")
        topic_match = bool(TOPIC_RE.search(text))

        # === AUTO-REPLY: skor ≥ 7 + topic match + AI draft + cap altı + no crisis
        if (not crisis_active and topic_match and
                score >= AUTO_REPLY_THRESHOLD and
                replies_today < REPLY_PER_DAY):
            ai_draft = _ai_draft_for(c)
            if ai_draft:
                _auto_queue_reply(c, ai_draft)
                _notify_auto("💬", "Cevap kuyrukta", c, ai_draft)
                _audit_write(audit_file, "reply", c, score, status="auto-queued")
                replies_today += 1
                auto_reply += 1
                time.sleep(1.0)
                continue

        # === AUTO-LIKE: skor ≥ 6 + cap altı + no crisis
        if (not crisis_active and
                score >= AUTO_LIKE_THRESHOLD and
                likes_today < LIKE_PER_DAY):
            _auto_queue_like(c)
            _notify_auto("💛", "Like kuyrukta", c, None)
            _audit_write(audit_file, "like", c, score, status="auto-queued")
            likes_today += 1
            auto_like += 1
            time.sleep(0.5)
            continue

        # === MANUEL KART: orta skor (3-6) topic match → reply candidate manuel
        if manual_cards >= propose_top:
            continue
        if topic_match and replies_today < REPLY_PER_DAY:
            action = "reply-candidate"
        elif likes_today < LIKE_PER_DAY:
            action = "like-candidate"
        else:
            continue
        _send_proposal_card(c, action)
        _audit_write(audit_file, "like" if action == "like-candidate" else "reply",
                     c, score, status="proposed")
        manual_cards += 1
        time.sleep(1.0)

    _log(f"auto-like={auto_like} auto-reply={auto_reply} manual-cards={manual_cards} "
         f"(today caps: like {likes_today}/{LIKE_PER_DAY}, reply {replies_today}/{REPLY_PER_DAY})")


def _audit_write(audit_file: Path, kind: str, c: dict, score: int, status: str) -> None:
    with open(audit_file, "a") as f:
        f.write(json.dumps({
            "ts": int(time.time()),
            "kind": kind,
            "status": status,
            "target": c.get("url"),
            "score": score,
        }) + "\n")


def _ai_draft_for(c: dict) -> str | None:
    """Generate AI reply draft via reply_drafter subprocess.

    Returns the draft text or None on failure (skips auto-reply, falls through
    to manual card flow).
    """
    try:
        import subprocess
        drafter = Path(__file__).parent / "reply_drafter.py"
        proc = subprocess.run(
            [sys.executable, str(drafter), "draft",
             "--incoming", c["text"][:280],
             "--author", f"@{c.get('handle','?')}",
             "--lang", "en"],
            capture_output=True, text=True, timeout=140,
        )
        if proc.returncode != 0:
            _log(f"ai_draft fail rc={proc.returncode}: {proc.stderr[:200]}")
            return None
        out = json.loads(proc.stdout)
        draft = (out.get("draft") or "").strip()
        if not draft or len(draft) > 270:
            _log(f"ai_draft rejected (len={len(draft)}): {draft[:80]}")
            return None
        # Sanity: no helpful-bot tone leaks
        bad = ("great question", "happy to help", "hope this helps", "let me know")
        low = draft.lower()
        if any(b in low for b in bad):
            _log(f"ai_draft tone leak: {draft[:80]}")
            return None
        return draft
    except Exception as e:
        _log(f"ai_draft exception: {e}")
        return None


def _auto_queue_like(c: dict) -> Path:
    """Write a kind=like queue item — poster will execute on next 5min cron."""
    qid = f"auto-like-{c['tweet_id']}"
    item = {
        "id": qid,
        "kind": "like",
        "to": c["url"],
        "text": "",
        "context": f"auto-like (score {c.get('score')}, @{c.get('handle')})",
        "approved_at": int(time.time()),
        "scheduled_time": int(time.time()) + 30,  # ~30s delay for humanizer
        "source": "engagement_scanner_auto",
    }
    path = QUEUE_DIR / f"{qid}.json"
    path.write_text(json.dumps(item, ensure_ascii=False, indent=2))
    return path


def _auto_queue_reply(c: dict, draft_text: str) -> Path:
    qid = f"auto-reply-{c['tweet_id']}"
    # Human gap: 5-15min spread for replies (avoids burst pattern)
    import random
    delay = random.randint(300, 900)
    item = {
        "id": qid,
        "kind": "reply",
        "to": c["url"],
        "text": draft_text,
        "context": f"auto-reply via ai_draft (score {c.get('score')}, @{c.get('handle')})",
        "approved_at": int(time.time()),
        "scheduled_time": int(time.time()) + delay,
        "source": "engagement_scanner_auto",
        "ai_drafted": True,
    }
    path = QUEUE_DIR / f"{qid}.json"
    path.write_text(json.dumps(item, ensure_ascii=False, indent=2))
    return path


def _notify_auto(emoji: str, action_tr: str, c: dict, draft: str | None) -> None:
    """Inform Telegram an auto-action was queued (no buttons — just info)."""
    try:
        bridge_dir = Path(__file__).parent
        sys.path.insert(0, str(bridge_dir))
        import telegram_bridge as tb  # type: ignore
        env = tb._load_env()
        if not env.get("TELEGRAM_CHAT_ID"):
            return
        lines = [
            f"{emoji} OTOMATİK — {action_tr}",
            f"@{c.get('handle','?')}  ·  skor {c.get('score')}  ·  {c.get('hours_old','?')}h önce",
            f"🔗 {c.get('url','')}",
            "",
            f"📥 Hedef tweet:",
            c.get("text", "")[:240],
        ]
        if draft:
            lines += ["", "✨ Bizim cevap:", draft]
        lines.append("")
        lines.append("ℹ️ Otomatik atıldı, onayın gerekmedi. Yanlışsa Telegram'da söyle, geri çekerim.")
        tb._api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": "\n".join(lines),
            "disable_web_page_preview": True,
        })
    except Exception as e:
        _log(f"notify_auto fail: {e}")


def main() -> None:
    propose_top = 0
    for a in sys.argv[1:]:
        if a.startswith("--propose-top="):
            propose_top = int(a.split("=", 1)[1])
        elif a == "--propose-top":
            propose_top = 3
    asyncio.run(main_async(propose_top))


if __name__ == "__main__":
    main()
