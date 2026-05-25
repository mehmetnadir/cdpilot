#!/usr/bin/env python3
"""reply_drafter.py — AI-generated reply drafts using Claude CLI (subscription).

Uses `claude -p` (Claude Code CLI) — no API key needed, covered by Pro subscription.
System prompt encodes the cdpilot reply-tone profile (xbot/reply-tone.md):
  max 2 sentences, no helpful-bot tone, curiosity hook, peer voice,
  match input language (TR/EN), no URLs in body.

Falls back to a static template if claude CLI is unavailable.

CLI:
  python reply_drafter.py draft \\
      --incoming "their text" \\
      --parent "our original tweet" \\
      [--author "@username"] \\
      [--lang en|tr]

Returns JSON to stdout:
  {"draft_en": "...", "draft_tr": "...", "model": "claude-haiku-4-5", "cost_usd": 0}
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
LOG_FILE = DATA / "logs" / "reply-drafter.log"

CLAUDE_BIN = os.environ.get("CDPILOT_CLAUDE_BIN", "claude")
MODEL = os.environ.get("CDPILOT_REPLY_MODEL", "claude-haiku-4-5")

SYSTEM_PROMPT = """You are drafting a reply tweet for the @cdpilot_dev account.

cdpilot is an open-source browser automation CLI built on raw CDP (Chrome DevTools
Protocol) — zero deps, stealth + adaptive escalation, currently at v0.8.0.
Audience: dev community (browser automation, anti-bot, agents).

REPLY TONE — strict rules:
1. MAX 2 sentences. Usually 1. NEVER exceed 200 characters.
2. NO helpful-bot phrases: "great question", "happy to help", "hope this helps",
   "let me know if". NO bullet points or lists.
3. End with a curiosity hook: question, observation, or mild provocation.
4. Latch onto ONE specific technical detail from their reply. No generic platitudes.
5. Lowercase-prevailing, conversational shorthand (yeah, fair, tho) OK.
6. Emoji only if they used one (max 1).
7. NEVER put URLs in the body. Never link to anything.
8. Match their language: if they wrote in Turkish, reply Turkish. Else English.
9. Cool, peer voice — not aloof, not eager. Don't suck up, don't lecture.

Examples of good replies (EN):
  "yeah — raw CDP makes nested-frame traversal cheaper than playwright actually. specific timeout you're hitting?"
  "fair. cdpilot is for the 5% where you're fighting the framework, not using it. which side are you on usually?"

OUTPUT FORMAT: respond with the reply text ONLY. No quotes around it, no
preamble, no explanation. Just the tweet body."""


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _claude_available() -> bool:
    return shutil.which(CLAUDE_BIN) is not None


def _build_user_prompt(incoming: str, parent: str | None, author: str | None,
                       lang: str | None) -> str:
    lang_hint = ""
    if lang == "tr":
        lang_hint = "\nReply IN TURKISH (their language).\n"
    elif lang == "en":
        lang_hint = "\nReply in English.\n"

    parent_block = ""
    if parent:
        parent_block = f"OUR ORIGINAL TWEET:\n{parent}\n\n"

    author_block = f"({author} wrote)" if author else ""

    return (
        f"{parent_block}"
        f"THEIR REPLY {author_block}:\n{incoming}\n\n"
        f"{lang_hint}"
        f"Now write ONE tweet (max 2 sentences) replying to them."
    )


def _static_fallback(incoming: str, lang: str | None) -> str:
    """Used only when claude CLI is unavailable."""
    if lang == "tr":
        return "ilginç. spesifik kısmı ne oldu?"
    return "interesting. what part specifically?"


def draft(incoming: str, parent: str | None = None, author: str | None = None,
          lang: str | None = None, timeout: int = 120) -> dict:
    if not _claude_available():
        text = _static_fallback(incoming, lang)
        _log(f"claude unavailable → fallback: {text}")
        return {"draft": text, "model": "fallback-static", "fallback": True}

    user_prompt = _build_user_prompt(incoming, parent, author, lang)
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", "--model", MODEL, "--append-system-prompt", SYSTEM_PROMPT],
            input=user_prompt, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _log(f"claude CLI timeout after {timeout}s")
        return {"draft": _static_fallback(incoming, lang),
                "model": "fallback-timeout", "fallback": True}
    except Exception as e:
        _log(f"claude CLI exception: {type(e).__name__}: {e}")
        return {"draft": _static_fallback(incoming, lang),
                "model": f"fallback-{type(e).__name__}", "fallback": True}

    raw = (proc.stdout or "").strip()
    if proc.returncode != 0 or not raw:
        err = (proc.stderr or "")[:200]
        _log(f"claude CLI exit={proc.returncode}: {err}")
        return {"draft": _static_fallback(incoming, lang),
                "model": "fallback-nonzero", "fallback": True, "stderr": err}

    # Clean up common LLM artifacts — surrounding quotes, leading 'Reply:' etc.
    cleaned = raw.strip().strip('"').strip("'")
    for prefix in ("Reply:", "reply:", "Tweet:", "Response:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    # Trim to ≤270 chars to stay under Twitter weighted limit safely
    if len(cleaned) > 270:
        cleaned = cleaned[:267].rsplit(" ", 1)[0] + "…"
    _log(f"drafted ({len(cleaned)} chars): {cleaned}")
    return {"draft": cleaned, "model": MODEL, "fallback": False}


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s_d = sub.add_parser("draft", help="generate an AI reply draft")
    s_d.add_argument("--incoming", required=True, help="their reply text")
    s_d.add_argument("--parent", default=None, help="our original tweet text")
    s_d.add_argument("--author", default=None, help="@username")
    s_d.add_argument("--lang", choices=["en", "tr"], default=None)
    s_d.add_argument("--timeout", type=int, default=60)
    args = p.parse_args()
    if args.cmd == "draft":
        out = draft(args.incoming, parent=args.parent, author=args.author,
                    lang=args.lang, timeout=args.timeout)
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
