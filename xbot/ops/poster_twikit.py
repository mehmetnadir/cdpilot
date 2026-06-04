#!/usr/bin/env python3
"""poster_twikit.py — HTTP-only queue worker (Chrome-free).

Scans ~/cdpilot-twitter-data/queue/ for items where scheduled_time <= now,
posts via twikit (phin fork) with cookies-only auth — no browser, no CDP.
Notifies Telegram on success/failure.

Designed for launchd (Mac) or systemd (srv21). Same JSON queue schema as the
old CDP-based poster.py. Idempotent: only picks items with status=="pending".

Required env (optional, defaults shown):
  CDPILOT_TWIKIT_COOKIES   ~/cdpilot-twitter-data/cookies/cdpilot_dev.json
  CDPILOT_TWIKIT_LANG      en-US

Run: source twikit-venv/bin/activate && python poster_twikit.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path

# twikit installed in the venv this script is launched from
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
import _twikit_patch  # noqa: F401
from twikit import Client  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import bot_home  # noqa: E402

DATA = bot_home()
QUEUE_DIR = DATA / "queue"
POSTED_DIR = DATA / "posted"
FAILED_DIR = DATA / "failed"
LOG_FILE = DATA / "logs" / "poster.log"
FREEZE_FLAG = DATA / "state" / "crisis-freeze.flag"
COOKIES_PATH = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES",
    str(DATA / "cookies" / "cdpilot_dev.json"),
))
LANG = os.environ.get("CDPILOT_TWIKIT_LANG", "en-US")
TELEGRAM_BRIDGE = Path(__file__).parent / "telegram_bridge.py"


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _telegram_notify(text: str) -> None:
    try:
        import subprocess
        subprocess.run(
            [sys.executable, str(TELEGRAM_BRIDGE), "send", text],
            timeout=15, check=False,
        )
    except Exception as e:
        _log(f"telegram notify failed: {e}")


def _tr_summary(text: str) -> str:
    """Produce a 1-sentence Turkish summary of an (English) tweet.

    Uses the local ``claude`` CLI (subscription auth on srv21). On any failure
    — CLI missing, timeout, empty output — falls back to the first 100 chars of
    the raw tweet text. Never raises; always returns a non-empty string when the
    input is non-empty.
    """
    text = (text or "").strip()
    if not text:
        return ""
    fallback = text[:100] + ("…" if len(text) > 100 else "")
    import shutil
    import subprocess
    if not shutil.which("claude"):
        return fallback
    prompt = ("Bu tweet'i 1 cümle Türkçe özetle, sadece özeti yaz: " + text)
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except Exception as e:
        _log(f"tr_summary claude call failed: {e}")
        return fallback
    out = (proc.stdout or "").strip()
    return out if out else fallback


def _tweet_id_from_to(to: str | None) -> str | None:
    """Extract tweet id from a reply target URL like https://x.com/user/status/12345."""
    if not to:
        return None
    if to.isdigit():
        return to
    if "/status/" in to:
        tail = to.rstrip("/").split("/status/")[-1]
        tail = tail.split("?")[0].split("/")[0]
        return tail if tail.isdigit() else None
    return None


async def _upload_media(client: Client, image_path: str) -> str | None:
    """Upload local media file and return media_id. None on failure."""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        mid = await client.upload_media(image_path)
        return mid
    except Exception as e:
        _log(f"upload_media failed for {image_path}: {e}")
        return None


async def _post_tweet(client: Client, text: str, image_path: str | None = None) -> dict:
    media_ids = None
    if image_path:
        mid = await _upload_media(client, image_path)
        if mid:
            media_ids = [mid]
    tw = await client.create_tweet(text=text, media_ids=media_ids)
    return {"ok": True, "tweet_id": str(tw.id),
            "tweet_url": f"https://x.com/cdpilot_dev/status/{tw.id}",
            "had_media": bool(media_ids)}


