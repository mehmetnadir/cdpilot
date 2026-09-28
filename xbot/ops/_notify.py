"""_notify.py — the one phone-push path for the xbot (ntfy, no Telegram).

Alarms went to Telegram. Between 2026-09-15 and 09-21 the sends failed with
"Network is unreachable", and the ones that did land sat in a chat nobody
reads — so a false crisis freeze kept the account silent for 11 days while
the sentinel reported the alarm as delivered. An alarm is only as good as
the channel someone actually looks at. Since 2026-09-28 routine activity
(replies sent, likes, mentions, pain-hunter hits, DMs) goes through ntfy too.

Two channels, so alarms are never drowned by routine noise:
  - alarm=True  → CDPILOT_NTFY_CHANNEL          (default `bekci`)
  - alarm=False → CDPILOT_NTFY_ROUTINE_CHANNEL  (default `cdpilot-x`)

Routine pushes are rate-limited: once BURST_MAX pushes went out inside
BURST_WINDOW_S, further ones are held and later collapsed into ONE digest
(flushed by the next notify() or flush_digest() call that finds room — the
poster runs every 5 minutes, so a held digest never waits long). Alarms are
never held.

Delivery: ntfy's JSON publish API on the same servers + token `bildir` uses
(~/.config/ntfy/servers + token; NTFY_URL / NTFY_TOKEN override), because
`bildir` cannot pass Actions. If every server fails, `bildir` itself is the
fallback (it also knows the ntfy.sh last-resort topic). The token is never
logged or returned. Never raises: a broken push path must not take the
caller down with it.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import bot_home  # noqa: E402

BILDIR = os.environ.get("CDPILOT_BILDIR", "bildir")
CHANNEL = os.environ.get("CDPILOT_NTFY_CHANNEL", "bekci")
ROUTINE_CHANNEL = os.environ.get("CDPILOT_NTFY_ROUTINE_CHANNEL", "cdpilot-x")
TITLE = "cdpilot xbot"
HANDLE = os.environ.get("CDPILOT_HANDLE", "cdpilot_dev")

BURST_MAX = int(os.environ.get("CDPILOT_NTFY_BURST_MAX", "5"))
BURST_WINDOW_S = int(os.environ.get("CDPILOT_NTFY_BURST_WINDOW_S", "600"))
HELD_CAP = 60  # held items kept for the digest; older ones are only counted
# ntfy's message-size-limit is 4096 BYTES; past it the text turns into an
# attachment. Budget = 4096 - title bytes - JSON/field headroom.
NTFY_MAX_BYTES = 4096
JSON_HEADROOM_BYTES = 256

PRIORITIES = {"dusuk": 2, "normal": 3, "yuksek": 4, "acil": 5}
_PRIORITY_NAMES = {v: k for k, v in PRIORITIES.items()}


# ── URL helpers ──

def status_url(tweet_id: str | int, user: str | None = None) -> str:
    """https://x.com/<user>/status/<id>; `i` works for any tweet id."""
    return f"https://x.com/{(user or 'i').lstrip('@')}/status/{tweet_id}"


def profile_url(handle: str) -> str:
    return f"https://x.com/{handle.lstrip('@')}"


def compose_url(text: str, in_reply_to: str | None = None) -> str:
    """X web-intent composer, prefilled — tapping it is how Nadir approves a
    held post without Telegram: X opens with the draft, he presses Post."""
    params = {"text": text}
    if in_reply_to:
        params["in_reply_to"] = in_reply_to
    return "https://x.com/intent/post?" + urllib.parse.urlencode(params)


def x_url(target: str | int | None) -> str | None:
    """Best link for a queue `to` value: URL as-is, bare id → status,
    @handle / handle → profile."""
    if target is None:
        return None
    t = str(target).strip()
    if not t:
        return None
    if t.startswith(("http://", "https://")):
        return t
    if t.isdigit():
        return status_url(t)
    h = t.lstrip("@")
    if h and len(h) <= 15 and all(c.isalnum() or c == "_" for c in h):
        return profile_url(h)
    return None


# ── payload ──

def _priority_value(priority: str | int) -> int:
    if isinstance(priority, int):
        return max(1, min(5, priority))
    return PRIORITIES.get(str(priority), 3)


def _message_budget(title: str) -> int:
    return max(512, NTFY_MAX_BYTES - len(title.encode("utf-8")) - JSON_HEADROOM_BYTES)


