#!/usr/bin/env python3
"""daily_strategist.py — Faz A #1.

Her sabah cycle başında (08:30) çalışır. Geçen 24h KPI'yı, son 7 gün pillar
dağılımını, aktif deneyleri, tier1 sinyallerini, trend listener çıktısını
okur ve srv21 Claude CLI ile bugünün CONCRETE önerisini üretir:

  "Bugün: Pillar X, format Y, saat HH:MM TR, hook Z, görsel A,
   reply-bait '...?' ile bitir. Neden: ekosistem pillar'ı 2 gündür eksik,
   17:23 statik peak içi + audience pattern'ine uygun, görsel boost."

Çıktı:
  ~/cdpilot-twitter-data/state/strategy/YYYY-MM-DD.json (strategy artifact)
  Telegram'a karar kartı (✅ Onayla / 💬 Revize / ⏭ Geç)

DOCTRINE.md §3 Faz A item 1.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import bot_home  # noqa: E402

DATA = bot_home()
XBOT = Path(__file__).resolve().parent.parent
ANALYTICS = DATA / "analytics"
POSTED = DATA / "posted"
DRAFTS = DATA / "drafts"
DISCOVERIES = DATA / "discoveries"
STATE = DATA / "state"
STRATEGY_DIR = STATE / "strategy"
LOG_FILE = DATA / "logs" / "strategist.log"
TIER1 = XBOT / "tier1.json"
PILLARS_DOC = XBOT / "content-pillars.md"
TONE_DOC = XBOT / "reply-tone.md"
DOCTRINE = XBOT / "DOCTRINE.md"

CLAUDE_BIN = os.environ.get("CDPILOT_CLAUDE_BIN", "claude")
MODEL = os.environ.get("CDPILOT_STRATEGY_MODEL", "claude-sonnet-4-6")

DAY_NAMES_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
TRACK_BY_DAY = {
    0: "Foundations (CDP basics, raw browser primitives)",
    1: "Anti-Bot Wars (CAPTCHA, detection, stealth, vendor internals)",
    2: "Building in Public (progress, commits, design decisions)",
    3: "X/Twitter Internal (HeavyRanker, algorithm mechanics)",
    4: "Comparisons & Benchmarks (cdpilot vs Playwright/Puppeteer/Selenium)",
    5: "Tutorial (step-by-step, code snippet, practical demo)",
    6: "History & Hot Takes (browser history, contrarian claims)",
}

PILLAR_KEYS = ["cdpilot", "llm-tips", "gem-repos", "behind-the-scenes", "teaser"]
PILLAR_TARGET = {
    "cdpilot": 0.35,
    "llm-tips": 0.25,
    "gem-repos": 0.20,
    "behind-the-scenes": 0.10,
    "teaser": 0.10,
}

SYSTEM_PROMPT = """You are the daily strategist for the @cdpilot_dev Twitter/X account.
Identity: cool peer voice, technical credibility, never helpful-bot, never marketing-speak.

cdpilot is an open-source CDP-based browser automation CLI (zero deps, stealth +
adaptive escalation, v0.8.0). Audience: dev community — browser automation,
anti-bot researchers, AI agent builders.