async def _post_followup_reply(client: Client, parent_tweet_id: str,
                                followup_text: str) -> dict:
    """Reply to our own just-posted tweet (link-in-reply algorithm tactic).

    Body kept link-free for max algo reach; URL/details go in first reply
    which appears auto-expanded below the parent.
    """
    tw = await client.create_tweet(text=followup_text, reply_to=parent_tweet_id)
    return {"ok": True, "tweet_id": str(tw.id),
            "tweet_url": f"https://x.com/cdpilot_dev/status/{tw.id}"}


async def _post_reply(client: Client, text: str, to: str | None,
                       image_path: str | None = None) -> dict:
    target = _tweet_id_from_to(to)
    if not target:
        return {"ok": False, "err": f"reply needs tweet id or url, got: {to!r}"}
    media_ids = None
    if image_path:
        mid = await _upload_media(client, image_path)
        if mid:
            media_ids = [mid]
    tw = await client.create_tweet(text=text, reply_to=target, media_ids=media_ids)
    return {"ok": True, "tweet_id": str(tw.id),
            "tweet_url": f"https://x.com/cdpilot_dev/status/{tw.id}",
            "had_media": bool(media_ids)}


async def _post_quote(client: Client, text: str, to: str | None) -> dict:
    target = _tweet_id_from_to(to)
    if not target:
        return {"ok": False, "err": f"quote needs tweet id or url, got: {to!r}"}
    quote_url = to if to and to.startswith("http") else f"https://x.com/i/status/{target}"
    tw = await client.create_tweet(text=f"{text}\n{quote_url}".strip())
    return {"ok": True, "tweet_id": str(tw.id),
            "tweet_url": f"https://x.com/cdpilot_dev/status/{tw.id}"}


async def _like(client: Client, to: str | None) -> dict:
    target = _tweet_id_from_to(to)
    if not target:
        return {"ok": False, "err": f"like needs tweet id, got: {to!r}"}
    tw = await client.get_tweet_by_id(target)
    await tw.favorite()
    return {"ok": True, "action": "like", "target": target}


async def _retweet(client: Client, to: str | None) -> dict:
    target = _tweet_id_from_to(to)
    if not target:
        return {"ok": False, "err": f"retweet needs tweet id, got: {to!r}"}
    tw = await client.get_tweet_by_id(target)
    await tw.retweet()
    return {"ok": True, "action": "retweet", "target": target}


async def _bookmark(client: Client, to: str | None) -> dict:
    target = _tweet_id_from_to(to)
    if not target:
        return {"ok": False, "err": f"bookmark needs tweet id, got: {to!r}"}
    tw = await client.get_tweet_by_id(target)
    await tw.bookmark()
    return {"ok": True, "action": "bookmark", "target": target}


async def _follow(client: Client, to: str | None) -> dict:
    """to can be @screenname or numeric user id."""
    if not to:
        return {"ok": False, "err": "follow needs username or user id"}
    handle = to.lstrip("@")
    if handle.isdigit():
        uid = handle
    else:
        u = await client.get_user_by_screen_name(handle)
        uid = str(u.id)
    await client.follow_user(uid)
    return {"ok": True, "action": "follow", "target": handle, "uid": uid}


async def _process_one(client: Client, item: dict) -> dict:
    kind = item.get("kind", "tweet")
    text = item.get("text", "")
    to = item.get("to_url") or item.get("to") or item.get("quote_url")
    image_path = item.get("image_path")
    if kind == "tweet":
        return await _post_tweet(client, text, image_path=image_path)
    if kind == "reply":
        return await _post_reply(client, text, to, image_path=image_path)
    if kind == "quote":
        return await _post_quote(client, text, to)
    if kind == "like":
        return await _like(client, to)
    if kind in ("retweet", "rt"):
        return await _retweet(client, to)
    if kind == "bookmark":
        return await _bookmark(client, to)
    if kind == "follow":
        return await _follow(client, to)
    return {"ok": False, "err": f"unsupported kind: {kind}"}


