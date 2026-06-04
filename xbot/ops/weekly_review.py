#!/usr/bin/env python3
"""weekly_review.py — Faz A #2.

Her Pazar 22:00'de cycle night slot'unda çalışır. Geçen haftanın:
  • KPI özetini (toplam impression/like/reply, follower delta, top/bottom 3)
  • Format ROI'sini (single/thread/image hangisi daha çok engagement getirdi)
  • Saat dağılımını (hangi slot daha iyi performans gösterdi)
  • Pillar dağılımını (hangi konu eksik, hangisi fazla)

derler, srv21 Claude CLI ile gelecek haftanın 7-günlük backlog'unu ÜRETİR:
  [{date, weekday, track, pillar, format, hook_seed, reasoning}] x 7

Çıktı:
  ~/cdpilot-twitter-data/state/weekly/YYYY-WW.json (weekly review artifact)
  Telegram'a 7-günlük plan kartı (✅ Onayla / 💬 Revize / ⏭ Geç)

Onaylanırsa: 7 ayrı strategy artifact'ı (state/strategy/YYYY-MM-DD.json) yazılır.
daily_strategist sabah çalışırken artifact mevcutsa Claude'u tekrar çağırmaz, hazır
öneriyi alıp Telegram'a sunar (CDPILOT_STRATEGIST_FORCE=1 değilse).

DOCTRINE.md §3 Faz A item 2.
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
STATE = DATA / "state"
WEEKLY_DIR = STATE / "weekly"
STRATEGY_DIR = STATE / "strategy"
LOG_FILE = DATA / "logs" / "weekly.log"

CLAUDE_BIN = os.environ.get("CDPILOT_CLAUDE_BIN", "claude")
MODEL = os.environ.get("CDPILOT_WEEKLY_MODEL", "claude-sonnet-4-6")

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

SYSTEM_PROMPT = """You are the weekly content planner for the @cdpilot_dev Twitter/X account.
Identity: cool peer voice, technical credibility, never helpful-bot, never marketing-speak.

cdpilot: open-source CDP browser automation CLI (zero deps, stealth + adaptive,
v0.8.0). Audience: browser automation devs, anti-bot researchers, AI agent builders.

YOUR JOB:
Read last week's KPI + format ROI + pillar balance + time-of-day performance.
Produce next week's 7-day content backlog — one tweet plan per day.

OUTPUT FORMAT (strict JSON, no markdown, no preamble):
{
  "summary_tr": "2-3 cümle Türkçe haftalık değerlendirme (ne işe yaradı, ne yaramadı)",
  "next_week_plan": [
    {
      "date": "YYYY-MM-DD",
      "weekday": "Mon|Tue|Wed|Thu|Fri|Sat|Sun",
      "track": "Foundations|Anti-Bot Wars|Building in Public|X/Twitter Internal|Comparisons|Tutorial|History",
      "pillar": "cdpilot|llm-tips|gem-repos|behind-the-scenes|teaser",
      "format": "single|thread|image|quote",
      "post_time_tr": "HH:MM",
      "hook_seed": "1 sentence hook idea (will be refined by daily strategist)",
      "reasoning": "1-2 sentence WHY this slot — backed by KPI evidence"
    },
    ... (7 items, one per day starting from next Monday)
  ]
}

HARD RULES:
1. Cover all 7 days of NEXT week (Mon-Sun from the start_date provided).
2. Times in Istanbul hot zones: 13:00-15:00 / 17:00-19:00 / 21:00-23:00. Never :00 minutes.
3. Each day's track MUST match the weekly rotation (Mon=Foundations, Tue=Anti-Bot, etc.)
   UNLESS last week's KPI strongly suggests overriding for one day.
4. Pillar distribution across the 7 days should approximate:
   cdpilot 35%, llm-tips 25%, gem-repos 20%, behind-the-scenes 10%, teaser 10%.
   But ALSO compensate for last week's imbalance — overrepresented pillars get less.
5. Variety in formats: don't put 7 single tweets. Aim for ~4 single, ~2 thread, ~1 image.
   But weight winning format from last week's ROI higher.
6. Hook seeds must be SPECIFIC topics, not "share a tip about X". Give the actual angle.
7. summary_tr should mention: top 1 winning slot, bottom 1, suggested adjustment.
8. NEVER include marketing words ("excited", "thrilled", "introducing", "check out").