YOUR JOB:
Read the context blob (KPI from last 24h, pillar balance over last 7 days,
active experiments, today's weekly track, current trend candidates). Produce
exactly ONE concrete recommendation for today's primary tweet.

OUTPUT FORMAT (strict JSON, no markdown, no preamble):
{
  "pillar": "cdpilot|llm-tips|gem-repos|behind-the-scenes|teaser",
  "format": "single|thread|image|quote",
  "post_time_tr": "HH:MM",
  "hook": "the opening 1-2 sentences exactly as they should appear",
  "body_outline": "concise outline of remaining content (or 'same as hook' for zinger)",
  "reply_bait": "the closing question / provocation, max 80 chars, ends the tweet",
  "image": {"needed": true|false, "concept": "Field Notebook style: <subject>"},
  "url_in_reply": null | "the URL to post in a followup reply (NEVER in body)",
  "reasoning": "3-5 sentences: WHY this pillar, WHY this time, WHY this format — backed by KPI/balance/experiment evidence from the context"
}

HARD RULES:
1. Time MUST be in Istanbul hot zones: 13:00-15:00, 17:00-19:00, or 21:00-23:00.
   Never :00 minutes — pick :07, :14, :23, :37, :43, :51 etc.
2. Pillar choice MUST address the worst-underrepresented pillar in the last 7 days
   UNLESS the weekly track for today (Mon=Foundations, Tue=Anti-Bot, etc.) overrides.
3. If a hook is reused from posted/* within last 30 days → reject, pick another angle.
4. tweet length (hook + body) MUST fit Twitter's 280 weighted chars (URLs count 23).
5. NEVER use marketing words: "excited to announce", "thrilled", "introducing".
6. End every tweet with a question OR provocative claim (reply +27 HeavyRanker).
7. URLs go in reply only — never in the main hook body.
8. If today's track is Tutorial (Sat) or Foundations (Mon), favor image=true.
9. If there has been NO behind-the-scenes post in 7+ days, weight that pillar higher.
10. Match audience language: English for global dev audience (default).

Be decisive. Pick one option. Justify with data."""


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


def _recent_posted(days: int = 7) -> list[dict]:
    """Last N days of posted tweets — pillar tagging from id prefix when possible."""
    cutoff = time.time() - days * 86400
    out = []
    if not POSTED.exists():
        return out
    for f in sorted(POSTED.glob("*.json")):
        item = _load_json(f)
        if not isinstance(item, dict):
            continue
        if item.get("posted_at", 0) < cutoff:
            continue
        out.append({
            "id": item.get("id"),
            "text": (item.get("text") or "")[:200],
            "posted_at": item.get("posted_at"),
            "tweet_id": item.get("tweet_id"),
            "kind": item.get("kind"),
            "pillar": _infer_pillar(item.get("id", "")),
        })
    return out


def _infer_pillar(draft_id: str) -> str:
    """Best-effort pillar inference from draft id prefix."""
    if draft_id.startswith("tip-"):
        return "llm-tips"
    if draft_id.startswith("gem-"):
        return "gem-repos"
    if draft_id.startswith("bts-") or "smoke" in draft_id:
        return "behind-the-scenes"
    if draft_id.startswith("teaser-") or "conductor" in draft_id:
        return "teaser"
    return "cdpilot"


def _pillar_balance(posted: list[dict]) -> dict:
    """Returns {pillar: count, pillar_share: pct, target: pct, delta: pct}."""
    total = max(len(posted), 1)
    counts = {k: 0 for k in PILLAR_KEYS}
    for p in posted:
        pk = p.get("pillar") or "cdpilot"
        if pk in counts:
            counts[pk] += 1
    balance = {}
    for k in PILLAR_KEYS:
        share = counts[k] / total
        balance[k] = {
            "count": counts[k],
            "share": round(share, 3),
            "target": PILLAR_TARGET[k],
            "delta": round(share - PILLAR_TARGET[k], 3),
        }
    return balance


def _kpi_recent(days: int = 3) -> dict:
    """Aggregate KPI from the last N analytics snapshots."""
    if not ANALYTICS.exists():
        return {}
    files = sorted(ANALYTICS.glob("*.json"))[-days:]
    if not files:
        return {}
    latest = _load_json(files[-1]) if files else {}
    all_metrics = []
    for f in files:
        snap = _load_json(f)
        if isinstance(snap, dict):
            all_metrics.extend(snap.get("tweet_metrics", []))

    def _i(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    total_views = sum(_i(m.get("views")) for m in all_metrics)
    total_likes = sum(_i(m.get("likes")) for m in all_metrics)
    total_replies = sum(_i(m.get("replies")) for m in all_metrics)
    top = sorted(all_metrics, key=lambda m: _i(m.get("views")), reverse=True)[:3]
    return {
        "followers": latest.get("followers") if isinstance(latest, dict) else None,
        "following": latest.get("following") if isinstance(latest, dict) else None,
        "tweets_tracked": len(all_metrics),
        "total_views": total_views,
        "total_likes": total_likes,
        "total_replies": total_replies,
        "top_3": [
            {
                "id": m.get("id"),
                "text": (m.get("text") or "")[:120],
                "views": _i(m.get("views")),
                "likes": _i(m.get("likes")),
                "replies": _i(m.get("replies")),
            }
            for m in top
        ],
    }


def _active_experiments() -> dict:
    """Active experiment status snapshot."""
    exps = {}

    # URL-in-reply A/B (15-day, ends 2026-06-05)
    end = datetime(2026, 6, 5)
    today = datetime.now()
    if today <= end:
        exps["url_in_reply"] = {
            "status": "active",
            "ends": end.strftime("%Y-%m-%d"),
            "days_left": (end - today).days,
            "rule": "URLs go in followup reply, NEVER in body. Decision +15% delta → keep.",
        }

    # Grok rotation state
    grok_state = STATE / "grok-rotation.json"
    if grok_state.exists():
        rot = _load_json(grok_state)
        exps["grok"] = {
            "next_topic_idx": rot.get("next_idx", 0) if isinstance(rot, dict) else 0,
            "last_posted": rot.get("last_posted") if isinstance(rot, dict) else None,
            "rule": "1x/week max, Tuesday morning preferred.",
        }

    # Crisis freeze
    if (STATE / "crisis-freeze.flag").exists():
        exps["crisis_freeze"] = {"active": True, "rule": "Posting frozen — recovery mode."}

    return exps


def _trend_candidates(top: int = 5) -> list[dict]:
    """Recent discovery_scan output (HN + niche)."""
    if not DISCOVERIES.exists():
        return []
    files = sorted(DISCOVERIES.glob("*.json"))[-2:]
    cands = []
    for f in files:
        data = _load_json(f)
        if isinstance(data, list):
            cands.extend(data)
        elif isinstance(data, dict):
            cands.extend(data.get("items", []) or [])
    return cands[:top]


def _draft_pipeline_count() -> int:
    """How many drafts are currently in drafts/ awaiting approval?"""
    if not DRAFTS.exists():
        return 0
    return len(list(DRAFTS.glob("*.json")))


def build_context() -> dict:
    today = datetime.now()
    weekday = today.weekday()
    posted = _recent_posted(days=7)
    return {
        "today": today.strftime("%Y-%m-%d"),
        "weekday_tr": DAY_NAMES_TR[weekday],
        "weekly_track": TRACK_BY_DAY[weekday],
        "kpi_last_3d": _kpi_recent(days=3),
        "posted_last_7d": [
            {"id": p["id"], "text": p["text"][:120], "pillar": p["pillar"]}
            for p in posted
        ],
        "pillar_balance_7d": _pillar_balance(posted),
        "active_experiments": _active_experiments(),
        "trend_candidates": _trend_candidates(top=5),
        "drafts_pending": _draft_pipeline_count(),
        "tier1_snapshot": _load_json(TIER1) if TIER1.exists() else {},
    }


def _claude_available() -> bool:
    return shutil.which(CLAUDE_BIN) is not None


def _ask_claude(context: dict, timeout: int = 180) -> dict:
    """Send context to Claude CLI, get structured recommendation."""
    user_prompt = (
        "TODAY'S CONTEXT (JSON):\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        "Now produce TODAY'S RECOMMENDATION as strict JSON per the schema in your "
        "system prompt. No prose, no markdown fences, no preamble — just the JSON object."
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

    # Strip possible code fences
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


def _render_card_text(rec: dict, context: dict) -> str:
    """Plain-text strategy card for Telegram."""
    pb = context.get("pillar_balance_7d", {})
    worst_pillar = min(pb.items(), key=lambda kv: kv[1]["delta"])[0] if pb else "?"
    kpi = context.get("kpi_last_3d", {})

    image = rec.get("image") or {}
    url_in_reply = rec.get("url_in_reply") or ""
    lines = [
        f"📅 GÜNÜN STRATEJİSİ — {context['today']} ({context['weekday_tr']})",
        f"Haftalık tema: {context['weekly_track']}",
        "",
        f"📍 Konu (pillar): {rec.get('pillar', '?')}",
        f"📐 Format: {rec.get('format', '?')}  ·  ⏰ Atış saati: {rec.get('post_time_tr', '?')} (TR)",
        "",
        "🎯 TWEET METNİ (hook):",
        rec.get("hook", "(boş)"),
        "",
    ]
    body = rec.get("body_outline")
    if body and body != "same as hook":
        lines += ["📝 Devamı:", body, ""]
    lines += [
        f"🪝 Soru ile bitiş: {rec.get('reply_bait', '(yok)')}",
        f"🖼  Görsel üretilecek mi: {'EVET — ' + (image.get('concept') or '?') if image.get('needed') else 'HAYIR'}",
    ]
    if url_in_reply:
        lines.append(f"🔗 URL (sadece reply'da paylaşılacak): {url_in_reply}")
    lines += [
        "",
        "🧠 NEDEN BU SEÇİM:",
        rec.get("reasoning", "(gerekçe yok)"),
        "",
        "── Bağlam ──",
        f"Takipçi: {kpi.get('followers')}  ·  7 günlük gösterim: {kpi.get('total_views')}  ·  Kuyrukta bekleyen: {context.get('drafts_pending')}",
        f"En zayıf konu (7g): {worst_pillar} (hedef sapma {pb.get(worst_pillar, {}).get('delta', '?')})",
    ]
    if context.get("active_experiments", {}).get("url_in_reply"):
        exp = context["active_experiments"]["url_in_reply"]
        lines.append(f"URL-reply deneyi: {exp.get('days_left')} gün kaldı")
    lines += [
        "",
        "👇 Karar ver:",
        "✅ Onayla → görsel üretilir + taslak kuyruğa girer",
        "💬 Revize → bu mesaja reply'la not yaz",
        "⏭ Geç → bugün strateji atlanır",
    ]
    return "\n".join(lines)


def _send_to_telegram(card_text: str, strategy_id: str) -> dict:
    """Send the strategy card with approve/revise/skip inline buttons."""
    sys.path.insert(0, str(Path(__file__).parent))
    import telegram_bridge as tb  # type: ignore

    env = tb._load_env()
    if not env.get("TELEGRAM_CHAT_ID"):
        _log("TELEGRAM_CHAT_ID missing, skipping send")
        return {"_error": "no_chat_id"}

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Bugün bunu yap", "callback_data": f"stratgo:{strategy_id}"},
            {"text": "💬 Revize", "callback_data": f"stratrev:{strategy_id}"},
            {"text": "⏭ Geç", "callback_data": f"stratskip:{strategy_id}"},
        ]]
    }

    # Telegram message limit is 4096; trim if needed.
    if len(card_text) > 3800:
        card_text = card_text[:3800] + "\n…(kısaltıldı)"

    result = tb._api(env, "sendMessage", {
        "chat_id": int(env["TELEGRAM_CHAT_ID"]),
        "text": card_text,
        "disable_web_page_preview": True,
        "reply_markup": keyboard,
    })
    # Register the strategy under message_id so the daemon can route the callback.
    msg_id = result.get("message_id")
    if msg_id:
        tb._register_pending(msg_id, {
            "id": f"strategy-{strategy_id}",
            "kind": "strategy",
            "strategy_id": strategy_id,
        })
    return result


def _auto_queue(strategy_id: str, artifact: dict) -> dict:
    """AUTO_POST: compile the strategy recommendation into a draft and queue it
    directly (no approval card). Hot-zone scheduled_time is preserved via the
    shared telegram_bridge queue logic.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import telegram_bridge as tb  # type: ignore

    draft = tb._strategy_to_draft(strategy_id, artifact)
    if not draft:
        return {"_error": "no_draft"}
    qp = tb.auto_queue_draft(draft)
    return {"queued": True, "queue_path": str(qp), "draft_id": draft["id"]}


def run(send: bool = True) -> dict:
    today_str = datetime.now().strftime("%Y-%m-%d")
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)

    out_path = STRATEGY_DIR / f"{today_str}.json"
    if out_path.exists() and os.environ.get("CDPILOT_STRATEGIST_FORCE") != "1":
        existing = _load_json(out_path)
        # Weekly-preapproved artifact: send the card now (no Claude call), so user
        # still gets daily approval prompt for the pre-planned hook.
        if isinstance(existing, dict) and existing.get("approval_status") == "weekly_preapproved":
            sys.path.insert(0, str(Path(__file__).parent))
            import telegram_bridge as tb  # type: ignore
            if tb.auto_post_enabled():
                aq = _auto_queue(today_str, existing)
                if aq.get("_error"):
                    _log(f"weekly auto-queue failed: {aq['_error']}")
                    return {"status": "weekly_autoqueue_fail", "path": str(out_path),
                            "error": aq["_error"]}
                existing["approval_status"] = "auto_queued"
                existing["queued_at"] = int(time.time())
                out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
                _log(f"auto-queued weekly-derived strategy for {today_str}")
                return {"status": "weekly_auto_queued", "path": str(out_path), **aq}
            try:
                rec = existing.get("recommendation", {})
                ctx = build_context()
                card = _render_card_text(rec, ctx)
                # Mark as approved-from-weekly to indicate origin in card
                card = "📆 Haftalık plandan türetildi.\n\n" + card
                tg_result = _send_to_telegram(card, today_str)
                existing["telegram_message_id"] = tg_result.get("message_id")
                existing["approval_status"] = "awaiting_telegram"
                out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
                _log(f"sent weekly-derived strategy card for {today_str}")
                return {"status": "weekly_card_sent", "path": str(out_path)}
            except Exception as e:
                _log(f"weekly card send failed: {e}")
                return {"status": "weekly_card_fail", "path": str(out_path), "error": str(e)}
        _log(f"strategy already exists for {today_str}: {out_path} (set CDPILOT_STRATEGIST_FORCE=1 to overwrite)")
        return {"status": "exists", "strategy": existing, "path": str(out_path)}

    context = build_context()

    if not _claude_available():
        _log("claude CLI unavailable — emitting context-only artifact")
        artifact = {
            "id": today_str,
            "generated_at": int(time.time()),
            "context": context,
            "recommendation": None,
            "approval_status": "no_claude",
        }
        out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        return {"status": "no_claude", "path": str(out_path)}

    rec = _ask_claude(context)
    artifact = {
        "id": today_str,
        "generated_at": int(time.time()),
        "context": context,
        "recommendation": rec,
        "model": MODEL,
        "approval_status": "pending",
    }
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
    _log(f"wrote strategy artifact {out_path}")

    if rec.get("_error"):
        _log(f"recommendation error: {rec['_error']}")
        if send:
            try:
                _send_to_telegram(
                    f"⚠️ Daily Strategist hatası: {rec.get('_error')}\n"
                    f"Artifact: {out_path}",
                    today_str,
                )
            except Exception as e:
                _log(f"telegram error notification failed: {e}")
        return {"status": "error", "path": str(out_path), "error": rec["_error"]}

    if send:
        sys.path.insert(0, str(Path(__file__).parent))
        import telegram_bridge as tb  # type: ignore
        if tb.auto_post_enabled():
            aq = _auto_queue(today_str, artifact)
            if aq.get("_error"):
                _log(f"auto-queue failed: {aq['_error']}")
                return {"status": "autoqueue_fail", "path": str(out_path),
                        "error": aq["_error"], "recommendation": rec}
            artifact["approval_status"] = "auto_queued"
            artifact["queued_at"] = int(time.time())
            out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
            _log(f"auto-queued strategy for {today_str} → {aq.get('queue_path')}")
            return {"status": "auto_queued", "path": str(out_path),
                    "recommendation": rec, **aq}
        try:
            card = _render_card_text(rec, context)
            tg_result = _send_to_telegram(card, today_str)
            artifact["telegram_message_id"] = tg_result.get("message_id")
            artifact["approval_status"] = "awaiting_telegram"
            out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        except Exception as e:
            _log(f"telegram send failed: {e}")
            return {"status": "telegram_fail", "path": str(out_path), "error": str(e)}

    return {"status": "ok", "path": str(out_path), "recommendation": rec}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--no-send", action="store_true", help="don't send Telegram card, only write artifact")
    p.add_argument("--force", action="store_true", help="overwrite existing strategy for today")
    p.add_argument("--print-context", action="store_true", help="dump context blob and exit (no claude call)")
    args = p.parse_args()

    if args.force:
        os.environ["CDPILOT_STRATEGIST_FORCE"] = "1"

    if args.print_context:
        print(json.dumps(build_context(), ensure_ascii=False, indent=2))
        return

    result = run(send=not args.no_send)
    print(json.dumps({k: v for k, v in result.items() if k != "recommendation"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
