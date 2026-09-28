#!/usr/bin/env python3
"""pain_hunter.py — find people complaining without knowing cdpilot exists.

search_respond.py answered *questions* about our niche. This looks for a
narrower, higher-value signal: someone describing THEIR OWN pain, in their own
words, with no idea a tool like ours exists. The data behind this module is
.claude/docs/x-sorun-haritasi-2026-09-27.md (cdpilot repo) — a manual read of
59 fresh + 573 historical search results that found two hard lessons:

  1. Long, ordinary-word sentences are noise: "cursor agent can't see my
     browser" pulled back 30/30 unrelated tweets. The first fix — quoting every
     query as an exact phrase — was measured the same day and returned ZERO
     results (people never write our phrase). Short, specific bare word sets
     ("cookies keep expiring") are what found the real complaint, because X
     ANDs the words. See _search_one and pain-queries.json "query_note".
  2. MIN_FOLLOWERS (search_respond's 1000-follower floor) filters out exactly
     the people who write real complaints — @work_adam08 (32 followers) and
     @vincent_edes (409 followers) are the two clearest hits in the harita
     doc. This module has NO follower floor.

Everything else about the funnel is stricter, not looser: 36h freshness, a
30-day seen-cache so the same tweet is never re-classified, a competitor
denylist (CloakBrowser/OctoBrowser/browser-use/Browserbase/Jev/nottecore all
market into this exact vocabulary), and a real classifier call before anything
is written to the reply queue. A reply we don't send costs nothing.

Config lives in xbot/pain-queries.json (data, not code) — queries, classes,
and each class's real cdpilot answer (or its acknowledged gap), so the roadmap
signal and the reply copy both come from one audited source.

CLI:
  python pain_hunter.py            # one cycle: search, classify, reply, log
  python pain_hunter.py --dry-run  # same, but writes nothing anywhere
  python pain_hunter.py --digest    # 7-day roadmap/reply digest -> pains/*.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import bot_home  # noqa: E402
from _relevance import off_limits  # noqa: E402
import _novelty  # noqa: E402
import _notify  # noqa: E402
import reply_drafter  # noqa: E402

DATA = bot_home()
XBOT = Path(__file__).resolve().parent.parent
STATE = DATA / "state"
PAINS_DIR = DATA / "pains"
DRAFTS_DIR = DATA / "drafts"
LOG_FILE = DATA / "logs" / "pain-hunter.log"
CURSOR_PATH = STATE / "pain-cursor.json"
SEEN_PATH = PAINS_DIR / "seen.json"

COOKIES_PATH = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES", str(DATA / "cookies" / "cdpilot_dev.json")))
LANG = os.environ.get("CDPILOT_TWIKIT_LANG", "en-US")
HANDLE = os.environ.get("CDPILOT_HANDLE", "cdpilot_dev")

PAIN_CONFIG_PATH = Path(os.environ.get(
    "CDPILOT_PAIN_QUERIES", str(XBOT / "pain-queries.json")))

MAX_AGE_HOURS = int(os.environ.get("CDPILOT_PAIN_MAX_AGE_H", "36"))
MIN_BODY_CHARS = int(os.environ.get("CDPILOT_PAIN_MIN_BODY_CHARS", "40"))
QUERIES_PER_RUN = int(os.environ.get("CDPILOT_PAIN_QUERIES_PER_RUN", "6"))
SEARCH_GAP_S = int(os.environ.get("CDPILOT_PAIN_SEARCH_GAP_S", "20"))
SEEN_WINDOW_DAYS = int(os.environ.get("CDPILOT_PAIN_SEEN_DAYS", "30"))
DAILY_REPLY_CAP = int(os.environ.get("CDPILOT_PAIN_DAILY_CAP", "3"))
CDPILOT_MENTION_BUDGET = int(os.environ.get("CDPILOT_PAIN_MENTION_BUDGET", "1"))


class RateLimited(Exception):
    """Raised when the search client reports a 429 / rate-limit response."""


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


# ── config ──

def load_pain_config(path: Path | None = None) -> dict:
    p = path or PAIN_CONFIG_PATH
    return json.loads(p.read_text())


# ── cursor rotation (which 6 queries run this cycle) ──

def next_queries(all_queries: list[dict], cursor_path: Path,
                  n: int = QUERIES_PER_RUN, persist: bool = True) -> list[dict]:
    """Return the next `n` queries, round-robin, and advance the cursor.

    `persist=False` (used by --dry-run) reads the position but never writes
    the advance — a dry run must not change what the next real run sees.
    """
    if not all_queries:
        return []
    try:
        pos = json.loads(cursor_path.read_text()).get("pos", 0)
    except Exception:
        pos = 0
    total = len(all_queries)
    picked = [all_queries[(pos + i) % total] for i in range(min(n, total))]
    if persist:
        cursor_path.parent.mkdir(parents=True, exist_ok=True)
        cursor_path.write_text(json.dumps({"pos": (pos + n) % total}))
    return picked


# ── seen cache (30-day dedup) ──

def load_seen(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_seen(path: Path, seen: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen))


def prune_seen(seen: dict, now: float, days: int = SEEN_WINDOW_DAYS) -> dict:
    cutoff = now - days * 86400
    return {k: v for k, v in seen.items() if v >= cutoff}


# ── filters ──

_URL_RE = re.compile(r"https?://\S+")


def strip_urls(text: str) -> str:
    return _URL_RE.sub("", text or "")


def is_retweet(cand: dict) -> bool:
    text = cand.get("text") or ""
    if text.startswith("RT @"):
        return True
    return bool(cand.get("retweeted_tweet"))


def passes_filters(cand: dict, seen: dict, negative_terms: list[str],
                    negative_authors: set[str], now: float) -> tuple[bool, str]:
    """(ok, reason). Every rejection reason is named so callers can count them.

    No follower floor here on purpose — MIN_FOLLOWERS in search_respond.py is
    exactly what filters out the small accounts that write real complaints.
    """
    author = (cand.get("author") or "").lower()
    text = cand.get("text") or ""
    tweet_id = cand.get("tweet_id")

    if author == HANDLE.lower():
        return False, "self"
    if is_retweet(cand):
        return False, "retweet"

    hours_old = cand.get("hours_old")
    if hours_old is None:
        created = cand.get("created_ts") or 0
        hours_old = (now - created) / 3600.0 if created else 999
    if hours_old > MAX_AGE_HOURS:
        return False, "stale"

    body = strip_urls(text).strip()
    if len(body) < MIN_BODY_CHARS:
        return False, "link-only"

    low = text.lower()
    if author in negative_authors:
        return False, "competitor-noise"
    if any(term.lower() in low for term in negative_terms):
        return False, "competitor-noise"

    blocked = off_limits(text)
    if blocked:
        return False, f"off-limits:{blocked}"

    if tweet_id and tweet_id in seen:
        return False, "seen"

    return True, "ok"


# ── classification ──

_CMD_RE = re.compile(r"(?:npx cdpilot|cdpilot)\s+[a-z][\w-]*")


def allowed_commands(classes: dict) -> set[str]:
    """Real cdpilot commands mentioned in pain-queries.json's class answers.

    A fabricated command (the model inventing `cdpilot vision-solve`) will not
    appear here and gets rejected by `_command_is_known`.
    """
    out: set[str] = set()
    for info in classes.values():
        ans = (info.get("cdpilot_answer") or "").lower()
        out |= {m.group(0) for m in _CMD_RE.finditer(ans)}
    return out


def _command_is_known(command: str, allowed: set[str]) -> bool:
    if not command:
        return True
    hits = {m.group(0) for m in _CMD_RE.finditer(command.lower())}
    return bool(hits & allowed)


def classify_system_prompt(classes: dict) -> str:
    lines = []
    for name, info in classes.items():
        ans = info.get("cdpilot_answer")
        if ans:
            lines.append(f'- "{name}": cdpilot already solves this — {ans}')
        else:
            lines.append(f'- "{name}": cdpilot does NOT solve this yet — '
                          f'missing: {info.get("missing")}')
    classes_block = "\n".join(lines)
    return (
        "You are triaging an X (Twitter) post to decide whether it is a "
        "genuine, first-person software-engineering pain point that "
        "@cdpilot_dev (a zero-dependency browser automation CLI) can speak "
        "to.\n\nKNOWN PROBLEM CLASSES (use one of these, or \"other\" if none "
        f"fit):\n{classes_block}\n\n"
        "Return STRICT JSON only, no prose, no code fence, matching exactly "
        "this shape:\n"
        '{"first_person_pain": bool, "class": "<one of the class names above '
        'or \\"other\\">", "pain": "<=120 char summary of their actual '
        'problem>", "solvable_now": bool, "command": "<a real cdpilot command '
        'copied from the list above, or null>", "missing_capability": "<short '
        'label if solvable_now is false, else null>"}\n\n'
        "Rules:\n"
        "- first_person_pain is true only when the author is describing "
        "THEIR OWN experience, not reporting news, analyzing someone else's "
        "post, or marketing a product.\n"
        "- solvable_now is true only if cdpilot already ships a real command "
        "for their exact problem — never invent one.\n"
        "- command must be copied from the class list above (or null) — "
        "never invented, never a competitor's command.\n"
        "- missing_capability is null when solvable_now is true.\n"
        "- Output nothing but the JSON object."
    )


def classify_user_prompt(cand: dict) -> str:
    return (f'TWEET by @{cand.get("author")}:\n"{cand.get("text")}"\n\n'
            f'(matched search query: "{cand.get("query")}")\n\n'
            "Classify this tweet. Reply with the JSON object only — your reply "
            "must start with { and end with }. No analysis before or after it.")


def _strip_code_fence(text: str) -> str:
    """Return the JSON object inside a reply, tolerating fences and preamble.

    2026-09-27: nemotron-3-ultra answered the classifier with a paragraph of
    analysis ("The user is describing their own experience...") before — or
    instead of — the object. Take the outermost {...} span when there is one;
    pure prose still fails json.loads and is refused.
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        return t[start:end + 1]
    return t