Be decisive. Plan the full week."""


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


def _infer_pillar(draft_id: str) -> str:
    if draft_id.startswith("tip-"):
        return "llm-tips"
    if draft_id.startswith("gem-"):
        return "gem-repos"
    if draft_id.startswith("bts-") or "smoke" in draft_id:
        return "behind-the-scenes"
    if draft_id.startswith("teaser-") or "conductor" in draft_id:
        return "teaser"
    return "cdpilot"


def _infer_format(item: dict) -> str:
    if item.get("image_path") or item.get("image_content"):
        return "image"
    text = item.get("text") or ""
    if len(text) > 240 or "\n\n" in text and text.count("\n\n") >= 3:
        return "thread"
    if item.get("kind") == "quote":
        return "quote"
    return "single"


def _to_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _week_kpi(days: int = 7) -> dict:
    """Aggregate week's KPI + per-format/per-slot performance."""
    cutoff = time.time() - days * 86400
    posted = []
    if POSTED.exists():
        for f in sorted(POSTED.glob("*.json")):
            item = _load_json(f)
            if isinstance(item, dict) and item.get("posted_at", 0) >= cutoff:
                posted.append(item)

    # Latest metrics by tweet_id from analytics files
    metrics_by_id: dict[str, dict] = {}
    if ANALYTICS.exists():
        for f in sorted(ANALYTICS.glob("*.json"))[-days:]:
            snap = _load_json(f)
            if not isinstance(snap, dict):
                continue
            for m in snap.get("tweet_metrics", []):
                tid = m.get("tweet_id")
                if tid:
                    metrics_by_id[tid] = m

    per_format: dict[str, dict] = {}
    per_slot: dict[str, dict] = {}
    per_pillar: dict[str, dict] = {}

    tweets_summary = []
    for item in posted:
        tid = item.get("tweet_id")
        m = metrics_by_id.get(tid, {})
        views = _to_int(m.get("views"))
        likes = _to_int(m.get("likes"))
        replies = _to_int(m.get("replies"))
        rt = _to_int(m.get("rt"))
        engagement = likes + 2 * replies + 3 * rt

        fmt = _infer_format(item)
        pillar = _infer_pillar(item.get("id", ""))
        posted_ts = item.get("posted_at", 0)
        slot = "?"
        if posted_ts:
            h = datetime.fromtimestamp(posted_ts).hour
            if 13 <= h < 15:
                slot = "13-15"
            elif 17 <= h < 19:
                slot = "17-19"
            elif 21 <= h < 23:
                slot = "21-23"
            else:
                slot = f"{h:02d}-other"

        for bucket, key in [(per_format, fmt), (per_slot, slot), (per_pillar, pillar)]:
            bucket.setdefault(key, {"count": 0, "views": 0, "engagement": 0})
            bucket[key]["count"] += 1
            bucket[key]["views"] += views
            bucket[key]["engagement"] += engagement

        tweets_summary.append({
            "id": item.get("id"),
            "text": (item.get("text") or "")[:120],
            "pillar": pillar,
            "format": fmt,
            "slot": slot,
            "views": views,
            "likes": likes,
            "replies": replies,
            "rt": rt,
            "engagement": engagement,
        })

    # Compute averages
    def _averaged(bucket: dict) -> dict:
        for k, v in bucket.items():
            v["avg_views"] = round(v["views"] / max(v["count"], 1), 1)
            v["avg_engagement"] = round(v["engagement"] / max(v["count"], 1), 2)
        return bucket

    # Follower delta from oldest and newest analytics in range
    follower_delta = None
    follower_now = None
    if ANALYTICS.exists():
        files = sorted(ANALYTICS.glob("*.json"))[-days:]
        if len(files) >= 2:
            first = _load_json(files[0])
            last = _load_json(files[-1])
            if isinstance(first, dict) and isinstance(last, dict):
                f0 = first.get("followers")
                f1 = last.get("followers")
                follower_now = f1
                if f0 is not None and f1 is not None:
                    follower_delta = f1 - f0
        elif files:
            last = _load_json(files[-1])
            if isinstance(last, dict):
                follower_now = last.get("followers")

    top3 = sorted(tweets_summary, key=lambda x: x["engagement"], reverse=True)[:3]
    bottom3 = sorted(tweets_summary, key=lambda x: x["engagement"])[:3]

    return {
        "window_days": days,
        "tweets_posted": len(posted),
        "follower_now": follower_now,
        "follower_delta_7d": follower_delta,
        "total_views": sum(t["views"] for t in tweets_summary),
        "total_engagement": sum(t["engagement"] for t in tweets_summary),
        "per_format": _averaged(per_format),
        "per_slot": _averaged(per_slot),
        "per_pillar": _averaged(per_pillar),
        "top_3": top3,
        "bottom_3": bottom3,
    }


