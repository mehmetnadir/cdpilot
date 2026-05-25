#!/usr/bin/env python3
"""trend_listener.py — Faz A #3.

Günlük 09:00 ve 17:00 cycle'da çalışır. discovery_scan çıktısını okur
(HN/GitHub/arXiv/X search), srv21 Claude CLI ile bizim niş için en relevant
3 trend'i seçer, her birine "ne yapalım" önerisiyle Telegram'a butonlu kart atar.

Çıktı:
  ~/cdpilot-twitter-data/state/trends/YYYY-MM-DD-HH.json (trend artifact)
  Telegram'a 3 kart (her trend için):
    📝 Tweet at → strategist seed olarak ekle
    💬 Tartışmaya katıl → reply drafter ile cevap üret (X search trendi ise)
    ⏭ Geç

DOCTRINE.md §3 Faz A item 3.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
XBOT = Path(__file__).resolve().parent.parent
DISCOVERIES = DATA / "discoveries"
POSTED = DATA / "posted"
STATE = DATA / "state"
TRENDS_DIR = STATE / "trends"
LOG_FILE = DATA / "logs" / "trend.log"

CLAUDE_BIN = os.environ.get("CDPILOT_CLAUDE_BIN", "claude")
MODEL = os.environ.get("CDPILOT_TREND_MODEL", "claude-sonnet-4-6")
MAX_CANDIDATES = int(os.environ.get("CDPILOT_TREND_MAX", "3"))

SYSTEM_PROMPT = """You are the trend listener for @cdpilot_dev (cdpilot — zero-dep CDP
browser automation CLI). Audience: browser automation devs, anti-bot researchers,
AI agent builders, indie OSS dev tooling enthusiasts.

YOUR JOB:
Read today's raw discovery feed (HN top stories, GitHub trending, arXiv papers,
X niche search results). Pick the TOP 3 items that are MOST RELEVANT to our niche
AND most likely to drive engagement IF we tweet/reply.

OUTPUT FORMAT (strict JSON, no markdown, no preamble):
{
  "selections": [
    {
      "source": "hn|github|arxiv|x_search",
      "title": "the item's title (from feed)",
      "url": "the canonical URL (from feed)",
      "why_now": "1 sentence: why this is worth reacting to today",
      "suggested_action": "tweet|reply|both",
      "angle": "the specific angle/take we should use (1-2 sentences)",
      "format_hint": "single|thread|quote",
      "pillar": "cdpilot|llm-tips|gem-repos|behind-the-scenes",
      "risk_flag": null | "controversial|outdated|low_overlap"
    },
    ... (exactly 3)
  ]
}

RULES:
1. Exactly 3 selections. Diverse sources when possible.
2. If a source is empty in the feed → don't fabricate; pick from non-empty ones.
3. Skip items that are obvious marketing, generic AI hype, or unrelated.
4. Prefer items where we have a SPECIFIC technical angle (raw CDP perspective,
   stealth/anti-bot insight, OSS dev tooling take), not generic commentary.
5. For X search results suggesting a reply, set suggested_action="reply" + angle
   should be the actual reply tone (cool peer voice, max 200 chars body).
6. risk_flag: warn if the topic is politically hot, technically wrong, or low
   audience-overlap. NEVER pick items requiring crisis/controversy management.
7. angle MUST be specific — no "share thoughts" or "join the conversation". Tell
   me exactly what the tweet would say (the substance, not the form).

Be selective. 3 high-signal beats 10 mediocre."""


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _load_json(p: Path) -> dict | list:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _latest_discovery() -> dict:
    """Find the most recent discovery_scan output."""
    if not DISCOVERIES.exists():
        return {}
    files = sorted(DISCOVERIES.glob("*.json"))[-1:]
    if not files:
        return {}
    data = _load_json(files[0])
    return data if isinstance(data, dict) else {}


def _recent_posted_urls(days: int = 7) -> set[str]:
    """URLs we've already tweeted about — skip them to avoid duplicate coverage."""
    cutoff = time.time() - days * 86400
    out: set[str] = set()
    if not POSTED.exists():
        return out
    for f in sorted(POSTED.glob("*.json")):
        item = _load_json(f)
        if not isinstance(item, dict) or item.get("posted_at", 0) < cutoff:
            continue
        for key in ("followup_text", "url", "source_url"):
            v = item.get(key)
            if v and isinstance(v, str) and v.startswith("http"):
                out.add(v)
        text = item.get("text") or ""
        for tok in text.split():
            if tok.startswith("http"):
                out.add(tok.rstrip(".,)"))
    return out


def build_context() -> dict:
    disc = _latest_discovery()
    seen = _recent_posted_urls(days=7)
    # discovery_scan structure: typically {"hn":[...], "github":[...], "arxiv":[...], "x_search":[...]}
    filtered = {}
    for src, items in disc.items():
        if src.startswith("_") or not isinstance(items, list):
            continue
        kept = []
        for it in items:
            if isinstance(it, dict):
                url = it.get("url") or ""
                if url in seen:
                    continue
                kept.append({
                    "title": it.get("title") or it.get("text", "")[:120],
                    "url": url,
                    "score": it.get("score") or it.get("favorite_count") or it.get("stars"),
                    "author": it.get("by") or it.get("author") or it.get("handle"),
                })
        filtered[src] = kept[:8]  # cap per source so prompt stays small
    return {
        "scan_time": disc.get("_meta", {}).get("generated_at") if isinstance(disc.get("_meta"), dict) else None,
        "today": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sources": filtered,
        "skip_urls_count": len(seen),
    }