def make_classification_validator(classes: dict) -> Callable[[str], tuple[str, list[str]]]:
    """Build the `validate(text)` callback passed to reply_drafter.generate."""
    allowed_classes = set(classes.keys()) | {"other"}
    allowed_cmds = allowed_commands(classes)

    def _validate(raw: str) -> tuple[str, list[str]]:
        text = _strip_code_fence(raw)
        try:
            obj = json.loads(text)
        except Exception:
            return text, ["invalid json"]

        required = ("first_person_pain", "class", "pain", "solvable_now",
                    "command", "missing_capability")
        issues = [f"missing key: {k}" for k in required if k not in obj]
        if issues:
            return text, issues

        if not isinstance(obj["first_person_pain"], bool):
            issues.append("first_person_pain not bool")
        if not isinstance(obj["solvable_now"], bool):
            issues.append("solvable_now not bool")
        if not isinstance(obj.get("class"), str) or obj["class"] not in allowed_classes:
            issues.append(f"unknown class: {obj.get('class')!r}")
        if not isinstance(obj.get("pain"), str) or not obj["pain"].strip():
            issues.append("empty pain")
        elif len(obj["pain"]) > 160:
            issues.append("pain too long")
        cmd = obj.get("command")
        if cmd is not None and (not isinstance(cmd, str) or not _command_is_known(cmd, allowed_cmds)):
            issues.append(f"unknown command: {cmd!r}")
        return text, issues

    return _validate