def _next_week_dates() -> list[dict]:
    """Returns [{date, weekday_tr, weekday_en, track}] for next Mon..Sun."""
    today = datetime.now()
    # Next Monday
    days_until_mon = (7 - today.weekday()) % 7 or 7
    start = today + timedelta(days=days_until_mon)
    out = []
    for i in range(7):
        d = start + timedelta(days=i)
        wd = d.weekday()
        out.append({
            "date": d.strftime("%Y-%m-%d"),
            "weekday_tr": DAY_NAMES_TR[wd],
            "weekday_en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wd],
            "track": TRACK_BY_DAY[wd],
        })
    return out


def _load_profile_summary() -> dict:
    """Pull decision_learner profile.json if present — adds learned patterns
    to weekly card so user sees what was inferred."""
    p = STATE / "profile.json"
    if not p.exists():
        return {}
    try:
        prof = json.loads(p.read_text())
        return {
            "total_decisions": prof.get("total_decisions", 0),
            "revision_rate": prof.get("revision_rate", 0),
            "summary_tr": prof.get("summary_tr", ""),
            "high_trust_handles": [h for h, b in prof.get("handle_stats", {}).items()
                                   if b.get("trust") == "high"][:6],
            "veto_handles": [h for h, b in prof.get("handle_stats", {}).items()
                             if b.get("trust") == "veto"][:6],
            "pillar_deltas": prof.get("pillar_weight_deltas", {}),
        }
    except (OSError, ValueError):
        return {}


def build_context() -> dict:
    kpi = _week_kpi(days=7)
    next_week = _next_week_dates()
    return {
        "this_week_kpi": kpi,
        "next_week_dates": next_week,
        "today": datetime.now().strftime("%Y-%m-%d"),
        "week_iso": datetime.now().strftime("%G-W%V"),
        "learned_profile": _load_profile_summary(),
    }


def _claude_available() -> bool:
    return shutil.which(CLAUDE_BIN) is not None


