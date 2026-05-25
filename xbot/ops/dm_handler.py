#!/usr/bin/env python3
"""dm_handler.py — poll DM inbox, sanitize, draft reply via Telegram.

twikit doesn't expose inbox listing publicly, so we hit
i/api/1.1/dm/inbox_initial_state.json directly via twikit's authenticated
session (cookies + ct0 + transaction id are all already configured).

Behavior (Faz 0 strict):
  - Read-only: NEVER auto-replies. Always pushes to Telegram for manual draft.
  - Spam pattern filter: silently ignored, logged to audit
  - Crisis topic filter: pushed with red flag
  - Rate cap: max 5 new DM drafts per slot

State:
  ~/cdpilot-twitter-data/state/dm-seen.json
    {"seen_message_ids": ["1234", ...], "last_poll": 1700000000}

Audit:
  ~/cdpilot-twitter-data/audit/dm-YYYY-MM-DD.jsonl  (raw + sanitized)

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
from _sanitize import sanitize, render_flags  # type: ignore

DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
STATE_FILE = DATA / "state" / "dm-seen.json"
LOG_FILE = DATA / "logs" / "dm.log"
COOKIES = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES",
    str(DATA / "cookies" / "cdpilot_dev.json"),
))
INBOX_URL = "https://x.com/i/api/1.1/dm/inbox_initial_state.json"

SPAM_PATTERNS = re.compile(
    r"(check (out )?my (project|tool|app|new)|"
    r"dm me back|"
    r"invest in|"
    r"100x|moonshot|"
    r"buy this nft|"
    r"telegram.me/[^\s]+|"
    r"join my channel|"
    r"crypto signals)",
    re.IGNORECASE,
)

MAX_NEW_PER_SLOT = 5


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except ValueError:
            pass
    return {"seen_message_ids": [], "last_poll": 0}


def _save_state(s: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # cap seen list at 5000
    s["seen_message_ids"] = s["seen_message_ids"][-5000:]
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2))


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


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _fetch_inbox(client: Client) -> dict:
    """Use twikit's authenticated session to hit inbox endpoint."""
    # twikit's Client.get is the authenticated requests wrapper
    params = {
        "nsfw_filtering_enabled": "false",
        "filter_low_quality": "true",
        "include_quality": "all",
        "include_profile_interstitial_type": "1",
        "include_blocking": "1",
        "include_blocked_by": "1",
        "include_followed_by": "1",
        "include_want_retweets": "1",
        "include_mute_edge": "1",
        "include_can_dm": "1",
        "include_can_media_tag": "1",
        "skip_status": "1",
        "dm_secret_conversations_enabled": "false",
        "krs_registration_enabled": "true",
        "cards_platform": "Web-12",
        "include_cards": "1",
        "include_ext_alt_text": "true",
        "include_quote_count": "true",
        "include_reply_count": "1",
        "tweet_mode": "extended",
        "include_groups": "true",
        "include_inbox_timelines": "true",
        "include_ext_media_color": "true",
        "supports_reactions": "true",
    }
    resp = await client.get(INBOX_URL, params=params)
    if hasattr(resp, "json"):
        return resp.json()
    return resp  # already dict


async def main_async() -> None:
    if not COOKIES.exists():
        _log(f"cookies missing: {COOKIES}")
        return

    state = _load_state()
    seen = set(state.get("seen_message_ids", []))

    client = Client(os.environ.get("CDPILOT_TWIKIT_LANG", "en-US"))
    client.load_cookies(str(COOKIES))

    try:
        data = await _fetch_inbox(client)
    except Exception as e:
        _log(f"inbox fetch failed: {e}")
        return

    inbox = data.get("inbox_initial_state", {}) if isinstance(data, dict) else {}
    entries = inbox.get("entries", []) or []
    users = inbox.get("users", {}) or {}

    today = _today()
    audit_file = DATA / "audit" / f"dm-{today}.jsonl"
    audit_file.parent.mkdir(parents=True, exist_ok=True)

    new_count = 0
    drafted = 0
    for entry in entries:
        msg = entry.get("message")
        if not msg:
            continue
        mid = str(msg.get("id", ""))
        if not mid or mid in seen:
            continue
        seen.add(mid)
        state["seen_message_ids"].append(mid)
        new_count += 1

        sender_id = str(msg.get("message_data", {}).get("sender_id", ""))
        # skip our own outgoing DMs
        own_uid = str(inbox.get("user_id", "")) or ""
        if sender_id == own_uid:
            continue

        sender = users.get(sender_id, {}) or {}
        sender_handle = sender.get("screen_name", "?")
        sender_name = sender.get("name", sender_handle)

        text_raw = msg.get("message_data", {}).get("text", "") or ""
        san = sanitize(text_raw)

        is_spam = bool(SPAM_PATTERNS.search(text_raw))

        # audit entry
        with open(audit_file, "a") as f:
            f.write(json.dumps({
                "ts": int(time.time()),
                "mid": mid,
                "sender_id": sender_id,
                "sender_handle": sender_handle,
                "raw": text_raw[:500],
                "clean": san["clean"][:500],
                "flags": san["flags"],
                "is_spam": is_spam,
            }, ensure_ascii=False) + "\n")

        if is_spam:
            _log(f"silent-ignore spam DM mid={mid} from @{sender_handle}")
            continue

        if drafted >= MAX_NEW_PER_SLOT:
            _log(f"DM cap reached, {new_count - drafted} deferred")
            break

        # Telegram draft (taslak modu — manual cevap)
        flag_str = render_flags(san["flags"])
        msg_text = (
            f"📩 Yeni DM @{sender_handle} ({sender_name})\n"
            f"{flag_str}\n\n"
            f"📥 İçerik (sanitized):\n{san['clean'][:800]}\n\n"
            f"⚠️ Faz 0: Bot otomatik cevap yazmaz. Manuel cevap için X'i aç."
        )
        _telegram_send(msg_text)
        drafted += 1

    state["last_poll"] = int(time.time())
    _save_state(state)
    _log(f"polled inbox: {len(entries)} entries, {new_count} new, {drafted} drafted")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
