#!/usr/bin/env python3
"""news_flood.py — turn one AI/dev news item into a 3-4 tweet flood.

The point is translation, not relay. A link with "interesting" under it adds
nothing; the account's value is saying what a thing actually means for someone
who builds, in words they already use, plus a take we can defend.

Shape (enforced, not suggested):
  1. what happened, in plain language — no jargon, no link
  2. the mechanism: what actually changes, concretely
  3. our take: what we would do, or what it costs — with evidence
  4. optional: the honest caveat, or the question we genuinely have

Source: discoveries/<date>.json produced by discovery_scan.py.
Output:  drafts/flood-<date>-<slug>.json (kind=thread) — never auto-posted;
         Nadir approves it like any other thread. An ntfy "Onay bekliyor"
         notice (tap = the source) tells him one is waiting.

Usage:
  python news_flood.py                 # pick today's best item, draft a flood
  python news_flood.py --dry-run       # show the chosen item, no generation
  python news_flood.py --list          # rank today's candidates
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _novelty  # noqa: E402
from _paths import bot_home  # noqa: E402
import _notify  # noqa: E402
from _relevance import off_limits, relevance  # noqa: E402
from reply_drafter import generate, _voice_lint  # noqa: E402

DATA = bot_home()
DISCOVERIES = DATA / "discoveries"
DRAFTS = DATA / "drafts"
LOG_FILE = DATA / "logs" / "news-flood.log"
VOICE_RULES = Path(__file__).resolve().parent.parent / "voice-rules.md"

MIN_TWEETS, MAX_TWEETS = 3, 4

SYSTEM_PROMPT = """You write a short X (Twitter) flood for @cdpilot_dev.

WHO THIS ACCOUNT IS
A developer who builds software with AI every day, reports what actually made
the work easier, and starts discussions worth having. Not a news account: a
practitioner reacting to news with something only a practitioner would say.

THE JOB
Turn ONE piece of AI/developer news into 3 or 4 tweets that a working developer
who has not read the source can follow completely.

  Tweet 1 — what happened, in plain language. No jargon, no vendor phrasing, no
            link. Someone scrolling must understand it without clicking.
  Tweet 2 — what actually changes, concretely. The mechanism, not the adjective.
  Tweet 3 — our take: what we would do about it, or what it costs, or where it
            breaks. This is the reason the flood exists. Take a position.
  Tweet 4 — OPTIONAL. The honest caveat, or the question we genuinely have.
            Leave it out rather than padding.

HARD RULES
- Each tweet stands alone and is under 260 characters.
- No em dashes. Use ".." as a soft pause.
- No hype vocabulary: game-changer, revolutionary, insane, mind-blowing,
  "this changes everything". No thread emoji, no "🧵", no "1/4" numbering.
- No links in any tweet.
- Never invent a technical claim. If the source does not say it, do not say it.
- Never claim experience we do not have. No "after running X for years". Say
  what we measured or what we hit: "we measured", "our bench scored", "we hit".
- Do not pitch cdpilot. It may appear only as evidence of something we measured.
- Specific numbers beat adjectives.
- Lowercase-casual is fine. Capitalize real names (Anthropic, Claude, GitHub).

OUTPUT FORMAT
A JSON array of 3 or 4 strings, nothing else. No markdown fence, no commentary.
Example: ["first tweet", "second tweet", "third tweet"]

