#!/usr/bin/env python3
"""poster_twikit.py — HTTP-only queue worker (Chrome-free).

Scans ~/cdpilot-twitter-data/queue/ for items where scheduled_time <= now,
posts via twikit (phin fork) with cookies-only auth — no browser, no CDP.
Notifies Nadir's phone via ntfy (ops/_notify.py) on success/failure: every
push carries the tweet link as its Click, so tapping it opens the post.

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
import _notify  # noqa: E402

DATA = bot_home()
QUEUE_DIR = DATA / "queue"
POSTED_DIR = DATA / "posted"
FAILED_DIR = DATA / "failed"
ARCHIVE_DIR = DATA / "queue-archive"
LOG_FILE = DATA / "logs" / "poster.log"
FREEZE_FLAG = DATA / "state" / "crisis-freeze.flag"
AUTO_REPLY_COUNT_FILE = DATA / "state" / "auto-reply-count.json"
# Guardrails for unattended (AUTO_POST) reply posting
AUTO_REPLY_DAILY_CAP = int(os.environ.get("CDPILOT_AUTO_REPLY_DAILY_CAP", "6"))
REPLY_MAX_AGE_H = int(os.environ.get("CDPILOT_REPLY_MAX_AGE_H", "48"))
# Humanized gap between chained thread tweets (seconds)
THREAD_GAP_S = (20.0, 90.0)
# TR night quiet window — keep in sync with telegram_bridge._schedule_time_for
TR_TZ_OFFSET_S = 3 * 3600
QUIET_START_HOUR = 23
QUIET_END_HOUR = 8
COOKIES_PATH = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES",
    str(DATA / "cookies" / "cdpilot_dev.json"),
))
LANG = os.environ.get("CDPILOT_TWIKIT_LANG", "en-US")


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _phone_notify(title: str, text: str = "", url: str | None = None, *,
                  priority: str = "normal", tags: list[str] | None = None,
                  alarm: bool = False, actions: list[dict] | None = None) -> None:
    """ntfy push (routine channel unless `alarm`). Never raises."""
    try:
        if not _notify.notify(title, text, url=url, priority=priority, tags=tags,
                              alarm=alarm, actions=actions):
            _log(f"ntfy push not delivered: {title}")
    except Exception as e:  # noqa: BLE001
        _log(f"ntfy push failed: {e!r}")


_DONE_LABEL = {
    "tweet": "Tweet atıldı",
    "reply": "Cevap atıldı",
    "quote": "Alıntı atıldı",
    "thread": "Thread atıldı",
    "like": "Beğenildi",
    "retweet": "Repost edildi",
    "rt": "Repost edildi",
    "bookmark": "Yer imi",
    "follow": "Takip edildi",
}
_DONE_TAG = {"tweet": "bird", "reply": "speech_balloon", "quote": "repeat",
             "thread": "thread", "like": "yellow_heart", "retweet": "repeat",
             "rt": "repeat", "bookmark": "bookmark", "follow": "handshake"}


def _target_url(item: dict) -> str | None:
    return _notify.x_url(item.get("to_url") or item.get("to") or item.get("quote_url"))


def _notify_done(item: dict, kind: str, result: dict, summary: str = "") -> None:
    """Post-action push: our tweet link as Click; target as a second button."""
    label = _DONE_LABEL.get(kind, "Tweet atıldı")
    if kind == "thread":
        label += f" ({result.get('thread_count')} tweet)"
    target = _target_url(item)
    own = item.get("tweet_url")
    if kind in ("tweet", "reply", "quote", "thread"):
        url = own or target
        actions = [{"label": "Hedef tweet", "url": target}] if target and target != url else []
        if item.get("followup_tweet_url"):
            actions.append({"label": "Link yanıtı", "url": item["followup_tweet_url"]})
        user = target.split("/status/")[0].rsplit("/", 1)[-1] \
            if target and "/status/" in target else ""
        who = f" → @{user}" if kind == "reply" and user and user != "i" else ""
        body = (summary or (item.get("text") or "")[:200]).strip()
        _phone_notify(f"{label}{who}", body, url, tags=[_DONE_TAG.get(kind, "bird")],
                      actions=actions)
    else:  # like / retweet / bookmark / follow — the target is the link
        _phone_notify(label, (item.get("context") or "")[:160], target,
                      priority="dusuk", tags=[_DONE_TAG.get(kind, "white_check_mark")])


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
            capture_output=True, text=True, timeout=75, check=False,
        )
    except Exception as e:
        _log(f"tr_summary claude call failed: {e}")
        return fallback
    out = (proc.stdout or "").strip()
    return out if out else fallback


def _auto_post_enabled() -> bool:
    """Mirror of ``telegram_bridge.auto_post_enabled()`` — keep semantics in sync.

    Read from env directly so the poster stays import-independent from the
    bridge (it runs standalone inside twikit-venv under systemd/launchd).
    """
    val = os.environ.get("CDPILOT_AUTO_POST", "on").strip().lower()
    return val in ("on", "1", "true", "yes")


def _in_quiet_hours(ts: float) -> bool:
    """True when ``ts`` falls inside the TR night quiet window (23:00-08:00).

    Same window as the quiet-hours guard in
    ``telegram_bridge._schedule_time_for`` — scheduling already avoids the
    window; this is the posting-time backstop for late/rotted items.
    """
    hour = time.gmtime(ts + TR_TZ_OFFSET_S).tm_hour
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


def _humanized_gap(lo: float = THREAD_GAP_S[0], hi: float = THREAD_GAP_S[1]) -> float:
    """Gaussian-ish humanized delay in seconds, clamped to [lo, hi].

    Mid-range mean, sigma = range/6 — same spirit as the existing humanizer
    patterns (followup 12-45s gap, ``_gen_queue_day1.gauss_jitter``).
    """
    import random
    mean = (lo + hi) / 2.0
    sigma = (hi - lo) / 6.0
    return max(lo, min(hi, random.gauss(mean, sigma)))


def _today_str() -> str:
    return time.strftime("%Y-%m-%d")


def _auto_replies_today() -> int:
    """Auto-posted reply count for today (persisted in state/)."""
    try:
        rec = json.loads(AUTO_REPLY_COUNT_FILE.read_text())
    except (OSError, ValueError):
        return 0
    if rec.get("date") != _today_str():
        return 0
    try:
        return int(rec.get("count", 0))
    except (TypeError, ValueError):
        return 0


def _bump_auto_replies_today() -> int:
    count = _auto_replies_today() + 1
    AUTO_REPLY_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTO_REPLY_COUNT_FILE.write_text(
        json.dumps({"date": _today_str(), "count": count})
    )
    return count


def _staleness_ts(item: dict) -> int | None:
    """Best timestamp for the reply staleness gate.

    Prefers the target tweet's own timestamp, falls back to when the item was
    created/approved. ``None`` → age unknown (treated as fresh).
    """
    for key in ("target_created_ts", "created_at", "approved_at"):
        val = item.get(key)
        if isinstance(val, (int, float)) and val > 0:
            return int(val)
    return None


def _archive_stale(p: Path, item: dict) -> None:
    """Move a too-old queue item to queue-archive/ with status=stale."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    item["status"] = "stale"
    item["archived_at"] = int(time.time())
    (ARCHIVE_DIR / p.name).write_text(json.dumps(item, ensure_ascii=False, indent=2))
    p.unlink()
    _log(f"🗄 stale (> {REPLY_MAX_AGE_H}h) → archived {item.get('id')}")


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