def _claude_available() -> bool:
    return shutil.which(CLAUDE_BIN) is not None


def _ask_claude(context: dict, timeout: int = 180) -> dict:
    user_prompt = (
        "TREND FEED (JSON):\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        "Now pick the 3 best items as strict JSON per the schema in your system prompt. "
        "No prose, no markdown fences."
    )
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", "--model", MODEL, "--append-system-prompt", SYSTEM_PROMPT],
            input=user_prompt, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _log(f"claude CLI timeout after {timeout}s")
        return {"_error": "timeout"}
    except Exception as e:
        _log(f"claude CLI exception: {type(e).__name__}: {e}")
        return {"_error": f"{type(e).__name__}: {e}"}

    raw = (proc.stdout or "").strip()
    if proc.returncode != 0 or not raw:
        err = (proc.stderr or "")[:300]
        _log(f"claude CLI exit={proc.returncode}: {err}")
        return {"_error": f"exit={proc.returncode}", "stderr": err}

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except ValueError as e:
        _log(f"claude output not valid JSON: {e} :: {cleaned[:200]}")
        return {"_error": "invalid_json", "raw": cleaned[:500]}


def _render_card(sel: dict, idx: int, total: int) -> str:
    source_tr = {
        "hn": "Hacker News",
        "github": "GitHub Trending",
        "arxiv": "arXiv",
        "x_search": "X araması",
    }.get(sel.get("source"), sel.get("source", "?"))
    action_tr = {
        "tweet": "Tweet at",
        "reply": "Cevap yaz",
        "both": "Tweet + cevap",
    }.get(sel.get("suggested_action"), "?")
    risk = sel.get("risk_flag")
    risk_line = f"⚠️ Risk: {risk}\n" if risk else ""
    return (
        f"🔥 TREND {idx}/{total} — {source_tr}\n"
        f"📰 {sel.get('title', '(başlık yok)')}\n"
        f"🔗 {sel.get('url', '(URL yok)')}\n\n"
        f"⏰ Neden şimdi: {sel.get('why_now', '(yok)')}\n"
        f"🎯 Önerilen aksiyon: {action_tr}  ·  Pillar: {sel.get('pillar', '?')}  ·  Format: {sel.get('format_hint', '?')}\n"
        f"💡 Açı:\n{sel.get('angle', '(yok)')}\n"
        f"{risk_line}\n"
        f"👇 Karar ver:"
    )


def _send_card(sel: dict, idx: int, total: int, trend_id: str) -> dict:
    sys.path.insert(0, str(Path(__file__).parent))
    import telegram_bridge as tb  # type: ignore

    env = tb._load_env()
    if not env.get("TELEGRAM_CHAT_ID"):
        return {"_error": "no_chat_id"}

    action = sel.get("suggested_action", "tweet")
    cb_id = f"{trend_id}-{idx}"
    buttons = [
        [{"text": "📝 Tweet at", "callback_data": f"trendtweet:{cb_id}"}],
    ]
    if action in ("reply", "both") and sel.get("url", "").startswith("https://x.com"):
        buttons[0].insert(0, {"text": "💬 Cevap yaz", "callback_data": f"trendreply:{cb_id}"})
    buttons.append([{"text": "⏭ Geç", "callback_data": f"trendskip:{cb_id}"}])

    card = _render_card(sel, idx, total)
    result = tb._api(env, "sendMessage", {
        "chat_id": int(env["TELEGRAM_CHAT_ID"]),
        "text": card,
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": buttons},
    })
    msg_id = result.get("message_id")
    if msg_id:
        tb._register_pending(msg_id, {
            "id": f"trend-{cb_id}",
            "kind": "trend",
            "trend_id": trend_id,
            "selection": sel,
        })
    return result


def run(send: bool = True) -> dict:
    stamp = datetime.now().strftime("%Y-%m-%d-%H")
    TRENDS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TRENDS_DIR / f"{stamp}.json"

    context = build_context()
    total_items = sum(len(v) for v in context.get("sources", {}).values() if isinstance(v, list))
    if total_items == 0:
        _log("no discovery items found — skipping trend listener")
        return {"status": "no_feed"}

    if not _claude_available():
        artifact = {"id": stamp, "generated_at": int(time.time()),
                    "context": context, "selections": None, "approval_status": "no_claude"}
        out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        return {"status": "no_claude", "path": str(out_path)}

    result = _ask_claude(context)
    artifact = {
        "id": stamp,
        "generated_at": int(time.time()),
        "context_summary": {k: len(v) for k, v in context.get("sources", {}).items()},
        "selections": result.get("selections", []) if isinstance(result, dict) else [],
        "claude_error": result.get("_error"),
        "model": MODEL,
    }
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
    _log(f"wrote trend artifact {out_path}")

    if result.get("_error"):
        return {"status": "claude_error", "path": str(out_path), "error": result["_error"]}

    selections = (result.get("selections") or [])[:MAX_CANDIDATES]
    if send:
        sent = 0
        for i, sel in enumerate(selections, 1):
            try:
                _send_card(sel, i, len(selections), stamp)
                sent += 1
                time.sleep(1.2)  # spacing so Telegram doesn't rate-limit
            except Exception as e:
                _log(f"send card {i} failed: {e}")
        return {"status": "ok", "path": str(out_path), "sent": sent, "total": len(selections)}

    return {"status": "no_send", "path": str(out_path), "selections": len(selections)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--no-send", action="store_true")
    p.add_argument("--print-context", action="store_true")
    args = p.parse_args()

    if args.print_context:
        print(json.dumps(build_context(), ensure_ascii=False, indent=2))
        return

    result = run(send=not args.no_send)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