If the item is not worth a flood — a routine release note, a rumor, something
with no consequence for people who build — output exactly SKIP."""


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    sys.stderr.write(msg + "\n")


def _latest_discovery() -> dict | None:
    files = sorted(DISCOVERIES.glob("*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text())
    except Exception as e:
        _log(f"discovery unreadable: {e!r}")
        return None


def candidates(payload: dict) -> list[dict]:
    """Flatten a discovery payload into ranked, on-topic candidates."""
    out: list[dict] = []
    for item in payload.get("hn", []):
        out.append({"source": "hn", "title": item.get("title", ""),
                    "url": item.get("url") or item.get("hn_url", ""),
                    "signal": item.get("score", 0) + item.get("comments", 0)})
    for item in payload.get("github", []):
        out.append({"source": "github",
                    "title": f"{item.get('name', '')}: {item.get('description', '')}".strip(": "),
                    "url": item.get("url", ""), "signal": item.get("stars", 0) / 10})
    for item in payload.get("arxiv", []):
        out.append({"source": "arxiv", "title": item.get("title", ""),
                    "url": item.get("url", ""), "signal": 5})

    ranked = []
    for c in out:
        title = c["title"]
        if not title or off_limits(title):
            continue
        fit = relevance(title)[0]
        if fit == 0:
            continue
        c["fit"] = fit
        c["score"] = round(fit * 10 + min(c["signal"], 100) / 10, 2)
        ranked.append(c)
    ranked.sort(key=lambda c: c["score"], reverse=True)
    return ranked


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return "-".join(s.split("-")[:5]) or "item"


def _validate_flood(raw: str) -> tuple[str, list[str]]:
    """The model must return a JSON array of 3-4 clean tweets."""
    text = (raw or "").strip()
    if text.strip().upper() == "SKIP":
        return text, []
    fence = re.search(r"\[.*\]", text, re.S)
    if not fence:
        return text, ["not a JSON array"]
    try:
        tweets = json.loads(fence.group(0))
    except ValueError as e:
        return text, [f"bad JSON: {e}"]
    if not isinstance(tweets, list) or not all(isinstance(t, str) for t in tweets):
        return text, ["not an array of strings"]
    if not MIN_TWEETS <= len(tweets) <= MAX_TWEETS:
        return text, [f"{len(tweets)} tweets, need {MIN_TWEETS}-{MAX_TWEETS}"]

    issues: list[str] = []
    cleaned: list[str] = []
    for i, t in enumerate(tweets, 1):
        fixed, tweet_issues = _voice_lint(t)
        if len(fixed) > 260:
            tweet_issues.append(f"tweet {i} too long ({len(fixed)})")
        issues += [f"t{i}:{msg}" for msg in tweet_issues]
        cleaned.append(fixed)
    return json.dumps(cleaned, ensure_ascii=False), issues


def build(item: dict, timeout: int = 120) -> dict:
    rules = ""
    try:
        rules = VOICE_RULES.read_text()
    except Exception:
        pass
    system = SYSTEM_PROMPT + (f"\n\n--- VOICE RULES (binding) ---\n{rules}" if rules else "")
    user = (f"SOURCE: {item['source']}\n"
            f"TITLE: {item['title']}\n"
            f"URL (context only, never quote it): {item.get('url', '')}\n\n"
            "Write the flood.")
    # A 3-4 tweet flood needs room: at 300 tokens the JSON array was cut
    # mid-string and read as malformed output rather than a long answer.
    res = generate(system, user, timeout=timeout, validate=_validate_flood,
                   max_tokens=1200)
    if res.get("skip") or (res.get("text") or "").strip().upper() == "SKIP":
        return {"skip": True, "reason": "model judged it not worth a flood"}
    if not res.get("text"):
        return {"error": "no engine produced a flood", "errors": res.get("errors", [])}
    return {"tweets": json.loads(res["text"]), "engine": res.get("engine"),
            "model": res.get("model")}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--timeout", type=int, default=120)
    args = p.parse_args()

    payload = _latest_discovery()
    if not payload:
        print(json.dumps({"error": "no discoveries"}))
        sys.exit(1)
    ranked = candidates(payload)
    if args.list:
        for c in ranked[:10]:
            print(f"{c['score']:6.2f} [{c['source']}] {c['title'][:90]}")
        return
    if not ranked:
        print(json.dumps({"status": "no on-topic candidate today"}))
        return

    for cand in ranked[:5]:
        ok, why = _novelty.check(cand["title"], DATA)
        if not ok:
            _log(f"skip '{cand['title'][:60]}' — {why}")
            continue
        if args.dry_run:
            print(json.dumps({"picked": cand, "novelty": why}, ensure_ascii=False))
            return
        result = build(cand, timeout=args.timeout)
        if result.get("skip"):
            _log(f"model skipped '{cand['title'][:60]}'")
            continue
        if result.get("error"):
            print(json.dumps(result))
            sys.exit(1)

        joined = " ".join(result["tweets"])
        ok, why = _novelty.check(joined, DATA)
        if not ok:
            _log(f"generated flood rejected as repetitive — {why}")
            continue

        DRAFTS.mkdir(parents=True, exist_ok=True)
        date = datetime.now().strftime("%Y-%m-%d")
        out = DRAFTS / f"flood-{date}-{_slug(cand['title'])}.json"
        out.write_text(json.dumps({
            "id": out.stem,
            "kind": "thread",
            "source": f"news_flood/{cand['source']}",
            "context": f"news flood: {cand['title'][:120]}",
            "origin_url": cand.get("url", ""),
            "engine": result.get("engine"),
            "model": result.get("model"),
            "texts": result["tweets"],
        }, ensure_ascii=False, indent=2))
        _log(f"wrote {out.name} ({len(result['tweets'])} tweets, {result.get('model')})")
        try:
            _notify.notify_waiting(
                f"thread ({len(result['tweets'])} tweet)",
                reason=f"Haber: {cand['title'][:120]}\nTaslak: drafts/{out.name}\n\n"
                       + "\n\n".join(result["tweets"])[:1800],
                context_url=cand.get("url") or None, compose=False,
            )
        except Exception as e:  # noqa: BLE001
            _log(f"ntfy notice failed: {e!r}")
        print(json.dumps({"draft": str(out), "tweets": result["tweets"]},
                         ensure_ascii=False, indent=2))
        return

    print(json.dumps({"status": "nothing novel and worth a flood today"}))


if __name__ == "__main__":
    main()