async def _post_thread(client: Client, item: dict, queue_path: Path) -> dict:
    """Post a thread item: texts[0] as root, each next text replying to the previous.

    Humanized Gaussian-ish 20-90s gaps between chained tweets (none before the
    root — ``scheduled_time`` already governs the start). Progress
    (``posted_ids`` + ``last_posted_index``) is persisted to the queue file
    after EVERY tweet, so a mid-chain failure leaves ``status="partial"`` and a
    later poster run RESUMES from the next unposted text instead of
    re-posting from scratch.
    """
    texts = [t for t in (item.get("texts") or item.get("thread") or [])
             if isinstance(t, str) and t.strip()]
    if len(texts) < 2:
        return {"ok": False, "err": f"thread needs >=2 non-empty texts, got {len(texts)}"}
    posted_ids: list[str] = [str(t) for t in (item.get("posted_ids") or [])]
    if len(posted_ids) > len(texts):
        return {"ok": False, "err": "posted_ids longer than texts — corrupt thread state"}

    def _persist_progress(error: str | None = None) -> None:
        item["posted_ids"] = posted_ids
        item["last_posted_index"] = len(posted_ids) - 1
        item["status"] = "partial"
        if error:
            item["error"] = error
            item["last_error_at"] = int(time.time())
        queue_path.write_text(json.dumps(item, ensure_ascii=False, indent=2))

    for i in range(len(posted_ids), len(texts)):
        if posted_ids:  # humanized gap between chained tweets only
            await asyncio.sleep(_humanized_gap())
        if FREEZE_FLAG.exists():  # crisis can start mid-chain — stop, resume later
            _persist_progress("crisis-freeze mid-thread")
            return {"ok": False, "partial": True, "err": "crisis-freeze mid-thread",
                    "posted": len(posted_ids), "total": len(texts)}
        try:
            reply_to = posted_ids[-1] if posted_ids else None
            try:
                tw = await client.create_tweet(text=texts[i], reply_to=reply_to)
            except Exception as first:
                # srv21 egress is flaky: ConnectTimeout('') breaks chains for no
                # good reason. One backoff retry before declaring partial.
                if "Timeout" not in type(first).__name__ and "Connect" not in type(first).__name__:
                    raise
                _log(f"  🧵 transient {type(first).__name__} at {i + 1}, retrying in 15s")
                await asyncio.sleep(15)
                tw = await client.create_tweet(text=texts[i], reply_to=reply_to)
        except Exception as e:
            tb = traceback.format_exc()
            _persist_progress(repr(e))
            item["traceback"] = tb
            _log(f"🧵 thread {item.get('id')} broke at {i + 1}/{len(texts)}: {e!r}\n{tb}")
            return {"ok": False, "partial": True, "err": repr(e),
                    "posted": len(posted_ids), "total": len(texts)}
        posted_ids.append(str(tw.id))
        _persist_progress()
        _log(f"  🧵 {len(posted_ids)}/{len(texts)} → {posted_ids[-1]}")

    item.pop("error", None)
    item.pop("last_error_at", None)
    root = posted_ids[0]
    return {"ok": True, "tweet_id": root,
            "tweet_url": f"https://x.com/cdpilot_dev/status/{root}",
            "thread_count": len(texts), "tweet_ids": list(posted_ids)}


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