def _ask_claude(context: dict, timeout: int = 240) -> dict:
    user_prompt = (
        "WEEKLY CONTEXT (JSON):\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        "Now produce the weekly review + next-week 7-day backlog as strict JSON per "
        "the schema in your system prompt. No prose, no markdown fences, no preamble — "
        "just the JSON object."
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


def _render_card_text(plan: dict, context: dict) -> str:
    kpi = context.get("this_week_kpi", {})
    summary = plan.get("summary_tr", "(özet yok)")
    nw = plan.get("next_week_plan", [])

    lines = [
        f"📊 HAFTALIK DEĞERLENDİRME — {context.get('week_iso','?')}",
        "",
        f"📈 Geçen hafta: {kpi.get('tweets_posted')} tweet · "
        f"{kpi.get('total_views')} gösterim · "
        f"takipçi delta: {kpi.get('follower_delta_7d', '?')}",
        "",
        "🧠 ÖZET:",
        summary,
        "",
    ]

    # Decision learner insights (Faz B) — what we learned from user's decisions
    lp = context.get("learned_profile") or {}
    if lp.get("total_decisions", 0) >= 5:
        lines.append("── 🧬 SENDEN ÖĞRENDİKLERİM ──")
        lines.append(lp.get("summary_tr", ""))
        if lp.get("high_trust_handles"):
            lines.append(f"💚 Bundan sonra otomatik reply: {', '.join(lp['high_trust_handles'])}")
        if lp.get("veto_handles"):
            lines.append(f"🛑 Sessizce skip edeceğim: {', '.join(lp['veto_handles'])}")
        if lp.get("revision_rate", 0) > 0.30:
            lines.append(f"✏️ Revision oranı yüksek ({lp['revision_rate']*100:.0f}%). "
                         f"Reply-tone kalibrasyonu gerekebilir.")
        lines.append("")

    lines.append("── ÖNÜMÜZDEKİ HAFTA (7-GÜN PLAN) ──")
    for d in nw:
        lines.append(
            f"📅 {d.get('date')} {d.get('weekday','?')}  ·  {d.get('post_time_tr','?')}  ·  "
            f"{d.get('pillar','?')}/{d.get('format','?')}"
        )
        lines.append(f"   🎯 {d.get('hook_seed','(yok)')}")
        why = d.get("reasoning", "")
        if why:
            lines.append(f"   🧠 {why}")
        lines.append("")

    lines += [
        "👇 Karar ver:",
        "✅ Onayla → 7 strateji günlük olarak hazırlanır, her sabah Telegram'a düşer",
        "💬 Revize → bu mesaja reply'la not yaz, tekrar üretilir",
        "⏭ Geç → bu hafta plan yok, sabah strategist tek tek karar versin",
    ]
    return "\n".join(lines)


def _send_to_telegram(card_text: str, week_id: str) -> dict:
    sys.path.insert(0, str(Path(__file__).parent))
    import telegram_bridge as tb  # type: ignore

    env = tb._load_env()
    if not env.get("TELEGRAM_CHAT_ID"):
        _log("TELEGRAM_CHAT_ID missing")
        return {"_error": "no_chat_id"}

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Onayla (7-gün)", "callback_data": f"weekgo:{week_id}"},
            {"text": "💬 Revize", "callback_data": f"weekrev:{week_id}"},
            {"text": "⏭ Geç", "callback_data": f"weekskip:{week_id}"},
        ]]
    }

    if len(card_text) > 3800:
        card_text = card_text[:3800] + "\n…(kısaltıldı)"

    result = tb._api(env, "sendMessage", {
        "chat_id": int(env["TELEGRAM_CHAT_ID"]),
        "text": card_text,
        "disable_web_page_preview": True,
        "reply_markup": keyboard,
    })

    msg_id = result.get("message_id")
    if msg_id:
        tb._register_pending(msg_id, {
            "id": f"weekly-{week_id}",
            "kind": "weekly",
            "week_id": week_id,
        })
    return result


def run(send: bool = True) -> dict:
    week_id = datetime.now().strftime("%G-W%V")
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = WEEKLY_DIR / f"{week_id}.json"

    if out_path.exists() and os.environ.get("CDPILOT_WEEKLY_FORCE") != "1":
        existing = _load_json(out_path)
        _log(f"weekly already exists for {week_id}")
        return {"status": "exists", "path": str(out_path), "existing": existing}

    context = build_context()

    if not _claude_available():
        artifact = {
            "id": week_id,
            "generated_at": int(time.time()),
            "context": context,
            "plan": None,
            "approval_status": "no_claude",
        }
        out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        return {"status": "no_claude", "path": str(out_path)}

    plan = _ask_claude(context)
    artifact = {
        "id": week_id,
        "generated_at": int(time.time()),
        "context": context,
        "plan": plan,
        "model": MODEL,
        "approval_status": "pending",
    }
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
    _log(f"wrote weekly artifact {out_path}")

    if plan.get("_error"):
        if send:
            try:
                _send_to_telegram(f"⚠️ Weekly Strategist hatası: {plan.get('_error')}", week_id)
            except Exception as e:
                _log(f"telegram error notification failed: {e}")
        return {"status": "error", "path": str(out_path), "error": plan["_error"]}

    if send:
        try:
            card = _render_card_text(plan, context)
            tg_result = _send_to_telegram(card, week_id)
            artifact["telegram_message_id"] = tg_result.get("message_id")
            artifact["approval_status"] = "awaiting_telegram"
            out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        except Exception as e:
            _log(f"telegram send failed: {e}")
            return {"status": "telegram_fail", "path": str(out_path), "error": str(e)}

    return {"status": "ok", "path": str(out_path)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--no-send", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--print-context", action="store_true")
    args = p.parse_args()

    if args.force:
        os.environ["CDPILOT_WEEKLY_FORCE"] = "1"

    if args.print_context:
        print(json.dumps(build_context(), ensure_ascii=False, indent=2))
        return

    result = run(send=not args.no_send)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
