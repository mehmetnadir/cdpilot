"""telegram_bridge.py — Cowork ↔ Mobile approval pipe.

Two-way Telegram bridge for cdpilot Twitter approval flow:
  - Outbound: send batch of drafts to user with inline approve/edit/skip buttons
  - Inbound: poll getUpdates, parse user replies (commands, callback_queries)

Zero deps: pure stdlib (urllib + json). Same philosophy as cdpilot core.

Credentials loaded from ~/cdpilot-twitter-data/telegram.env (chmod 600).
Never logs the token. Chat-id pinned — only the configured user can drive the bot.

Usage:
  python3 telegram_bridge.py setup           # auto-detect chat_id from /start
  python3 telegram_bridge.py send "msg"      # send a plain message
  python3 telegram_bridge.py batch <file>    # send a structured draft batch (JSON)
  python3 telegram_bridge.py poll            # one-shot getUpdates dump
  python3 telegram_bridge.py wait-approval   # block until user clicks a button
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

_DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
ENV_PATH = Path(os.environ.get("CDPILOT_TELEGRAM_ENV", str(_DATA / "telegram.env")))
STATE_PATH = _DATA / "telegram-state.json"
PENDING_PATH = _DATA / "telegram-pending.json"
QUEUE_DIR = _DATA / "queue"
POSTED_DIR = _DATA / "posted"
API = "https://api.telegram.org"


def _load_env() -> dict:
    if not ENV_PATH.exists():
        sys.exit(f"missing {ENV_PATH} — create it with TELEGRAM_BOT_TOKEN first")
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    if not env.get("TELEGRAM_BOT_TOKEN"):
        sys.exit("TELEGRAM_BOT_TOKEN missing in telegram.env")
    return env


def _save_env(env: dict) -> None:
    lines = [
        "# cdpilot Twitter Approvals — Telegram Bridge",
        "# chmod 600. NEVER commit. NEVER share.",
        f"TELEGRAM_BOT_TOKEN={env.get('TELEGRAM_BOT_TOKEN', '')}",
        f"TELEGRAM_BOT_USERNAME={env.get('TELEGRAM_BOT_USERNAME', '')}",
        "# TELEGRAM_CHAT_ID populated by ops/telegram_setup.py after user /start",
        f"TELEGRAM_CHAT_ID={env.get('TELEGRAM_CHAT_ID', '')}",
    ]
    ENV_PATH.write_text("\n".join(lines) + "\n")
    os.chmod(ENV_PATH, 0o600)


def _api(env: dict, method: str, params: dict | None = None, timeout: int = 30) -> dict:
    """POST to Telegram Bot API. Returns parsed JSON or raises."""
    url = f"{API}/bot{env['TELEGRAM_BOT_TOKEN']}/{method}"
    data = json.dumps(params or {}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode())
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed: {body.get('description')}")
    return body.get("result", {})


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (OSError, ValueError):
            pass
    return {"last_update_id": 0}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))
    os.chmod(STATE_PATH, 0o600)


def _load_pending() -> dict:
    """Map of {message_id (str): draft_dict} for daemon to process."""
    if PENDING_PATH.exists():
        try:
            return json.loads(PENDING_PATH.read_text())
        except (OSError, ValueError):
            pass
    return {}


def _save_pending(pending: dict) -> None:
    PENDING_PATH.write_text(json.dumps(pending, ensure_ascii=False, indent=2))
    os.chmod(PENDING_PATH, 0o600)
    # Best-effort sync to srv21 so the daemon there has the same view.
    remote = os.environ.get("CDPILOT_PENDING_RSYNC",
                            "srv21:/opt/cdpilot-twitter-bot/telegram-pending.json")
    if remote and os.environ.get("CDPILOT_PENDING_RSYNC_DISABLE") != "1":
        try:
            import subprocess
            subprocess.run(
                ["rsync", "-a", str(PENDING_PATH), remote],
                check=False, timeout=15, capture_output=True,
            )
        except Exception:
            pass


def _register_pending(message_id: int, draft: dict) -> None:
    """Persist a draft as pending so daemon can act on its callback later."""
    pending = _load_pending()
    pending[str(message_id)] = {
        "draft_id": draft["id"],
        "draft": draft,
        "registered_at": int(time.time()),
    }
    _save_pending(pending)


def _resolve_pending(message_id: int) -> dict | None:
    """Lookup + remove the pending draft for a given message_id."""
    pending = _load_pending()
    rec = pending.pop(str(message_id), None)
    _save_pending(pending)
    return rec


def cmd_setup() -> None:
    """Auto-detect chat_id from the most recent /start.

    User MUST send /start (or any message) to the bot before this runs.
    Pulls getUpdates, picks the latest private chat that messaged us.
    """
    env = _load_env()
    print("Fetching updates from Telegram...")
    updates = _api(env, "getUpdates", {"timeout": 1, "limit": 50})

    candidates: list[tuple[int, str]] = []
    for u in updates:
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") == "private":
            candidates.append((chat["id"], chat.get("username") or chat.get("first_name", "?")))

    if not candidates:
        sys.exit("No private messages found. Open https://t.me/{} and send /start, then re-run.".format(
            env.get("TELEGRAM_BOT_USERNAME", "your-bot")))

    chat_id, who = candidates[-1]
    env["TELEGRAM_CHAT_ID"] = str(chat_id)
    _save_env(env)
    print(f"Linked chat_id={chat_id} (user={who})")
    print("Sending test message...")
    _api(env, "sendMessage", {
        "chat_id": chat_id,
        "text": (
            "🤖 *cdpilot Twitter Onay Sistemi* — köprü bağlandı.\n"
            "Buradan tweet/reply taslakları için onay batch'leri alacaksın.\n\n"
            "_İçerik dili:_ İngilizce (X paylaşımları)\n"
            "_Arayüz dili:_ Türkçe (bu mesajlar, butonlar)\n"
        ),
        "parse_mode": "Markdown",
    })
    print("Done.")


def cmd_send(text: str) -> None:
    env = _load_env()
    if not env.get("TELEGRAM_CHAT_ID"):
        sys.exit("TELEGRAM_CHAT_ID not set — run: telegram_bridge.py setup")
    # Plain sender — no Markdown parse to avoid escape headaches on URLs etc.
    _api(env, "sendMessage", {
        "chat_id": int(env["TELEGRAM_CHAT_ID"]),
        "text": text,
        "disable_web_page_preview": True,
    })
    print("sent")


_TLD_RE = re.compile(
    r"\b[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"\.(?:com|org|net|io|dev|ai|co|sh|me|app|xyz|gg|so|run|fyi|tech|edu|gov|info|"
    r"ist|tr|de|uk|us|jp|cn|br|fr|in|tv|cc|ist|live|news|cloud|host|site|store|"
    r"github\.io|netlify\.app|vercel\.app|workers\.dev)\b(?:/\S*)?",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _reply_bait_score(text: str) -> dict:
    """Score how reply-baity a tweet is. Returns dict with score (0-3) + reasons.

    Reply-baity = ends with question OR provocative claim that invites disagreement.
    HeavyRanker gives replies a +27 weight; reply-bait = reach amplifier.

    Score:
      3 = ends with ? + asks for opinion/counter
      2 = ends with ? OR provocative claim (counter:/disagree?/your take?)
      1 = some interrogative or invitational phrase, but not at end
      0 = no reply trigger, will get scroll
    """
    t = text.strip()
    if not t:
        return {"score": 0, "reasons": ["empty"], "tail": ""}

    # Look at last non-empty line
    last_line = ""
    for line in reversed(t.splitlines()):
        if line.strip():
            last_line = line.strip()
            break

    score = 0
    reasons: list[str] = []
    tail = last_line[-60:]

    if last_line.endswith("?"):
        score += 2
        reasons.append("ends with ?")

    invitations = [
        "your take", "thoughts?", "counter?", "disagree?", "am i wrong",
        "is this", "anyone else", "what am i missing", "fight me",
        "change my mind", "convince me", "is there", "/thread",
        "karşı?", "sizce?", "yanılıyor muyum", "hangi", "ne dersin",
    ]
    if any(inv in last_line.lower() for inv in invitations):
        score += 1
        reasons.append("invitation phrase")

    provocative = [
        "is brutal", "is a choice", "isn't your fault", "you're holding it wrong",
        "the real reason", "everyone is wrong", "this is the part",
        "hot take", "controversial:", "burada gördüğüm",
    ]
    if any(p in t.lower() for p in provocative):
        score += 1
        reasons.append("provocative claim")

    return {"score": min(score, 3), "reasons": reasons or ["no trigger"], "tail": tail}


def _twitter_weighted_len(text: str) -> tuple[int, list[str]]:
    """Compute Twitter weighted character count + URL list.

    - URLs (http(s)://… or bare-domain.tld) are replaced with 23-char t.co stand-in.
    - Char weighting: 0-4351 = 1; specific punctuation ranges = 1; else = 2.

    Returns: (weighted_count, found_urls)
    """
    urls: list[str] = []
    masked = text
    # 1) Strip explicit URLs
    def _sub_explicit(m: "re.Match[str]") -> str:
        urls.append(m.group(0))
        return "x" * 23
    masked = _URL_RE.sub(_sub_explicit, masked)
    # 2) Strip bare-domain auto-links (only single-word matches not already substituted)
    def _sub_bare(m: "re.Match[str]") -> str:
        urls.append(m.group(0))
        return "x" * 23
    masked = _TLD_RE.sub(_sub_bare, masked)

    w = 0
    for c in masked:
        o = ord(c)
        if 0 <= o <= 4351 or 8192 <= o <= 8205 or 8208 <= o <= 8223 or 8242 <= o <= 8247:
            w += 1
        else:
            w += 2
    return w, urls


def cmd_draft(json_path: str) -> None:
    """Send a SINGLE draft as one message with Approve/Skip buttons.

    User can press a button OR reply to the message with corrected text (= edit).

    Expected JSON:
    {
      "id": "fz0-1",
      "kind": "tweet|reply|quote|thread|follow|like|retweet",
      "to": "@username" (optional, for reply/quote),
      "context": "neden bu tweet" (TR, kullanıcıya),
      "text_tr": "Türkçe önizleme (sen okursun)",
      "text": "English post (atılacak metin)"
    }

    Prints: {"draft_id": "...", "message_id": N}  (Cowork bunu wait-decision'a verir)
    """
    env = _load_env()
    if not env.get("TELEGRAM_CHAT_ID"):
        sys.exit("TELEGRAM_CHAT_ID not set — run: telegram_bridge.py setup")

    d = json.loads(Path(json_path).read_text())
    did = d["id"]

    kind_tr = {"tweet": "yeni tweet", "reply": "yanıt", "quote": "alıntı tweet",
               "thread": "thread", "follow": "takip", "like": "beğeni",
               "retweet": "retweet"}
    prefix = "🐦" if d.get("kind") == "tweet" else ("💬" if d.get("kind") == "reply" else "🔁")
    kind_label = kind_tr.get(d.get("kind", ""), d.get("kind", "öğe"))
    target = f" → {d.get('to')}" if d.get("to") else ""
    ctx = f"\n_bağlam:_ {d['context']}\n" if d.get("context") else ""
    tr_preview = d.get("text_tr") or d.get("text", "")
    en_post = d.get("text", "")

    # Plain text — Telegram Markdown is too brittle for arbitrary tweet content
    # (underscores in code, asymmetric backticks, parens in italic markers, etc).
    body = f"{prefix} {kind_label}{target}  · {did}\n"
    if d.get("context"):
        body += f"bağlam: {d['context']}\n"

    # URL-aware Twitter length pre-check on the EN text we'd actually post
    if en_post:
        weighted, urls = _twitter_weighted_len(en_post)
        if weighted > 280:
            body += (
                f"\n⛔ UZUN: {weighted}/280 weighted "
                f"(raw {len(en_post)} char, {len(urls)} auto-link). "
                "X bunu reddeder — kısalt veya URL'leri kaldır.\n"
            )
        elif weighted > 270:
            body += f"\n⚠️ sınırda: {weighted}/280 weighted ({len(urls)} auto-link)\n"
        else:
            body += f"\n📏 length: {weighted}/280 weighted"
            if urls:
                body += f" · {len(urls)} auto-link"
            body += "\n"

        # Reply-bait audit (HeavyRanker reply +27 → end with question/claim)
        bait = _reply_bait_score(en_post)
        if bait["score"] >= 2:
            body += f"🎣 reply-bait: GOOD ({bait['score']}/3 · {', '.join(bait['reasons'])})\n"
        elif bait["score"] == 1:
            body += f"🎣 reply-bait: WEAK ({bait['score']}/3 · {', '.join(bait['reasons'])}) — son satırı soru/iddia ile bitirmeyi düşün\n"
        else:
            body += f"🎣 reply-bait: NONE (0/3) — bu tweet scroll edilir, son satıra soru/karşıt iddia ekle\n"

    body += f"\n📖 türkçe önizleme:\n{tr_preview}\n"
    if d.get("text_tr") and en_post and en_post != tr_preview:
        body += f"\n🐦 atılacak (EN):\n{en_post}\n"
    if d.get("followup_text"):
        body += f"\n🔗 ilk reply (URL):\n{d['followup_text']}\n"
    body += "\n— düzeltmek için: bu mesaja reply yap, doğru metni yaz —"

    # Generate image on-demand if draft has image_content
    image_path = d.get("image_path")
    if not image_path and d.get("image_content"):
        try:
            from image_gen import generate as _img_generate  # type: ignore
        except ImportError:
            sys.path.insert(0, str(Path(__file__).parent))
            from image_gen import generate as _img_generate  # type: ignore
        try:
            img_id = f"draft-{did}"
            img_out = _img_generate(img_id, d["image_content"],
                                    title=d.get("image_title"),
                                    size=d.get("image_size", "1080x1080"))
            image_path = img_out["path"]
            d["image_path"] = image_path
        except Exception as e:
            sys.stderr.write(f"image gen failed for {did}: {e}\n")

    # Build button rows — add regen + no-image when an image is present
    if image_path:
        rows = [
            [{"text": "✅ Onayla", "callback_data": f"approve:{did}"},
             {"text": "🔁 Yeni görsel", "callback_data": f"regen:{did}"}],
            [{"text": "📝 Görselsiz at", "callback_data": f"noimage:{did}"},
             {"text": "⏭ Geç", "callback_data": f"skip:{did}"}],
        ]
    else:
        rows = [[
            {"text": "✅ Onayla", "callback_data": f"approve:{did}"},
            {"text": "⏭ Geç", "callback_data": f"skip:{did}"},
        ]]

    # If image generated locally, mirror to srv21 so the daemon (which runs there)
    # can reference the same path when queueing for poster.
    if image_path and Path(image_path).exists():
        remote_root = os.environ.get(
            "CDPILOT_IMAGE_RSYNC_ROOT", "srv21:/opt/cdpilot-twitter-bot/images/")
        if remote_root and os.environ.get("CDPILOT_IMAGE_RSYNC_DISABLE") != "1":
            try:
                import subprocess
                subprocess.run(["rsync", "-a", str(image_path), remote_root],
                               check=False, timeout=20, capture_output=True)
                # Translate path: srv21 sees it at /opt/cdpilot-twitter-bot/images/<name>
                d["image_path"] = f"/opt/cdpilot-twitter-bot/images/{Path(image_path).name}"
            except Exception as e:
                sys.stderr.write(f"image rsync to srv21 failed: {e}\n")

    if image_path and Path(image_path).exists():
        # sendPhoto with caption + inline buttons
        result = _send_photo(env, int(env["TELEGRAM_CHAT_ID"]), image_path,
                              caption=body[:1024], reply_markup={"inline_keyboard": rows})
    else:
        result = _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": body[:4000],
            "reply_markup": {"inline_keyboard": rows},
            "disable_web_page_preview": True,
        })
    msg_id = result.get("message_id")
    # Register so the daemon can act on user's later button press/reply.
    if msg_id is not None:
        _register_pending(msg_id, d)
    print(json.dumps({"draft_id": did, "message_id": msg_id}))


def _send_photo(env: dict, chat_id: int, photo_path: str, *,
                caption: str = "", reply_markup: dict | None = None,
                timeout: int = 60) -> dict:
    """sendPhoto via multipart/form-data (stdlib only)."""
    import secrets
    boundary = "----cdpilotbnd" + secrets.token_hex(8)
    parts: list[bytes] = []

    def _field(name: str, value: str):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                     f"name=\"{name}\"\r\n\r\n{value}\r\n".encode())

    _field("chat_id", str(chat_id))
    if caption:
        _field("caption", caption)
    if reply_markup is not None:
        _field("reply_markup", json.dumps(reply_markup))

    with open(photo_path, "rb") as f:
        photo_bytes = f.read()
    fname = Path(photo_path).name
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; "
        f"filename=\"{fname}\"\r\nContent-Type: image/png\r\n\r\n".encode()
    )
    parts.append(photo_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    url = f"{API}/bot{env['TELEGRAM_BOT_TOKEN']}/sendPhoto"
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        data = json.loads(e.read().decode())
    if not data.get("ok"):
        raise RuntimeError(f"sendPhoto failed: {data.get('description')}")
    return data.get("result", {})


def _schedule_time_for(now_ts: float, kind: str, index: int) -> int:
    """Plan a scheduled_time for a draft post.

    Rules (basic, Faz 2 makul defaults):
      - First draft of the day: next peak window (16:00-19:00 TR or 22:00-01:00 TR)
      - Subsequent drafts: previous + 4-8h Gauss jitter
      - Replies: 30-90 min after now (faster than tweets)
      - Never schedule between 23:00-08:00 TR (night quiet window)

    Caller can override by including `scheduled_time` in the draft JSON.
    """
    import datetime
    import random
    tz_offset = 3 * 3600  # TR
    now = datetime.datetime.fromtimestamp(now_ts + tz_offset, tz=datetime.timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    peak1_start = today + datetime.timedelta(hours=16)
    peak1_end = today + datetime.timedelta(hours=19)
    peak2_start = today + datetime.timedelta(hours=22)
    quiet_end = today + datetime.timedelta(hours=8)  # next morning
    if kind in ("reply", "quote"):
        # 30-90 min from now, jittered
        delta = random.randint(30 * 60, 90 * 60)
        sched = now + datetime.timedelta(seconds=delta)
    else:
        # Tweet: target peak window
        if now < peak1_start:
            base = peak1_start + datetime.timedelta(minutes=random.randint(0, 180))
        elif now < peak1_end:
            base = now + datetime.timedelta(minutes=random.randint(10, 60))
        elif now < peak2_start:
            base = peak2_start + datetime.timedelta(minutes=random.randint(0, 90))
        else:
            # Past peak2 — schedule for tomorrow peak1
            tomorrow_peak1 = peak1_start + datetime.timedelta(days=1)
            base = tomorrow_peak1 + datetime.timedelta(minutes=random.randint(0, 180))
        # Index-based spacing — multi-tweets spread across days
        base += datetime.timedelta(hours=index * 18 + random.randint(-3, 3))
        sched = base
    # Quiet hours guard
    if 23 <= sched.hour or sched.hour < 8:
        sched = sched.replace(hour=9, minute=random.randint(0, 59))
        if sched < now:
            sched += datetime.timedelta(days=1)
    return int(sched.timestamp() - tz_offset)


def _queue_draft(d: dict, decision: dict, idx: int) -> Path:
    """Write an approved draft to local queue/<id>.json + auto-rsync to srv21.

    Local file goes to ~/cdpilot-twitter-data/queue/.
    If CDPILOT_QUEUE_RSYNC is set (e.g. 'srv21:/opt/cdpilot-twitter-bot/queue/'),
    the file is also pushed there immediately after write. Server-side systemd
    timer (cdpilot-poster.timer) picks it up within 5 minutes.
    """
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    final_text = decision.get("edited_text") or d.get("text", "")
    item = {
        "id": d["id"],
        "kind": d.get("kind", "tweet"),
        "to": d.get("to"),
        "text": final_text,
        "context": d.get("context"),
        "status": "pending",
        "approved_at": int(time.time()),
        "scheduled_time": d.get("scheduled_time") or _schedule_time_for(
            time.time(), d.get("kind", "tweet"), idx
        ),
        "edited": bool(decision.get("edited_text")),
    }
    if d.get("followup_text"):
        item["followup_text"] = d["followup_text"]
    if d.get("image_path"):
        item["image_path"] = d["image_path"]
    p = QUEUE_DIR / f"{d['id']}.json"
    p.write_text(json.dumps(item, ensure_ascii=False, indent=2))

    # Auto-rsync to remote queue (best-effort)
    remote = os.environ.get("CDPILOT_QUEUE_RSYNC", "srv21:/opt/cdpilot-twitter-bot/queue/")
    if remote:
        try:
            import subprocess
            subprocess.run(
                ["rsync", "-a", str(p), remote],
                check=False, timeout=20, capture_output=True,
            )
        except Exception:
            pass
    return p


def cmd_batch_seq(json_path: str) -> None:
    """Sequential batch helper: send N drafts one-by-one, wait for each decision.

    On approve (or edit), the draft is automatically queued to
    ~/cdpilot-twitter-data/queue/<id>.json with a scheduled_time chosen
    according to peak windows + jitter + per-kind rules. The local posting
    worker (cdpilot-twitter-poster.plist) picks them up at scheduled_time.

    Designed to be called by Cowork as the daily orchestrator.
    """
    env = _load_env()
    if not env.get("TELEGRAM_CHAT_ID"):
        sys.exit("TELEGRAM_CHAT_ID not set — run: telegram_bridge.py setup")

    data = json.loads(Path(json_path).read_text())
    label = data.get("label", "Batch")
    drafts = data["drafts"]
    timeout_per = int(data.get("timeout_per_draft", 7200))

    _api(env, "sendMessage", {
        "chat_id": int(env["TELEGRAM_CHAT_ID"]),
        "text": f"📬 *{label}*\n{len(drafts)} taslak sırayla gelecek. Her birine ayrı karar ver.",
        "parse_mode": "Markdown",
    })

    decisions = []
    queued = 0
    for idx, d in enumerate(drafts):
        tmp = Path(f"/tmp/draft-{d['id']}.json")
        tmp.write_text(json.dumps(d))
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_draft(str(tmp))
        send_out = json.loads(buf.getvalue().strip())
        msg_id = send_out["message_id"]
        dec = _wait_one_decision(env, d["id"], msg_id, timeout_per)
        decisions.append(dec)
        tmp.unlink(missing_ok=True)

        # AUTO-QUEUE on approve/edit
        if dec.get("action") in ("approve", "edit"):
            qp = _queue_draft(d, dec, idx)
            queued += 1
            # Notify scheduled time back
            sched_iso = time.strftime("%Y-%m-%d %H:%M", time.localtime(json.loads(qp.read_text())["scheduled_time"]))
            try:
                _api(env, "sendMessage", {
                    "chat_id": int(env["TELEGRAM_CHAT_ID"]),
                    "text": f"📥 `{d['id']}` kuyrukta — planlanan: *{sched_iso}*",
                    "parse_mode": "Markdown",
                })
            except Exception:
                pass

        if dec.get("action") == "abort":
            break

    # Summary
    try:
        _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": (
                f"🏁 *Batch tamamlandı:* `{label}`\n"
                f"Onaylanan: {sum(1 for x in decisions if x['action'] in ('approve','edit'))} · "
                f"Geçilen: {sum(1 for x in decisions if x['action']=='skip')} · "
                f"Kuyrukta: {queued}"
            ),
            "parse_mode": "Markdown",
        })
    except Exception:
        pass
    print(json.dumps({"label": label, "decisions": decisions, "queued": queued}, ensure_ascii=False, indent=2))


def _wait_one_decision(env: dict, draft_id: str, message_id: int, timeout_sec: int) -> dict:
    """Block until user makes a decision on draft `draft_id` (msg `message_id`).

    Decision is one of:
      - {action: approve, draft_id}             — button ✅
      - {action: skip, draft_id}                — button ⏭
      - {action: edit, draft_id, edited_text}   — user replied to the message
      - {action: timeout, draft_id}             — elapsed without decision
      - {action: abort, draft_id}               — user sent /stop

    Edits original message to reflect the decision (strips buttons + adds status line).
    """
    state = _load_state()
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        wait = min(50, max(1, int(deadline - time.time())))
        updates = _api(env, "getUpdates", {
            "timeout": wait, "offset": state["last_update_id"] + 1, "limit": 20,
        })
        if updates:
            state["last_update_id"] = max(u["update_id"] for u in updates)
            _save_state(state)
        for u in updates:
            # /stop = abort
            msg = u.get("message") or u.get("edited_message") or {}
            if msg.get("text", "").strip().lower() in ("/stop", "/iptal", "/dur"):
                return {"action": "abort", "draft_id": draft_id}

            # Reply to our draft message = edit
            reply_to = (msg.get("reply_to_message") or {}).get("message_id")
            if reply_to == message_id and msg.get("text"):
                new_text = msg["text"]
                _edit_msg_status(env, message_id, "✏️ Düzeltildi", suffix=f"\n_yeni metin:_\n```\n{new_text}\n```")
                return {"action": "edit", "draft_id": draft_id, "edited_text": new_text}

            cb = u.get("callback_query")
            if not cb:
                continue
            data = cb.get("data", "")
            parts = data.split(":", 1)
            action = parts[0]
            cb_did = parts[1] if len(parts) > 1 else ""
            if cb_did != draft_id:
                _api(env, "answerCallbackQuery", {"callback_query_id": cb["id"], "text": "stale"})
                continue
            action_tr = {"approve": "✅ Onaylandı", "skip": "⏭ Geçildi"}.get(action, action)
            _api(env, "answerCallbackQuery", {"callback_query_id": cb["id"], "text": action_tr})
            _edit_msg_status(env, message_id, action_tr)
            return {"action": action, "draft_id": draft_id}
    return {"action": "timeout", "draft_id": draft_id}


def _edit_msg_status(env: dict, message_id: int, status: str, suffix: str = "") -> None:
    """Update an existing draft message: strip buttons, append status line."""
    chat_id = int(env["TELEGRAM_CHAT_ID"])
    now_hm = time.strftime("%H:%M")
    # First, remove the buttons (works even if text edit fails)
    try:
        _api(env, "editMessageReplyMarkup", {
            "chat_id": chat_id, "message_id": message_id,
            "reply_markup": {"inline_keyboard": []},
        })
    except Exception:
        pass
    # Then try to append status (best-effort; Markdown may fail on edge cases)
    try:
        _api(env, "sendMessage", {
            "chat_id": chat_id,
            "text": f"— *{status}* — {now_hm}{suffix}",
            "parse_mode": "Markdown",
            "reply_to_message_id": message_id,
            "disable_web_page_preview": True,
        })
    except Exception:
        pass


def cmd_wait_decision(draft_id: str, message_id: int, timeout: int) -> None:
    """One-shot wait for a single draft's decision. Prints JSON, exits."""
    env = _load_env()
    dec = _wait_one_decision(env, draft_id, message_id, timeout)
    print(json.dumps(dec, ensure_ascii=False))
    sys.exit({"approve": 0, "skip": 2, "edit": 3, "timeout": 1, "abort": 4}.get(dec["action"], 1))


def cmd_poll(timeout: int = 1) -> None:
    """One-shot dump of pending updates (debug)."""
    env = _load_env()
    state = _load_state()
    updates = _api(env, "getUpdates", {
        "timeout": timeout, "offset": state["last_update_id"] + 1, "limit": 50,
    })
    if updates:
        state["last_update_id"] = max(u["update_id"] for u in updates)
        _save_state(state)
    print(json.dumps(updates, indent=2, ensure_ascii=False))


def cmd_incoming_reply(json_path: str) -> None:
    """Notify Telegram of an incoming reply/mention with 3-button decision card.

    Expected JSON (from mention_scraper inbox/*.json):
      {
        "tweet_id": "...",
        "author": "@somebody",
        "text": "their reply text",
        "tweet_url": "https://x.com/.../status/...",
        "is_reply_to_us": true,
        ...
      }

    Card actions:
      💬 Cevap yaz  → user replies to message with text → daemon queues as kind=reply
      💛 Like       → daemon queues as kind=like
      ⏭ Atla       → mark inbox seen, no action
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from _sanitize import sanitize, render_flags  # type: ignore

    env = _load_env()
    if not env.get("TELEGRAM_CHAT_ID"):
        sys.exit("TELEGRAM_CHAT_ID not set — run: telegram_bridge.py setup")

    m = json.loads(Path(json_path).read_text())
    tid = m.get("tweet_id")
    author = m.get("author", "@?")
    raw_text = m.get("text", "")
    san = sanitize(raw_text)
    url = m.get("tweet_url", "")

    # Detect language from the incoming text (heuristic — Turkish-specific chars)
    lang = "tr" if any(c in san["clean"] for c in "çğıöşüÇĞİÖŞÜ") else "en"

    # Generate AI draft (Claude CLI via reply_drafter) unless flagged unsafe
    ai_draft = ""
    if san.get("drop"):
        ai_draft = ""  # don't draft for dropped (crisis_topic / url_bomb)
    else:
        try:
            from reply_drafter import draft as _make_draft  # type: ignore
            parent = m.get("parent_tweet_text") or None
            res = _make_draft(san["clean"], parent=parent, author=author, lang=lang)
            ai_draft = res.get("draft", "") if not res.get("fallback") else ""
        except Exception as e:
            sys.stderr.write(f"reply_drafter failed for {tid}: {e}\n")
            ai_draft = ""

    flags_str = render_flags(san["flags"])
    body = (
        f"💬 yeni yorum · {author}\n"
        f"{flags_str}\n\n"
        f"📥 yorum (sanitized):\n{san['clean'][:500]}\n\n"
    )
    if ai_draft:
        body += f"✨ AI taslağı ({lang.upper()}):\n{ai_draft}\n\n"
    body += (
        f"🔗 {url}\n"
        f"— manuel yazmak için: bu mesaja reply yap, kendi metnini gönder —"
    )

    if ai_draft:
        rows = [
            [{"text": "✨ AI taslağını at", "callback_data": f"aireply:{tid}"},
             {"text": "💬 Manuel yaz", "callback_data": f"replywrite:{tid}"}],
            [{"text": "💛 Sadece like", "callback_data": f"likemention:{tid}"},
             {"text": "⏭ Atla", "callback_data": f"mskip:{tid}"}],
        ]
    else:
        rows = [[
            {"text": "💬 Cevap yaz", "callback_data": f"replywrite:{tid}"},
            {"text": "💛 Like", "callback_data": f"likemention:{tid}"},
            {"text": "⏭ Atla", "callback_data": f"mskip:{tid}"},
        ]]

    result = _api(env, "sendMessage", {
        "chat_id": int(env["TELEGRAM_CHAT_ID"]),
        "text": body[:4000],
        "reply_markup": {"inline_keyboard": rows},
        "disable_web_page_preview": False,  # show preview of original tweet
    })
    msg_id = result.get("message_id")
    if msg_id is not None:
        # Register as a special "incoming-reply" pending entry
        draft_pending = {
            "id": f"mention-{tid}",
            "kind": "incoming-reply",
            "tweet_id": tid,
            "target_url": url,
            "author": author,
            "text": san["clean"],
            "ai_draft": ai_draft,  # carried for aireply callback
            "lang": lang,
        }
        _register_pending(msg_id, draft_pending)
    print(json.dumps({"mention_tid": tid, "message_id": msg_id,
                      "ai_drafted": bool(ai_draft)}))


def cmd_daemon(idle_timeout: int = 50) -> None:
    """Long-running poller that processes approval callbacks for any pending draft.

    Drafts created via `draft` are persisted to telegram-pending.json keyed by
    message_id. When user presses Approve/Skip or replies (= edit), we look up
    the original draft and queue it (approve/edit) or drop it (skip).

    Designed to run forever under systemd. SIGINT/SIGTERM stops cleanly.

    State file lifecycle:
      - draft sent → pending[message_id] = {draft_id, draft, registered_at}
      - approve/edit → _queue_draft(...) + remove pending entry
      - skip → remove pending entry
    """
    import signal
    env = _load_env()
    state = _load_state()
    stop = {"flag": False}

    def _handler(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    sys.stderr.write(f"[daemon] started, polling every ~{idle_timeout}s\n")
    sys.stderr.flush()

    while not stop["flag"]:
        try:
            updates = _api(env, "getUpdates", {
                "timeout": idle_timeout,
                "offset": state["last_update_id"] + 1,
                "limit": 30,
            }, timeout=idle_timeout + 10)
        except Exception as e:
            sys.stderr.write(f"[daemon] poll error: {e}\n")
            time.sleep(5)
            continue

        if updates:
            state["last_update_id"] = max(u["update_id"] for u in updates)
            _save_state(state)

        for u in updates:
            try:
                _process_update(env, u)
            except Exception as e:
                sys.stderr.write(f"[daemon] update process error: {e}\n")

    sys.stderr.write("[daemon] stopped cleanly\n")


def _process_update(env: dict, u: dict) -> None:
    """Handle one Telegram update against the pending-drafts state file."""
    msg = u.get("message") or u.get("edited_message") or {}

    # /stop or /iptal — abort EVERY pending draft
    if msg.get("text", "").strip().lower() in ("/stop", "/iptal", "/dur"):
        pending = _load_pending()
        if pending:
            _api(env, "sendMessage", {
                "chat_id": int(env["TELEGRAM_CHAT_ID"]),
                "text": f"⛔ {len(pending)} bekleyen taslak iptal edildi.",
            })
            _save_pending({})
        return

    # Reply to a pending draft/mention message
    reply_to = (msg.get("reply_to_message") or {}).get("message_id")
    if reply_to:
        rec = _resolve_pending(reply_to)
        if rec and msg.get("text"):
            new_text = msg["text"]
            d = rec.get("draft", {})
            # Strategy revision note: append to artifact, don't queue anything.
            if d.get("kind") == "strategy":
                try:
                    _append_strategy_note(d.get("strategy_id", ""), new_text)
                    _edit_msg_status(env, reply_to, "💬 Revize notu kaydedildi",
                                     suffix=f"\nnot: {new_text[:200]}")
                except Exception as e:
                    sys.stderr.write(f"[daemon] strategy note error: {e}\n")
                return
            # Weekly plan revision note
            if d.get("kind") == "weekly":
                try:
                    _append_weekly_note(d.get("week_id", ""), new_text)
                    _edit_msg_status(env, reply_to, "💬 Haftalık plan revize notu kaydedildi",
                                     suffix=f"\nnot: {new_text[:200]}")
                except Exception as e:
                    sys.stderr.write(f"[daemon] weekly note error: {e}\n")
                return
            # Incoming-reply OR engagement-proposal flow: user typed the reply
            # text we should post (target_url + author present in both kinds).
            if d.get("kind") in ("incoming-reply", "engagement-proposal"):
                tweet_text = new_text
                queue_item = {
                    "id": f"reply-to-{d.get('tweet_id')}",
                    "kind": "reply",
                    "to": d.get("target_url"),
                    "text": tweet_text,
                    "context": f"manual reply to {d.get('author')}",
                }
                try:
                    _edit_msg_status(env, reply_to, "💬 Cevap atılacak",
                                     suffix=f"\n_metin:_\n{tweet_text[:300]}")
                except Exception:
                    pass
                _queue_and_notify(env, queue_item, {"action": "approve"})
            else:
                # Standard draft-edit flow
                _edit_msg_status(env, reply_to, "✏️ Düzeltildi",
                                 suffix=f"\n_yeni metin:_\n```\n{new_text}\n```")
                _queue_and_notify(env, d, {"action": "edit", "edited_text": new_text})
        return

    cb = u.get("callback_query")
    if not cb:
        return
    cb_msg_id = (cb.get("message") or {}).get("message_id")
    data = cb.get("data", "")
    parts = data.split(":", 1)
    action = parts[0]

    rec = _resolve_pending(cb_msg_id) if cb_msg_id else None
    if not rec:
        try:
            _api(env, "answerCallbackQuery",
                 {"callback_query_id": cb["id"], "text": "stale"})
        except Exception:
            pass
        return

    # Decision logger — every callback is a learning signal
    try:
        _log_decision(action, rec.get("draft", {}))
    except Exception as e:
        sys.stderr.write(f"[daemon] decision log fail: {e}\n")

    action_tr = {
        "approve": "✅ Onaylandı",
        "skip": "⏭ Geçildi",
        "regen": "🔁 Yeni görsel üretiliyor…",
        "noimage": "📝 Görselsiz atılacak",
        "replywrite": "💬 Cevap modu — bu mesaja reply yaz",
        "likemention": "💛 Like atılıyor",
        "mskip": "⏭ Atlandı",
        "aireply": "✨ AI taslağı atılacak",
        "stratgo": "✅ Strateji onaylandı",
        "stratrev": "💬 Strateji revize — reply ile not yaz",
        "stratskip": "⏭ Strateji geçildi",
        "weekgo": "✅ Haftalık plan onaylandı",
        "weekrev": "💬 Plan revize — reply ile not yaz",
        "weekskip": "⏭ Haftalık plan geçildi",
        "trendtweet": "📝 Trend → draft hazırlanıyor",
        "trendreply": "💬 Trend reply modu — bu mesaja reply yaz",
        "trendskip": "⏭ Trend geçildi",
    }.get(action, action)
    # Best-effort ack — query may be expired ("query is too old"); don't lose the draft over it.
    try:
        _api(env, "answerCallbackQuery",
             {"callback_query_id": cb["id"], "text": action_tr})
    except Exception:
        pass

    if action == "regen":
        # Re-generate image for the same draft, post a fresh card.
        draft = rec["draft"]
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from image_gen import generate as _img_generate  # type: ignore
            img_id = f"draft-{draft['id']}-r{int(time.time())}"
            img_out = _img_generate(img_id, draft.get("image_content", ""),
                                    title=draft.get("image_title"),
                                    size=draft.get("image_size", "1080x1080"))
            draft["image_path"] = img_out["path"]
        except Exception as e:
            sys.stderr.write(f"[daemon] regen failed: {e}\n")
            _api(env, "sendMessage", {
                "chat_id": int(env["TELEGRAM_CHAT_ID"]),
                "text": f"🔴 görsel üretilemedi: {str(e)[:200]}",
                "reply_to_message_id": cb_msg_id,
            })
            # Re-register so user can try again
            _register_pending(cb_msg_id, draft)
            return
        # Edit old message status; send fresh card with new image
        try:
            _edit_msg_status(env, cb_msg_id, "🔁 Yeni görsel")
        except Exception:
            pass
        # Reissue cmd_draft pipeline manually — write temp + call cmd_draft
        import tempfile
        tmp = Path(tempfile.gettempdir()) / f"draft-{draft['id']}-{int(time.time())}.json"
        tmp.write_text(json.dumps(draft, ensure_ascii=False))
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_draft(str(tmp))
        tmp.unlink(missing_ok=True)
        return

    try:
        _edit_msg_status(env, cb_msg_id, action_tr)
    except Exception:
        pass

    d_in = rec.get("draft", {})

    # Incoming-reply card actions
    if action == "aireply":
        ai_text = d_in.get("ai_draft", "").strip()
        if not ai_text:
            try:
                _api(env, "sendMessage", {
                    "chat_id": int(env["TELEGRAM_CHAT_ID"]),
                    "text": "🔴 AI taslağı boş — manuel yaz veya like at.",
                    "reply_to_message_id": cb_msg_id,
                })
            except Exception:
                pass
            _register_pending(cb_msg_id, d_in)
            return
        try:
            _edit_msg_status(env, cb_msg_id, "✨ AI taslağı atılacak",
                             suffix=f"\n_metin:_\n{ai_text[:300]}")
        except Exception:
            pass
        reply_item = {
            "id": f"aireply-to-{d_in.get('tweet_id')}",
            "kind": "reply",
            "to": d_in.get("target_url"),
            "text": ai_text,
            "context": f"AI draft reply to {d_in.get('author')}",
        }
        _queue_and_notify(env, reply_item, {"action": "approve"})
        return

    if action == "replywrite":
        # User must now reply to message — re-register so reply_to handler can fire
        _register_pending(cb_msg_id, d_in)
        return
    if action == "likemention":
        like_item = {
            "id": f"like-{d_in.get('tweet_id')}",
            "kind": "like",
            "to": d_in.get("target_url"),
            "text": "",
            "context": f"like to {d_in.get('author')}",
        }
        _queue_and_notify(env, like_item, {"action": "approve"})
        return
    if action == "mskip":
        return  # already removed from pending

    # Strategy card callbacks (Faz A daily_strategist) — flip artifact status,
    # optionally compile into a draft skeleton for the normal pipeline.
    if action in ("stratgo", "stratskip"):
        strategy_id = parts[1] if len(parts) > 1 else d_in.get("strategy_id", "")
        try:
            _handle_strategy_decision(env, strategy_id, action, cb_msg_id)
        except Exception as e:
            sys.stderr.write(f"[daemon] strategy decision error: {e}\n")
        return
    if action == "stratrev":
        # Keep the strategy in pending so the reply_to handler can capture the user's revision note.
        _register_pending(cb_msg_id, d_in)
        return

    # Weekly plan callbacks (Faz A weekly_review) — compile 7 strategy artifacts on approve.
    if action in ("weekgo", "weekskip"):
        week_id = parts[1] if len(parts) > 1 else d_in.get("week_id", "")
        try:
            _handle_weekly_decision(env, week_id, action, cb_msg_id)
        except Exception as e:
            sys.stderr.write(f"[daemon] weekly decision error: {e}\n")
        return
    if action == "weekrev":
        _register_pending(cb_msg_id, d_in)
        return

    # Trend listener callbacks
    if action == "trendtweet":
        # Compile trend selection into a draft skeleton and run through cmd_draft pipeline.
        sel = d_in.get("selection", {})
        if not sel:
            _api(env, "sendMessage", {
                "chat_id": int(env["TELEGRAM_CHAT_ID"]),
                "text": "⚠️ Trend kaybı — selection bulunamadı.",
            })
            return
        try:
            _handle_trend_tweet(env, sel, d_in.get("id", ""))
        except Exception as e:
            sys.stderr.write(f"[daemon] trend tweet error: {e}\n")
        return
    if action == "trendreply":
        # User must reply to the message with their reply text. Re-register pending
        # but as engagement-proposal so the reply_to handler treats it as a reply.
        sel = d_in.get("selection", {})
        url = sel.get("url", "")
        if "x.com" in url or "twitter.com" in url:
            tweet_id = url.rstrip("/").split("/")[-1] if "/status/" in url else None
            if tweet_id:
                _register_pending(cb_msg_id, {
                    "id": d_in.get("id"),
                    "kind": "engagement-proposal",
                    "tweet_id": tweet_id,
                    "target_url": url,
                    "author": "trend",
                })
                return
        # Fallback: just re-register the trend
        _register_pending(cb_msg_id, d_in)
        return
    if action == "trendskip":
        return  # already removed from pending

    if action == "approve":
        _queue_and_notify(env, d_in, {"action": "approve"})
    elif action == "noimage":
        d = dict(d_in)
        d.pop("image_path", None)
        d.pop("image_content", None)
        _queue_and_notify(env, d, {"action": "approve"})
    # skip = nothing to queue


_STRATEGY_DIR = _DATA / "state" / "strategy"


def _load_strategy(strategy_id: str) -> tuple[Path, dict] | tuple[None, None]:
    if not strategy_id:
        return None, None
    p = _STRATEGY_DIR / f"{strategy_id}.json"
    if not p.exists():
        return None, None
    try:
        return p, json.loads(p.read_text())
    except (OSError, ValueError):
        return None, None


def _save_strategy(path: Path, artifact: dict) -> None:
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))


def _append_strategy_note(strategy_id: str, note: str) -> None:
    path, artifact = _load_strategy(strategy_id)
    if not path:
        return
    notes = artifact.setdefault("revision_notes", [])
    notes.append({"at": int(time.time()), "note": note})
    artifact["approval_status"] = "revision_requested"
    _save_strategy(path, artifact)


def _strategy_to_draft(strategy_id: str, artifact: dict) -> dict | None:
    """Compile strategy artifact recommendation into a draft skeleton ready for cmd_draft."""
    rec = artifact.get("recommendation") or {}
    if not rec or rec.get("_error"):
        return None
    hook = rec.get("hook", "").strip()
    body = rec.get("body_outline", "").strip()
    reply_bait = rec.get("reply_bait", "").strip()
    if body and body != "same as hook":
        text = f"{hook}\n\n{body}\n\n{reply_bait}".strip()
    else:
        text = f"{hook}\n\n{reply_bait}".strip() if reply_bait else hook
    image = rec.get("image") or {}
    draft = {
        "id": f"strat-{strategy_id}",
        "kind": "tweet",
        "to": None,
        "text": text,
        "context": rec.get("reasoning", ""),
        "pillar": rec.get("pillar"),
        "format": rec.get("format"),
        "post_time_tr": rec.get("post_time_tr"),
        "reply_bait": reply_bait,
        "source": "daily_strategist",
        "strategy_id": strategy_id,
    }
    if image.get("needed"):
        draft["image_content"] = image.get("concept", "")
        draft["image_title"] = (rec.get("pillar") or "cdpilot")[:40]
    if rec.get("url_in_reply"):
        draft["followup_text"] = rec["url_in_reply"]
    return draft


def _handle_strategy_decision(env: dict, strategy_id: str, action: str, cb_msg_id: int) -> None:
    path, artifact = _load_strategy(strategy_id)
    if not path:
        _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": f"⚠️ Strateji bulunamadı: {strategy_id}",
        })
        return

    if action == "stratskip":
        artifact["approval_status"] = "skipped"
        artifact["decided_at"] = int(time.time())
        _save_strategy(path, artifact)
        return

    # stratgo — approve + compile to draft skeleton
    artifact["approval_status"] = "approved"
    artifact["decided_at"] = int(time.time())
    _save_strategy(path, artifact)

    draft = _strategy_to_draft(strategy_id, artifact)
    if not draft:
        _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": f"⚠️ Strateji {strategy_id} taslağa derlenemedi (recommendation eksik).",
        })
        return

    drafts_dir = _DATA / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    draft_path = drafts_dir / f"{draft['id']}.json"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2))

    # Send the draft through the normal cmd_draft pipeline so user can approve/regen image.
    try:
        cmd_draft(str(draft_path))
    except Exception as e:
        _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": f"🔴 Strateji taslağı gönderilemedi: {str(e)[:200]}",
        })


_DECISIONS_DIR = _DATA / "audit"


def _log_decision(action: str, draft: dict) -> None:
    """Append every user decision to audit/decisions-YYYY-MM-DD.jsonl.

    Powers the decision_learner: builds handle/pillar/hour approval patterns,
    then adaptive thresholds in engagement_scanner. Without this, the system
    can't learn from user behavior.
    """
    if not draft:
        return
    _DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    out = _DECISIONS_DIR / f"decisions-{today}.jsonl"

    # Approval semantics — group by intent so learner can compute approval_rate
    approve_actions = {"approve", "aireply", "likemention", "stratgo", "weekgo",
                       "trendtweet", "noimage"}
    skip_actions = {"skip", "mskip", "stratskip", "weekskip", "trendskip"}
    revise_actions = {"regen", "stratrev", "weekrev", "replywrite", "trendreply"}
    decision = ("approve" if action in approve_actions
                else "skip" if action in skip_actions
                else "revise" if action in revise_actions
                else "other")

    entry = {
        "ts": int(time.time()),
        "hour": time.strftime("%H"),
        "action": action,
        "decision": decision,
        "draft_id": draft.get("id"),
        "kind": draft.get("kind"),
        "pillar": draft.get("pillar"),
        "handle": draft.get("author") or draft.get("handle"),
        "source": draft.get("source"),
        "tweet_id": draft.get("tweet_id"),
        "ai_drafted": draft.get("ai_drafted", False),
    }
    with open(out, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


_WEEKLY_DIR = _DATA / "state" / "weekly"


def _load_weekly(week_id: str) -> tuple[Path, dict] | tuple[None, None]:
    if not week_id:
        return None, None
    p = _WEEKLY_DIR / f"{week_id}.json"
    if not p.exists():
        return None, None
    try:
        return p, json.loads(p.read_text())
    except (OSError, ValueError):
        return None, None


def _save_weekly(path: Path, artifact: dict) -> None:
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))


def _append_weekly_note(week_id: str, note: str) -> None:
    path, artifact = _load_weekly(week_id)
    if not path:
        return
    notes = artifact.setdefault("revision_notes", [])
    notes.append({"at": int(time.time()), "note": note})
    artifact["approval_status"] = "revision_requested"
    _save_weekly(path, artifact)


def _weekly_to_strategy_artifact(day_plan: dict, week_id: str) -> dict:
    """Convert one weekly_plan entry to a daily strategy artifact (pre-approved).

    The daily_strategist won't re-call Claude when an artifact exists (unless
    CDPILOT_STRATEGIST_FORCE=1). Instead it'll pick this up and send the card.
    """
    return {
        "id": day_plan.get("date"),
        "generated_at": int(time.time()),
        "source": "weekly_review",
        "week_id": week_id,
        "context": {"derived_from_weekly": True},
        "recommendation": {
            "pillar": day_plan.get("pillar"),
            "format": day_plan.get("format"),
            "post_time_tr": day_plan.get("post_time_tr"),
            "hook": day_plan.get("hook_seed", ""),
            "body_outline": "same as hook",
            "reply_bait": "",  # daily strategist or user fills this
            "image": {"needed": day_plan.get("format") == "image",
                      "concept": "Field Notebook style: " + (day_plan.get("pillar", "") or "")},
            "url_in_reply": None,
            "reasoning": day_plan.get("reasoning", ""),
        },
        "approval_status": "weekly_preapproved",
    }


def _handle_weekly_decision(env: dict, week_id: str, action: str, cb_msg_id: int) -> None:
    path, artifact = _load_weekly(week_id)
    if not path:
        _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": f"⚠️ Haftalık plan bulunamadı: {week_id}",
        })
        return

    if action == "weekskip":
        artifact["approval_status"] = "skipped"
        artifact["decided_at"] = int(time.time())
        _save_weekly(path, artifact)
        return

    # weekgo — approve + write 7 strategy artifacts for next week's daily slots
    plan = artifact.get("plan", {})
    days = plan.get("next_week_plan", []) if isinstance(plan, dict) else []
    if not days:
        _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": f"⚠️ Haftalık plan boş: {week_id} — derleme atlandı.",
        })
        return

    strategy_dir = _DATA / "state" / "strategy"
    strategy_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for d in days:
        date_str = d.get("date")
        if not date_str:
            continue
        target = strategy_dir / f"{date_str}.json"
        # Don't overwrite if user already approved a strategy for that day
        if target.exists():
            existing = json.loads(target.read_text())
            if existing.get("approval_status") in ("approved", "awaiting_telegram"):
                continue
        target.write_text(json.dumps(
            _weekly_to_strategy_artifact(d, week_id), ensure_ascii=False, indent=2))
        written += 1

    artifact["approval_status"] = "approved"
    artifact["decided_at"] = int(time.time())
    artifact["compiled_strategies"] = written
    _save_weekly(path, artifact)

    try:
        _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": f"✅ Haftalık plan onaylandı. {written}/7 strateji günlük olarak hazırlandı.\n"
                    f"Her sabah 08:30'da o günün kartı Telegram'a düşecek.",
        })
    except Exception:
        pass


def _handle_trend_tweet(env: dict, sel: dict, source_id: str) -> None:
    """Compile a trend selection into a draft skeleton and push through cmd_draft."""
    angle = sel.get("angle", "").strip()
    title = sel.get("title", "").strip()
    url = sel.get("url", "")
    if not angle:
        _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": "⚠️ Trend angle boş — draft üretilemedi.",
        })
        return

    # Body: just the angle. Reply-bait & URL handling left to user/strategist polish.
    body = angle
    draft = {
        "id": f"trend-{source_id}",
        "kind": "tweet",
        "to": None,
        "text": body,
        "context": f"trend listener seed — {sel.get('source', '?')}: {title[:120]}",
        "pillar": sel.get("pillar"),
        "format": sel.get("format_hint"),
        "source": "trend_listener",
        "source_url": url,
    }
    if url and not url.startswith("https://x.com"):
        # External link → goes to followup reply per URL-in-reply experiment
        draft["followup_text"] = url

    drafts_dir = _DATA / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    draft_path = drafts_dir / f"{draft['id']}.json"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2))

    try:
        cmd_draft(str(draft_path))
    except Exception as e:
        _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": f"🔴 Trend taslağı gönderilemedi: {str(e)[:200]}",
        })


def _queue_and_notify(env: dict, draft: dict, decision: dict) -> None:
    """Queue an approved/edited draft, notify Telegram with the scheduled time."""
    qp = _queue_draft(draft, decision, idx=0)
    try:
        sched_ts = json.loads(qp.read_text())["scheduled_time"]
        sched_iso = time.strftime("%Y-%m-%d %H:%M", time.localtime(sched_ts))
    except Exception:
        sched_iso = "?"
    try:
        _api(env, "sendMessage", {
            "chat_id": int(env["TELEGRAM_CHAT_ID"]),
            "text": f"📥 `{draft['id']}` kuyrukta — planlanan: *{sched_iso}*",
            "parse_mode": "Markdown",
        })
    except Exception:
        pass


def main() -> None:
    p = argparse.ArgumentParser(description="Telegram bridge for cdpilot Twitter approvals")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="auto-detect chat_id from /start")
    s_send = sub.add_parser("send", help="send a plain message")
    s_send.add_argument("text")
    s_draft = sub.add_parser("draft", help="send a SINGLE draft (JSON file)")
    s_draft.add_argument("json_path")
    s_seq = sub.add_parser("batch-seq", help="send N drafts sequentially, wait on each (orchestrator)")
    s_seq.add_argument("json_path")
    s_wait1 = sub.add_parser("wait-decision", help="wait for one draft's decision (approve/skip/edit)")
    s_wait1.add_argument("draft_id")
    s_wait1.add_argument("message_id", type=int)
    s_wait1.add_argument("--timeout", type=int, default=7200)
    s_poll = sub.add_parser("poll", help="one-shot getUpdates dump")
    s_poll.add_argument("--timeout", type=int, default=1)
    s_daemon = sub.add_parser("daemon", help="long-running approval-loop daemon")
    s_daemon.add_argument("--idle-timeout", type=int, default=50)
    s_inc = sub.add_parser("incoming-reply", help="post incoming-reply decision card")
    s_inc.add_argument("json_path", help="path to inbox/<id>.json")
    args = p.parse_args()
    if args.cmd == "setup":
        cmd_setup()
    elif args.cmd == "send":
        cmd_send(args.text)
    elif args.cmd == "draft":
        cmd_draft(args.json_path)
    elif args.cmd == "batch-seq":
        cmd_batch_seq(args.json_path)
    elif args.cmd == "wait-decision":
        cmd_wait_decision(args.draft_id, args.message_id, args.timeout)
    elif args.cmd == "poll":
        cmd_poll(args.timeout)
    elif args.cmd == "daemon":
        cmd_daemon(args.idle_timeout)
    elif args.cmd == "incoming-reply":
        cmd_incoming_reply(args.json_path)


if __name__ == "__main__":
    main()