def classify_candidate(cand: dict, classes: dict, timeout: int = 60) -> dict:
    """Returns {"classification": dict|None, "engine": str|None, "errors": [...]}."""
    validator = make_classification_validator(classes)
    res = reply_drafter.generate(
        classify_system_prompt(classes), classify_user_prompt(cand),
        timeout=timeout, validate=validator, max_tokens=250,
    )
    if res.get("skip") or res.get("fallback") or not res.get("text"):
        return {"classification": None, "engine": res.get("engine"),
                "errors": res.get("errors", [])}
    try:
        obj = json.loads(_strip_code_fence(res["text"]))
    except Exception as e:
        return {"classification": None, "engine": res.get("engine"),
                "errors": [f"parse-failed:{e}"]}
    return {"classification": obj, "engine": res.get("engine"), "errors": []}


def classify_candidates(survivors: list[dict], classes: dict, now: float,
                         dry_run: bool = False) -> tuple[list[dict], int]:
    """Classify every filter-surviving candidate; log each to the ledger.

    Returns (classified_with_first_person_flag_attached, unclassified_count).
    `dry_run=True` classifies (a real model call) but writes nothing — the
    ledger is a record of what was DONE, not what was considered.
    """
    classified: list[dict] = []
    unclassified_n = 0
    for cand in survivors:
        result = classify_candidate(cand, classes)
        if not dry_run:
            append_ledger({
                "ts": now, "url": cand["url"], "author": cand["author"],
                "followers": cand.get("author_followers"), "text": cand["text"],
                "query": cand.get("query"), "tweet_id": cand["tweet_id"],
                "classification": result["classification"],
                "engine": result["engine"],
            })
        if result["classification"] is None:
            unclassified_n += 1
        else:
            cand["classification"] = result["classification"]
            classified.append(cand)
    return classified, unclassified_n