DUPLICATE_WINDOW_DAYS = 30


def _normalized(text: str) -> str:
    return " ".join((text or "").lower().split())


def _duplicate_of(text: str) -> str | None:
    """Return the id of a recently posted item with identical text, if any.

    A drafting engine that silently degrades emits the same sentence forever:
    on 2026-08-28 a dead claude CLI put the identical 6-word fallback under 14
    different people's tweets, four of them the same account. Text-level
    repetition is a spam signal to X and to humans, so it is blocked here —
    the last gate before anything reaches the timeline.
    """
    norm = _normalized(text)
    if not norm:
        return None
    cutoff = time.time() - DUPLICATE_WINDOW_DAYS * 86400
    for f in POSTED_DIR.glob("*.json"):
        try:
            prev = json.loads(f.read_text())
        except Exception:
            continue
        if prev.get("posted_at", 0) < cutoff:
            continue
        if _normalized(prev.get("text", "")) == norm:
            return prev.get("id", f.stem)
    return None


# X/httpx timeout classes stringify to '' — str(e) alone loses the cause.
IDEMPOTENT_KINDS = {"like", "retweet", "rt", "bookmark", "follow"}


def _err_str(e: BaseException) -> str:
    """httpx.ConnectTimeout('') renders as an empty string, which wrote blank
    `error` fields into failed/ and made post-mortems impossible (2026-08 C8)."""
    return str(e) or repr(e)


def _is_transient(e: BaseException) -> bool:
    name = type(e).__name__
    return "Timeout" in name or "Connect" in name


