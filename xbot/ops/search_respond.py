#!/usr/bin/env python3
"""search_respond.py — Faz A #4.

Günlük 13:00 cycle slot'unda çalışır. cdpilot niş'inde "soru" pattern'ı
içeren tweet'leri X üzerinde arar:
  - "playwright stealth not working"
  - "captcha bypass help"
  - "cdp protocol question"
  - "browser automation how to"
  - + 6 niş pattern

Bulunan adaylardan yüksek-takipçi (5k+) + son 24h + soru içeren maks 3 tanesini
seçer, her birine reply_drafter ile cool ton'da cevap taslağı üretir, Telegram'a
butonlu kart atar (💬 Cevap at / 💛 Like / ⏭ Geç).

X search'i twikit'te şu an drift'li (ClientTransaction key issue) — graceful
zero-result, twikit düzelir düzelmez otomatik akmaya başlar.

DOCTRINE.md §3 Faz A item 4.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
import _twikit_patch  # noqa: F401
from twikit import Client  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import bot_home  # noqa: E402

DATA = bot_home()
XBOT = Path(__file__).resolve().parent.parent
STATE = DATA / "state"
SEARCH_DIR = STATE / "search"
LOG_FILE = DATA / "logs" / "search-respond.log"
COOKIES_PATH = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES",
    str(DATA / "cookies" / "cdpilot_dev.json"),
))
LANG = os.environ.get("CDPILOT_TWIKIT_LANG", "en-US")
HANDLE = os.environ.get("CDPILOT_HANDLE", "cdpilot_dev")

# Niş soru patterns — "X is" değil "X how/why/help/?" tarzı
SEARCH_QUERIES = [
    "playwright stealth not working",
    "puppeteer captcha bypass",
    "selenium detected",
    "cdp protocol question",
    "browser automation help",
    "headless chrome detection",
    "anti-bot bypass how",
    "scraping cloudflare 403",
    "datadome bypass",
    "browser fingerprint randomize",
]

MIN_FOLLOWERS = int(os.environ.get("CDPILOT_SEARCH_MIN_FOLLOWERS", "1000"))
MAX_AGE_HOURS = int(os.environ.get("CDPILOT_SEARCH_MAX_AGE_H", "36"))
MAX_PROPOSALS = int(os.environ.get("CDPILOT_SEARCH_MAX_PROPOSALS", "3"))

QUESTION_RE = re.compile(r"(\?|\bhow\b|\bwhy\b|\bhelp\b|\banyone know\b|\bany idea\b)", re.IGNORECASE)


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _hours_old(ts: float) -> float:
    return (time.time() - ts) / 3600.0


def _is_question(text: str) -> bool:
    return bool(QUESTION_RE.search(text or ""))


async def _search_one(client: Client, query: str, limit: int = 5) -> list[dict]:
    """Run one X search query. Returns list of normalized candidates or []."""
    out: list[dict] = []
    for mode in ("Latest", "Top"):
        try:
            tweets = await client.search_tweet(query, mode, count=limit)
        except Exception as e:
            _log(f"x search '{query}' [{mode}] fail: {e}")
            continue
        if not tweets:
            continue
        for tw in tweets:
            try:
                text = (tw.text or "").strip()
                if not text or not _is_question(text):
                    continue
                created = tw.created_at_datetime.timestamp() if tw.created_at_datetime else 0
                age_h = _hours_old(created) if created else 999
                if age_h > MAX_AGE_HOURS:
                    continue
                user = tw.user
                followers = getattr(user, "followers_count", 0) or 0
                if followers < MIN_FOLLOWERS:
                    continue
                handle = getattr(user, "screen_name", "?")
                if handle == HANDLE:
                    continue
                out.append({
                    "tweet_id": tw.id,
                    "url": f"https://x.com/{handle}/status/{tw.id}",
                    "author": handle,
                    "author_followers": followers,
                    "text": text[:280],
                    "created_ts": created,
                    "hours_old": round(age_h, 1),
                    "query": query,
                    "mode": mode,
                    "likes": getattr(tw, "favorite_count", 0) or 0,
                    "replies": getattr(tw, "reply_count", 0) or 0,
                })
            except Exception as e:
                _log(f"normalize tweet fail: {e}")
                continue
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for it in items:
        tid = it.get("tweet_id")
        if tid and tid not in seen:
            seen.add(tid)
            out.append(it)
    return out


def _score(it: dict) -> float:
    """Higher = better candidate. Recency + follower count + low reply count."""
    fresh_boost = max(0.0, (MAX_AGE_HOURS - it.get("hours_old", 999)) / MAX_AGE_HOURS)
    follower_log = min(1.0, (it.get("author_followers", 0) / 50000.0))
    low_reply_boost = 1.0 / (1 + it.get("replies", 0) / 5.0)
    return round(fresh_boost * 0.3 + follower_log * 0.5 + low_reply_boost * 0.2, 3)


def _ai_draft(incoming: str, author: str) -> str | None:
    """Call reply_drafter for a cool peer-voice draft."""
    try:
        proc = subprocess.run(
            [sys.executable, str(XBOT / "ops" / "reply_drafter.py"), "draft",
             "--incoming", incoming, "--author", f"@{author}", "--lang", "en"],
            capture_output=True, text=True, timeout=140,
        )
        if proc.returncode != 0:
            _log(f"reply_drafter fail: {proc.stderr[:200]}")
            return None
        out = json.loads(proc.stdout)
        return out.get("draft")
    except Exception as e:
        _log(f"reply_drafter exception: {e}")
        return None


def _send_card(c: dict, ai_draft: str | None, idx: int, total: int) -> dict:
    sys.path.insert(0, str(Path(__file__).parent))
    import telegram_bridge as tb  # type: ignore

    env = tb._load_env()
    if not env.get("TELEGRAM_CHAT_ID"):
        return {"_error": "no_chat_id"}

    text_lines = [
        f"🔎 SORU ADAYI {idx}/{total} — @{c['author']} ({c['author_followers']:,} takipçi)",
        f"⏰ {c['hours_old']}h önce  ·  ❤️ {c['likes']}  ·  💬 {c['replies']}  ·  skor {_score(c)}",
        f"🔗 {c['url']}",
        f"🔍 Sorgu: \"{c['query']}\"",
        "",
        "📥 Soru:",
        c["text"],
        "",
    ]
    if ai_draft:
        text_lines += [
            "✨ AI Cevap Taslağı:",
            ai_draft,
            "",
        ]
    text_lines.append("👇 Karar ver:")

    cb_id = f"search-{c['tweet_id']}"
    buttons_row = []
    if ai_draft:
        buttons_row.append({"text": "✨ AI cevap at", "callback_data": f"aireply:{cb_id}"})
    buttons_row.append({"text": "💬 Manuel yaz", "callback_data": f"replywrite:{cb_id}"})
    keyboard = {
        "inline_keyboard": [
            buttons_row,
            [
                {"text": "💛 Like", "callback_data": f"likemention:{cb_id}"},
                {"text": "⏭ Geç", "callback_data": f"mskip:{cb_id}"},
            ],
        ]
    }

    result = tb._api(env, "sendMessage", {
        "chat_id": int(env["TELEGRAM_CHAT_ID"]),
        "text": "\n".join(text_lines),
        "disable_web_page_preview": True,
        "reply_markup": keyboard,
    })
    msg_id = result.get("message_id")
    if msg_id:
        tb._register_pending(msg_id, {
            "id": cb_id,
            "kind": "incoming-reply",  # reuse handler — same target_url/author/ai_draft shape
            "tweet_id": c["tweet_id"],
            "target_url": c["url"],
            "author": c["author"],
            "ai_draft": ai_draft or "",
            "source": "search_respond",
        })
    return result


async def main_async(send: bool = True) -> dict:
    if not COOKIES_PATH.exists():
        _log(f"cookies missing: {COOKIES_PATH}")
        return {"status": "no_cookies"}

    SEARCH_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H")
    out_path = SEARCH_DIR / f"{stamp}.json"

    client = Client(LANG)
    client.load_cookies(str(COOKIES_PATH))

    all_candidates: list[dict] = []
    for q in SEARCH_QUERIES:
        try:
            results = await _search_one(client, q, limit=5)
            all_candidates.extend(results)
            await asyncio.sleep(1.5)
        except Exception as e:
            _log(f"search '{q}' wrapped fail: {e}")

    deduped = _dedupe(all_candidates)
    deduped.sort(key=_score, reverse=True)
    top = deduped[:MAX_PROPOSALS]

    artifact = {
        "id": stamp,
        "generated_at": int(time.time()),
        "queries": SEARCH_QUERIES,
        "total_found": len(all_candidates),
        "deduped": len(deduped),
        "sent": 0,
        "proposals": top,
    }

    if not top:
        out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        _log(f"no proposals — total_found={len(all_candidates)} deduped={len(deduped)}")
        return {"status": "no_results", "path": str(out_path), "scanned": len(all_candidates)}

    # Generate AI drafts then send cards
    if send:
        for i, c in enumerate(top, 1):
            ai = _ai_draft(c["text"], c["author"])
            try:
                _send_card(c, ai, i, len(top))
                artifact["sent"] += 1
                time.sleep(1.5)
            except Exception as e:
                _log(f"send card {i} fail: {e}")

    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
    _log(f"sent {artifact['sent']}/{len(top)} cards · artifact={out_path}")
    return {"status": "ok", "path": str(out_path),
            "scanned": len(all_candidates), "sent": artifact["sent"]}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--no-send", action="store_true")
    args = p.parse_args()
    result = asyncio.run(main_async(send=not args.no_send))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