# ── ledger (pains/YYYY-MM.jsonl) ──

def _ledger_path(ts: float) -> Path:
    return PAINS_DIR / f"{datetime.fromtimestamp(ts).strftime('%Y-%m')}.jsonl"


def append_ledger(record: dict) -> None:
    ts = record.get("ts") or time.time()
    p = _ledger_path(ts)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def iter_ledger(days: int) -> list[dict]:
    """All ledger rows within the last `days`, newest last."""
    cutoff = time.time() - days * 86400
    out: list[dict] = []
    if not PAINS_DIR.exists():
        return out
    for f in sorted(PAINS_DIR.glob("*.jsonl")):
        try:
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if (row.get("ts") or 0) >= cutoff:
                    out.append(row)
        except Exception:
            continue
    out.sort(key=lambda r: r.get("ts", 0))
    return out


# ── daily reply cap + cdpilot-mention budget ──

def _daily_path(date_str: str) -> Path:
    return PAINS_DIR / f"daily-{date_str}.json"


def load_daily(date_str: str) -> dict:
    p = _daily_path(date_str)
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"date": date_str, "items": []}


def save_daily(date_str: str, data: dict) -> None:
    p = _daily_path(date_str)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def mentions_cdpilot(text: str) -> bool:
    return "cdpilot" in (text or "").lower()


def pain_mode_block(classification: dict, mentions_left: int) -> str:
    lines = [
        "--- SORUN MODU (pain_hunter) ---",
        "This tweet is a genuine, first-person pain point. Lead with a "
        "concrete way to solve THEIR problem on their own stack — a real "
        "technique, not a pitch.",
    ]
    if classification.get("solvable_now") and classification.get("command"):
        if mentions_left > 0:
            lines.append(
                f'cdpilot happens to ship exactly this: `{classification["command"]}`. '
                "You may name cdpilot ONCE, only because it is the honest answer.")
        else:
            lines.append(
                "cdpilot solves this, but today's cdpilot-mention budget is "
                "used up — solve or acknowledge the problem WITHOUT naming "
                "cdpilot.")
    else:
        lines.append(
            "cdpilot does not solve this today either — do not claim it "
            "does. Acknowledge the limit honestly, or share what you'd try.")
    lines.append("NO links in the body. Ending with a real question is fine.")
    return "\n".join(lines)


def reply_user_prompt(cand: dict) -> str:
    return (f'THEIR PAIN (from @{cand.get("author")}):\n"{cand.get("text")}"\n\n'
            "Write ONE reply tweet (max 2 sentences).")


_LINK_RE = re.compile(r"https?://|www\.")