async def _with_transient_retry(kind: str, item: dict, call):
    """srv21's egress to X drops connections at random; a ConnectTimeout is not
    a rejection. Only idempotent actions retry — re-sending a tweet/reply after
    a timeout could duplicate a post that actually landed server-side."""
    try:
        return await call()
    except Exception as first:
        if not _is_transient(first):
            raise
        _log(f"  ↻ transient {type(first).__name__} on {kind} {item.get('id')} — retrying in 15s")
        await asyncio.sleep(15)
        return await call()


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

    # Held routine pushes (burst limiter) go out as one digest once there is
    # room — the poster is the 5-minute heartbeat that guarantees that.
    try:
        _notify.flush_digest()
    except Exception as e:  # noqa: BLE001
        _log(f"ntfy digest flush failed: {e!r}")

    # Crisis freeze short-circuits posting
    if FREEZE_FLAG.exists():
        _log("🔴 CRISIS FREEZE active — skipping posting cycle")
        return

    now = int(time.time())
    files = sorted(QUEUE_DIR.glob("*.json"))
    if not files:
        return
    auto_post = _auto_post_enabled()
    quiet_now = _in_quiet_hours(now)
    stale_archived = 0
    due = []
    for p in files:
        try:
            item = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            _log(f"corrupt queue file {p.name}: {e}")
            continue
        # "partial" = mid-chain interrupted thread → resume candidate
        if item.get("status") not in ("pending", "partial"):
            continue
        if item.get("scheduled_time", 0) > now:
            continue
        kind = item.get("kind", "tweet")
        # AUTO_POST reply guardrails: staleness → archive; quiet hours → defer.
        if auto_post and kind == "reply":
            ts = _staleness_ts(item)
            if ts is not None and (now - ts) > REPLY_MAX_AGE_H * 3600:
                _archive_stale(p, item)
                stale_archived += 1
                continue
            if quiet_now:
                _log(f"🌙 quiet hours — auto-reply {item.get('id')} deferred")
                continue
        # Threads never start (or resume) inside the quiet window.
        if kind == "thread" and quiet_now:
            _log(f"🌙 quiet hours — thread {item.get('id')} deferred")
            continue
        due.append((p, item))

    if stale_archived:
        _phone_notify(
            "Bayat yanıt arşivlendi",
            f"{stale_archived} yanıt {REPLY_MAX_AGE_H} saatten eski — atılmadı.",
            priority="dusuk", tags=["file_cabinet"],
        )

    if not due:
        return

    if not COOKIES_PATH.exists():
        _log(f"cookies file missing: {COOKIES_PATH}")
        _phone_notify("Poster: cookie yok",
                      f"{COOKIES_PATH.name} bulunamadı — hiçbir şey atılamıyor. Refresh gerekli.",
                      priority="yuksek", tags=["warning"], alarm=True)
        return

    _log(f"due items: {len(due)}")
    client = Client(LANG)
    client.load_cookies(str(COOKIES_PATH))

    for p, item in due:
        kind = item.get("kind", "tweet")
        try:
            # AUTO_POST daily cap: max N unattended replies/day (persisted state).
            if auto_post and kind == "reply" and _auto_replies_today() >= AUTO_REPLY_DAILY_CAP:
                _log(f"⏸ auto-reply daily cap ({AUTO_REPLY_DAILY_CAP}) reached — "
                     f"{item['id']} deferred")
                continue
            preview = (item.get("text") or (item.get("texts") or ["?"])[0])[:80]
            if kind in ("tweet", "reply", "quote"):
                dup = _duplicate_of(item.get("text", ""))
                if dup:
                    item["status"] = "failed"
                    item["failed_at"] = int(time.time())
                    item["error"] = f"duplicate text already posted as {dup}"
                    (FAILED_DIR / p.name).write_text(
                        json.dumps(item, ensure_ascii=False, indent=2))
                    p.unlink()
                    _log(f"⛔ duplicate {item['id']} — same text as {dup}, not posting")
                    _phone_notify(
                        "Tekrar metin engellendi",
                        f"{item['id']} atılmadı: metin {dup} ile birebir aynı. "
                        "Taslak üreteci bozuk olabilir.",
                        _target_url(item), priority="yuksek", tags=["no_entry"],
                        alarm=True,
                    )
                    continue
            _log(f"posting {item['id']} ({kind}): {preview}...")
            if kind == "thread":
                result = await _post_thread(client, item, p)
            elif kind in IDEMPOTENT_KINDS:
                result = await _with_transient_retry(
                    kind, item, lambda: _process_one(client, item)
                )
            else:
                result = await _process_one(client, item)
            if result.get("ok"):
                item["status"] = "posted"
                item["posted_at"] = int(time.time())
                item["tweet_url"] = result.get("tweet_url")
                item["tweet_id"] = result.get("tweet_id")
                if kind == "thread":
                    item["tweet_ids"] = result.get("tweet_ids")
                    item["thread_count"] = result.get("thread_count")
                if auto_post and kind == "reply":
                    _bump_auto_replies_today()

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
                        _phone_notify(
                            "Link yanıtı atılamadı",
                            f"{item['id']}: {str(fe)[:200]}",
                            item.get("tweet_url"), tags=["warning"], alarm=True,
                        )

                (POSTED_DIR / p.name).write_text(json.dumps(item, ensure_ascii=False, indent=2))
                p.unlink()
                _log(f"✅ posted {item['id']} → {item.get('tweet_url')}")
                # Post-notify: link as Click + Turkish summary (claude CLI, fallback raw)
                summary = ""
                if kind in ("tweet", "reply", "quote", "thread"):
                    summary = _tr_summary(
                        item.get("text") or (item.get("texts") or [""])[0]
                    )
                _notify_done(item, kind, result, summary)
            elif result.get("partial"):
                # Mid-chain thread failure: progress already persisted to the
                # queue file (status=partial) — next poster run resumes there.
                _log(f"🧵 partial {item['id']}: {result.get('posted')}/"
                     f"{result.get('total')} — will resume next run")
                root = (item.get("posted_ids") or [None])[0]
                _phone_notify(
                    "Thread yarım kaldı",
                    f"{item['id']}: {result.get('posted')}/{result.get('total')} atıldı — "
                    f"sonraki koşu kaldığı yerden sürer. ({str(result.get('err'))[:150]})",
                    _notify.status_url(root, _notify.HANDLE) if root else None,
                    priority="yuksek", tags=["warning"], alarm=True,
                )
            else:
                err = result.get("err", "unknown")
                item["status"] = "failed"
                item["failed_at"] = int(time.time())
                item["error"] = err
                (FAILED_DIR / p.name).write_text(json.dumps(item, ensure_ascii=False, indent=2))
                p.unlink()
                _log(f"❌ failed {item['id']}: {err}")
                _phone_notify("Atım hatası", f"{item['id']} ({kind}): {str(err)[:200]}",
                              _target_url(item), priority="yuksek", tags=["x"],
                              alarm=True)
        except Exception as e:
            tb = traceback.format_exc()
            _log(f"exception on {item['id']}: {tb}")
            if kind == "thread" and item.get("posted_ids"):
                # Never lose a partially-posted chain to failed/ — keep the
                # queue file (status=partial) so the next run resumes it.
                item["status"] = "partial"
                item["error"] = _err_str(e)
                p.write_text(json.dumps(item, ensure_ascii=False, indent=2))
                _phone_notify(
                    "Thread hatası (ilerleme korundu)",
                    f"{item['id']}: {_err_str(e)[:200]}",
                    _notify.status_url(item["posted_ids"][0], _notify.HANDLE),
                    priority="yuksek", tags=["warning"], alarm=True,
                )
                continue
            item["status"] = "failed"
            item["error"] = _err_str(e)
            item["traceback"] = tb
            (FAILED_DIR / p.name).write_text(json.dumps(item, ensure_ascii=False, indent=2))
            p.unlink()
            _phone_notify("Atım hatası", f"{item['id']} ({kind}): {_err_str(e)[:200]}",
                          _target_url(item), priority="yuksek", tags=["x"], alarm=True)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