async def main_async() -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    POSTED_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)

    # Crisis freeze short-circuits posting
    if FREEZE_FLAG.exists():
        _log("🔴 CRISIS FREEZE active — skipping posting cycle")
        return

    now = int(time.time())
    files = sorted(QUEUE_DIR.glob("*.json"))
    if not files:
        return
    due = []
    for p in files:
        try:
            item = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            _log(f"corrupt queue file {p.name}: {e}")
            continue
        if item.get("status") != "pending":
            continue
        if item.get("scheduled_time", 0) > now:
            continue
        due.append((p, item))

    if not due:
        return

    if not COOKIES_PATH.exists():
        _log(f"cookies file missing: {COOKIES_PATH}")
        _telegram_notify(f"⚠️ Poster: cookies bulunamadı ({COOKIES_PATH.name}). Refresh gerekli.")
        return

    _log(f"due items: {len(due)}")
    client = Client(LANG)
    client.load_cookies(str(COOKIES_PATH))

    for p, item in due:
        try:
            _log(f"posting {item['id']} ({item.get('kind')}): {item['text'][:80]}...")
            result = await _process_one(client, item)
            if result.get("ok"):
                item["status"] = "posted"
                item["posted_at"] = int(time.time())
                item["tweet_url"] = result.get("tweet_url")
                item["tweet_id"] = result.get("tweet_id")

                # OPTIONAL: link-in-reply tactic (HeavyRanker URL-penalty workaround)
                # If item has `followup_text`, post it as a self-reply.
                fu_text = item.get("followup_text")
                if fu_text and item.get("kind") == "tweet":
                    try:
                        # Brief humanized gap before the followup (12-45s)
                        import random as _rnd
                        await asyncio.sleep(_rnd.uniform(12, 45))
                        fu_result = await _post_followup_reply(
                            client, str(result["tweet_id"]), fu_text
                        )
                        item["followup_tweet_id"] = fu_result.get("tweet_id")
                        item["followup_tweet_url"] = fu_result.get("tweet_url")
                        _log(f"  ↳ followup posted {fu_result.get('tweet_url')}")
                    except Exception as fe:
                        item["followup_error"] = str(fe)
                        _log(f"  ↳ followup FAILED: {fe}")
                        _telegram_notify(
                            f"⚠️ `{item['id']}` followup atılamadı: {str(fe)[:200]}"
                        )

                (POSTED_DIR / p.name).write_text(json.dumps(item, ensure_ascii=False, indent=2))
                p.unlink()
                _log(f"✅ posted {item['id']} → {item['tweet_url']}")
                fu_suffix = (
                    f"\n  ↳ followup: {item.get('followup_tweet_url')}"
                    if item.get("followup_tweet_url") else ""
                )
                # Post-notify: link + Turkish summary (claude CLI, fallback raw)
                kind_label = {
                    "tweet": "Tweet atıldı",
                    "reply": "Cevap atıldı",
                    "quote": "Alıntı atıldı",
                }.get(item.get("kind", "tweet"), "Tweet atıldı")
                summary = _tr_summary(item.get("text", ""))
                summary_line = f"\n\n📝 TR özet: {summary}" if summary else ""
                _telegram_notify(
                    f"✅ {kind_label}\n{item['tweet_url']}{summary_line}{fu_suffix}"
                )
            else:
                err = result.get("err", "unknown")
                item["status"] = "failed"
                item["failed_at"] = int(time.time())
                item["error"] = err
                (FAILED_DIR / p.name).write_text(json.dumps(item, ensure_ascii=False, indent=2))
                p.unlink()
                _log(f"❌ failed {item['id']}: {err}")
                _telegram_notify(f"🔴 `{item['id']}` ATIM HATASI: {err}")
        except Exception as e:
            tb = traceback.format_exc()
            _log(f"exception on {item['id']}: {tb}")
            item["status"] = "failed"
            item["error"] = str(e)
            item["traceback"] = tb
            (FAILED_DIR / p.name).write_text(json.dumps(item, ensure_ascii=False, indent=2))
            p.unlink()
            _telegram_notify(f"🔴 `{item['id']}` EXCEPTION: {str(e)[:200]}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