def run_replies(pain_candidates: list[dict], dry_run: bool = False) -> dict:
    """Draft + queue replies for first-person-pain candidates, freshest first.

    Bounded by DAILY_REPLY_CAP (total for the day, not per run) and by
    CDPILOT_MENTION_BUDGET (how many of today's replies may name cdpilot).
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    daily = load_daily(date_str)
    stats = {"queued": 0, "drafts_written": 0, "rejected": 0}

    for idx, cand in enumerate(pain_candidates):
        if len(daily["items"]) >= DAILY_REPLY_CAP:
            break
        mentions_used = sum(1 for it in daily["items"] if it.get("mentions_cdpilot"))
        mentions_left = CDPILOT_MENTION_BUDGET - mentions_used
        classification = cand.get("classification") or {}

        sys_prompt = reply_drafter._system_prompt() + "\n\n" + pain_mode_block(
            classification, mentions_left)
        user_prompt = reply_user_prompt(cand)

        res = reply_drafter.generate(
            sys_prompt, user_prompt, timeout=90,
            validate=lambda t: reply_drafter._voice_lint(reply_drafter._clean(t)),
            max_tokens=220,
        )

        def _reject(reason: str) -> None:
            stats["rejected"] += 1
            if not dry_run:
                append_ledger({
                    "ts": time.time(), "event": "draft_rejected",
                    "tweet_id": cand.get("tweet_id"), "url": cand.get("url"),
                    "author": cand.get("author"), "reason": reason,
                })

        if res.get("skip"):
            _reject("model skip")
            continue
        if res.get("fallback") or not res.get("text"):
            _reject(f"no-usable-draft:{','.join(res.get('errors', []))[:120]}")
            continue

        draft_text = res["text"]
        if _LINK_RE.search(draft_text):
            _reject("link in body")
            continue
        this_mentions = mentions_cdpilot(draft_text)
        if this_mentions and mentions_left <= 0:
            _reject("cdpilot mention budget exhausted")
            continue
        ok, why = _novelty.check(draft_text, DATA, days=30)
        if not ok:
            _reject(f"novelty:{why}")
            continue

        if dry_run:
            stats["queued"] += 1
            continue

        draft = {
            "id": f"pain-reply-{cand['tweet_id']}",
            "kind": "reply",
            "to": cand["url"],
            "text": draft_text,
            "context": f"pain reply to @{cand.get('author')} (pain_hunter)",
            "source": "pain_hunter",
            "target_created_ts": int(cand.get("created_ts") or 0) or None,
        }

        sys.path.insert(0, str(Path(__file__).parent))
        import telegram_bridge as tb  # type: ignore  # queue helpers only, no Telegram
        if tb.auto_post_enabled():
            tb.auto_queue_draft(draft, idx=idx)
            stats["queued"] += 1
        else:
            DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
            (DRAFTS_DIR / f"{draft['id']}.json").write_text(
                json.dumps(draft, ensure_ascii=False, indent=2))
            stats["drafts_written"] += 1

        daily["items"].append({
            "tweet_id": cand["tweet_id"], "author": cand.get("author"),
            "mentions_cdpilot": this_mentions, "queued_at": int(time.time()),
        })
        append_ledger({
            "ts": time.time(), "event": "draft_accepted",
            "tweet_id": cand.get("tweet_id"), "url": cand.get("url"),
            "author": cand.get("author"), "text": draft_text,
            "mentions_cdpilot": this_mentions, "engine": res.get("engine"),
        })

    if not dry_run:
        save_daily(date_str, daily)
    return stats


# ── weekly digest ──

def build_digest(days: int = 7) -> dict:
    rows = [r for r in iter_ledger(days) if r.get("event") not in ("draft_rejected", "draft_accepted")]
    total = len(rows)
    class_counts: dict[str, int] = {}
    first_person = 0
    missing: dict[str, dict] = {}
    query_counts: dict[str, int] = {}

    for r in rows:
        cls = r.get("classification") or {}
        name = cls.get("class") or "unclassified"
        class_counts[name] = class_counts.get(name, 0) + 1
        if cls.get("first_person_pain"):
            first_person += 1
        if cls.get("missing_capability"):
            mc = cls["missing_capability"]
            entry = missing.setdefault(mc, {"count": 0, "example_urls": []})
            entry["count"] += 1
            if r.get("url") and len(entry["example_urls"]) < 2:
                entry["example_urls"].append(r["url"])
        q = r.get("query")
        if q:
            query_counts[q] = query_counts.get(q, 0) + 1

    top_queries = sorted(query_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]

    zero_signal: list[str] = []
    try:
        cfg = load_pain_config()
        for q in cfg.get("queries", []):
            if q["q"] not in query_counts:
                zero_signal.append(q["q"])
    except Exception:
        pass

    first_person_ratio = round(first_person / total, 3) if total else 0.0

    return {
        "days": days, "total": total, "class_counts": class_counts,
        "first_person": first_person, "first_person_ratio": first_person_ratio,
        "missing_capabilities": missing, "top_queries": top_queries,
        "zero_signal_queries": zero_signal,
    }


def _write_digest_md(digest: dict) -> Path:
    now = datetime.now()
    week = now.isocalendar()[1]
    path = PAINS_DIR / f"haftalik-{now.strftime('%Y')}-{week:02d}.md"
    lines = [f"# Haftalık Sorun Özeti — {now.strftime('%Y-%m-%d')} (hafta {week})",
             "", f"Son {digest['days']} gün, {digest['total']} kayıt, "
             f"first-person oranı %{digest['first_person_ratio'] * 100:.1f}.", ""]
    lines.append("## Sınıf başına sayı")
    for name, n in sorted(digest["class_counts"].items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"- {name}: {n}")
    lines.append("")
    lines.append("## Eksik yetenekler")
    if digest["missing_capabilities"]:
        for mc, info in sorted(digest["missing_capabilities"].items(), key=lambda kv: kv[1]["count"], reverse=True):
            urls = " ".join(info["example_urls"])
            lines.append(f"- {mc} ({info['count']}): {urls}")
    else:
        lines.append("- yok")
    lines.append("")
    lines.append("## En çok sinyal getiren sorgular")
    for q, n in digest["top_queries"]:
        lines.append(f"- \"{q}\": {n}")
    lines.append("")
    lines.append("## Hiç sinyal getirmeyen sorgular (budama adayı)")
    if digest["zero_signal_queries"]:
        for q in digest["zero_signal_queries"]:
            lines.append(f"- \"{q}\"")
    else:
        lines.append("- yok")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    return path


def run_digest() -> dict:
    digest = build_digest(days=7)
    path = _write_digest_md(digest)
    top_missing = sorted(digest["missing_capabilities"].items(),
                          key=lambda kv: kv[1]["count"], reverse=True)[:1]
    missing_note = f"Eksik: {top_missing[0][0]} ({top_missing[0][1]['count']})" if top_missing else "Eksik: yok"
    summary = (f"Haftalık sorun özeti: {digest['total']} kayıt, "
               f"%{digest['first_person_ratio'] * 100:.0f} first-person. {missing_note}.")
    _notify.notify("Haftalık sorun özeti", summary, priority="dusuk", tags=["chart"])
    return {"status": "ok", "path": str(path), "digest": digest}


def notify_hits(pain_candidates: list[dict], stats: dict) -> bool:
    """One routine push per run with first-person pain hits (tap = top hit).

    Replies are sent by the poster, which pushes each one with its link; this
    covers the hits themselves — including the ones the daily cap left alone.
    """
    if not pain_candidates:
        return False
    lines = [f"@{c.get('author')}: {(c.get('text') or '')[:90]}"
             for c in pain_candidates[:5]]
    if len(pain_candidates) > 5:
        lines.append(f"… +{len(pain_candidates) - 5}")
    queued = stats.get("queued", 0) + stats.get("drafts_written", 0)
    note = f"{queued} yanıt kuyrukta"
    if queued < len(pain_candidates):
        note += f", günlük sınır {DAILY_REPLY_CAP} / reddedilen {stats.get('rejected', 0)}"
    return _notify.notify(
        f"Pain hunter: {len(pain_candidates)} sorun", note + "\n" + "\n".join(lines),
        url=pain_candidates[0].get("url"), priority="dusuk", tags=["mag"],
        actions=[{"label": "2. sorun", "url": pain_candidates[1].get("url")}]
        if len(pain_candidates) > 1 and pain_candidates[1].get("url") else None,
    )


# ── search (network — never exercised by tests) ──

async def _get_client() -> Any:
    sys.path.insert(0, str(Path(__file__).parent))
    import _twikit_patch  # noqa: F401
    from twikit import Client  # type: ignore
    client = Client(LANG)
    client.load_cookies(str(COOKIES_PATH))
    return client


async def _search_one(client, q: dict) -> list[dict]:
    # Queries go out verbatim. Measured on the live search, 2026-09-27:
    #   cookies keep expiring      -> 2 results, 1 real pain (the one we wanted)
    #   "cookies keep expiring"    -> 0 results (people don't write our phrase)
    #   (a OR b) (c OR d) ...      -> 20 results, nearly all noise
    # X ANDs bare words, so short specific word sets carry the precision;
    # the classifier does the rest. Quote or add operators per query in
    # pain-queries.json only when a measurement says it helps.
    out: list[dict] = []
    try:
        tweets = await client.search_tweet(q["q"], "Latest", count=20)
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate limit" in msg.lower():
            raise RateLimited(msg) from e
        _log(f"pain search '{q['q']}' fail: {e}")
        return out
    for tw in tweets or []:
        try:
            text = (tw.text or "").strip()
            if not text:
                continue
            created = tw.created_at_datetime.timestamp() if tw.created_at_datetime else 0
            user = tw.user
            handle = getattr(user, "screen_name", "?")
            out.append({
                "tweet_id": tw.id,
                "url": f"https://x.com/{handle}/status/{tw.id}",
                "author": handle,
                "author_followers": getattr(user, "followers_count", 0) or 0,
                "text": text[:280],
                "created_ts": created,
                "hours_old": round((time.time() - created) / 3600.0, 1) if created else 999,
                "query": q["q"],
            })
        except Exception as e:
            _log(f"pain normalize fail: {e}")
    return out


async def main_async(dry_run: bool = False) -> dict:
    cfg = load_pain_config()
    queries = next_queries(cfg["queries"], CURSOR_PATH, n=QUERIES_PER_RUN, persist=not dry_run)
    if not COOKIES_PATH.exists():
        return {"status": "no_cookies"}

    client = await _get_client()
    all_candidates: list[dict] = []
    rate_limited = False
    for q in queries:
        try:
            all_candidates.extend(await _search_one(client, q))
        except RateLimited as e:
            _log(f"rate limited — stopping cycle: {e}")
            rate_limited = True
            break
        await asyncio.sleep(SEARCH_GAP_S)

    now = time.time()
    seen = load_seen(SEEN_PATH)
    negative_terms = cfg.get("negative_terms", [])
    negative_authors = {a.lower() for a in cfg.get("negative_authors", [])}
    filtered_counts: dict[str, int] = {}
    survivors: list[dict] = []
    for cand in all_candidates:
        ok, reason = passes_filters(cand, seen, negative_terms, negative_authors, now)
        if not ok:
            filtered_counts[reason] = filtered_counts.get(reason, 0) + 1
            continue
        if not dry_run:
            seen[cand["tweet_id"]] = now
        survivors.append(cand)

    if not dry_run:
        save_seen(SEEN_PATH, prune_seen(seen, now))

    classified, unclassified_n = classify_candidates(
        survivors, cfg["classes"], now, dry_run=dry_run)

    pain_candidates = [c for c in classified
                       if c["classification"].get("first_person_pain")]
    pain_candidates.sort(key=lambda c: c.get("created_ts", 0), reverse=True)
    reply_stats = run_replies(pain_candidates, dry_run=dry_run)
    if not dry_run:
        try:
            notify_hits(pain_candidates, reply_stats)
        except Exception as e:  # noqa: BLE001
            _log(f"ntfy hits push failed: {e!r}")

    return {
        "status": "rate_limited" if rate_limited else "ok",
        "queries_run": [q["q"] for q in queries],
        "scanned": len(all_candidates),
        "filtered": filtered_counts,
        "classified": len(classified),
        "unclassified": unclassified_n,
        **reply_stats,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--digest", action="store_true")
    args = p.parse_args()
    if args.digest:
        result = run_digest()
    else:
        result = asyncio.run(main_async(dry_run=args.dry_run))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