def trim_utf8(text: str, max_bytes: int) -> str:
    """Cut `text` so its JSON-escaped UTF-8 form fits `max_bytes`, never
    splitting a multi-byte character (ç, ş, ğ, emoji…); adds "…" if cut."""
    def size(t: str) -> int:
        return len(json.dumps(t, ensure_ascii=False).encode("utf-8")) - 2

    if size(text) <= max_bytes:
        return text
    ell = "…"
    limit = max_bytes - len(ell.encode("utf-8"))
    # raw byte cut first; errors="ignore" drops a half-cut trailing char
    out = text.encode("utf-8")[:max(0, limit)].decode("utf-8", errors="ignore")
    while out and size(out) > limit:  # escapes (\n, \") can still overflow
        out = out[:-max(1, (size(out) - limit) // 2)]
    return out + ell


def build_payload(title: str, text: str, *, url: str | None = None,
                  priority: str | int = "normal", tags: list[str] | None = None,
                  alarm: bool = False, actions: list[dict] | None = None,
                  open_label: str = "X'te aç") -> dict:
    """ntfy JSON-publish body. `url` becomes Click (tap opens it) and, when it
    is an X link, also an "X'te aç" view button. Max 3 actions (ntfy limit)."""
    msg = trim_utf8((text or "").strip() or title, _message_budget(title))
    payload: dict = {
        "topic": CHANNEL if alarm else ROUTINE_CHANNEL,
        "title": title,
        "message": msg,
        "priority": _priority_value(priority),
    }
    if tags:
        payload["tags"] = [t for t in tags if t]
    acts: list[dict] = []
    if url:
        payload["click"] = url
        if "x.com/" in url or "twitter.com/" in url:
            acts.append({"action": "view", "label": open_label, "url": url})
    for a in actions or []:
        if a.get("url") and not any(x.get("url") == a["url"] for x in acts):
            acts.append({"action": "view", "label": a.get("label", "Aç"),
                         "url": a["url"]})
    if acts:
        payload["actions"] = acts[:3]
    return payload


# ── delivery ──

def _ntfy_cfg_dir() -> Path:
    home = os.environ.get("HOME") or "/root"
    return Path(os.environ.get("CDPILOT_NTFY_CONFIG_DIR", str(Path(home) / ".config" / "ntfy")))


def _servers() -> list[str]:
    if os.environ.get("NTFY_URL"):
        return [os.environ["NTFY_URL"]]
    cfg = _ntfy_cfg_dir()
    for name in ("servers", "server"):
        try:
            lines = (cfg / name).read_text().splitlines()
        except OSError:
            continue
        out = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
        if out:
            return out
    return []


def _token() -> str:
    if os.environ.get("NTFY_TOKEN"):
        return os.environ["NTFY_TOKEN"]
    try:
        return (_ntfy_cfg_dir() / "token").read_text().strip()
    except OSError:
        return ""


def _http_publish(payload: dict) -> bool:
    body = json.dumps(payload, ensure_ascii=False).encode()
    token = _token()
    for server in _servers():
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(server.rstrip("/") + "/", data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                if 200 <= r.status < 300:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            continue  # never echo the error: some carry the request headers
    return False


def _bildir_publish(payload: dict) -> bool:
    exe = shutil.which(BILDIR)
    if not exe:
        return False
    args = [exe, payload["topic"], payload["message"], "-b", payload.get("title", TITLE),
            "-p", _PRIORITY_NAMES.get(payload.get("priority", 3), "normal")]
    if payload.get("click"):
        args += ["-t", payload["click"]]
    if payload.get("tags"):
        args += ["-e", ",".join(payload["tags"])]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=40, check=False)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _deliver(payload: dict) -> bool:
    """Send one payload. True only when a server accepted it."""
    try:
        if _http_publish(payload):
            return True
    except Exception:  # noqa: BLE001 — a push must never crash its caller
        pass
    return _bildir_publish(payload)


# ── routine burst limiter ──

def _state_path() -> Path:
    env = os.environ.get("CDPILOT_NTFY_STATE")
    return Path(env) if env else bot_home() / "state" / "ntfy-routine.json"


@contextlib.contextmanager
def _locked_state() -> Iterator[dict]:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a+") as lf:
        try:
            import fcntl
            fcntl.flock(lf, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        try:
            state = json.loads(path.read_text())
            if not isinstance(state, dict):
                raise ValueError
        except (OSError, ValueError):
            state = {}
        state.setdefault("sent", [])
        state.setdefault("held", [])
        state.setdefault("dropped", 0)
        yield state
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False))
        os.replace(tmp, path)


def _prune(state: dict, now: float) -> None:
    state["sent"] = [t for t in state["sent"] if now - float(t) < BURST_WINDOW_S]


def digest_payload(held: list[dict], dropped: int = 0) -> dict:
    n = len(held) + dropped
    lines = []
    for h in held[:12]:
        first = (h.get("text") or "").strip().splitlines()
        lines.append(f"• {h.get('title', '')}" + (f" — {first[0][:90]}" if first else ""))
    if n > len(lines):
        lines.append(f"… +{n - len(lines)} daha")
    urls = []
    for h in held:
        u = h.get("url")
        if u and u not in urls:
            urls.append(u)
    prio = max([_priority_value(h.get("priority", "normal")) for h in held] or [3])
    return build_payload(
        f"cdpilot · {n} olay (özet)", "\n".join(lines),
        url=f"https://x.com/{HANDLE}/with_replies", priority=prio, tags=["bar_chart"],
        actions=[{"label": f"{i + 1}. olay", "url": u} for i, u in enumerate(urls[:2])],
        open_label="Profil",
    )


def _flush_locked(state: dict, now: float) -> bool:
    if not state["held"] or len(state["sent"]) >= BURST_MAX:
        return False
    if _deliver(digest_payload(state["held"], state.get("dropped", 0))):
        state["held"] = []
        state["dropped"] = 0
        state["sent"].append(now)
        return True
    return False


def flush_digest(now: float | None = None) -> bool:
    """Send held routine pushes as one digest if the window has room."""
    now = time.time() if now is None else now
    try:
        with _locked_state() as st:
            _prune(st, now)
            return _flush_locked(st, now)
    except OSError:
        return False


# ── public API ──

def notify(title: str, text: str = "", *, url: str | None = None,
           priority: str | int = "normal", tags: list[str] | None = None,
           alarm: bool = False, actions: list[dict] | None = None,
           open_label: str = "X'te aç", now: float | None = None) -> bool:
    """Push one notification. Routine pushes may be held for a digest (then
    True: accepted). Alarms go out immediately. Never raises."""
    try:
        payload = build_payload(title, text, url=url, priority=priority, tags=tags,
                                alarm=alarm, actions=actions, open_label=open_label)
    except Exception:  # noqa: BLE001
        return False
    if alarm:
        return _deliver(payload)
    now = time.time() if now is None else now
    delivered: bool | None = None
    try:
        with _locked_state() as st:
            _prune(st, now)
            _flush_locked(st, now)
            if len(st["sent"]) >= BURST_MAX:
                st["held"].append({"title": title, "text": text, "url": url,
                                   "priority": priority, "ts": now})
                if len(st["held"]) > HELD_CAP:
                    st["dropped"] = st.get("dropped", 0) + len(st["held"]) - HELD_CAP
                    st["held"] = st["held"][-HELD_CAP:]
                return True
            delivered = _deliver(payload)
            if delivered:
                st["sent"].append(now)
            return delivered
    except OSError:
        # state file unusable: still deliver, but never twice
        return delivered if delivered is not None else _deliver(payload)


def _tweet_id(url: str | None) -> str | None:
    if not url or "/status/" not in url:
        return None
    tail = url.rstrip("/").split("/status/")[-1].split("?")[0].split("/")[0]
    return tail if tail.isdigit() else None


def notify_waiting(what: str, draft_text: str = "", *, reason: str = "",
                   reply_to_url: str | None = None, context_url: str | None = None,
                   compose: bool = True, priority: str = "normal") -> bool:
    """A post the bot will NOT publish on its own (original tweet, thread,
    weekly plan…). Nothing is queued; the draft stays where the caller left it.

    compose=True: Click opens X's composer prefilled with `draft_text` (as a
    reply when `reply_to_url` is given) — Nadir approves by pressing Post
    himself; no endpoint, no Telegram. The context link is a second button.
    """
    ctx = context_url or reply_to_url
    url = compose_url(draft_text, _tweet_id(reply_to_url)) if compose and draft_text \
        else ctx
    actions = [{"label": "Bağlam", "url": ctx}] if ctx and ctx != url else []
    body = "\n\n".join(x for x in (reason.strip(), draft_text.strip()) if x)
    return notify(f"Onay bekliyor: {what}", body, url=url, priority=priority,
                  tags=["hourglass"], actions=actions,
                  open_label="X'te paylaş" if compose and draft_text else "X'te aç")


def push(text: str, priority: str = "yuksek", tag: str = "warning") -> bool:
    """Legacy alarm API (sentinel, crisis_check, pain digest): alarm channel."""
    return notify(TITLE, text, priority=priority, tags=[tag], alarm=True)
