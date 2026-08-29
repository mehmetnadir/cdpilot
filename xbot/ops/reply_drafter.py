#!/usr/bin/env python3
"""reply_drafter.py — AI-generated reply drafts, engine chain with a real health check.

Engines, in order:
  1. `claude -p` (Claude Code CLI, subscription quota, no API key)
  2. NVIDIA NIM (free tier, OpenAI-compatible, API key — survives OAuth expiry)

System prompt encodes the cdpilot reply-tone profile (xbot/reply-tone.md):
  max 2 sentences, no helpful-bot tone, curiosity hook, peer voice,
  match input language (TR/EN), no URLs in body.

The static fallback is a LAST resort and is flagged `fallback: true`; unattended
callers must refuse to post it. 2026-08 lesson: srv21's claude token expired on
21 June, availability was checked with shutil.which() — presence, not health —
so for two months every reply degraded to the same canned sentence and the bot
looked alive while posting spam. Health is now inferred from real calls and
remembered for a short window, so one dead engine costs one timeout, not every
draft of the day.

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
import urllib.error
import urllib.request
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import bot_home  # noqa: E402

DATA = bot_home()
LOG_FILE = DATA / "logs" / "reply-drafter.log"

CLAUDE_BIN = os.environ.get("CDPILOT_CLAUDE_BIN", "claude")
MODEL = os.environ.get("CDPILOT_REPLY_MODEL", "claude-haiku-4-5")

# `claude setup-token` prints a long-lived token that still has to be installed
# where the CLI actually runs. Keeping it in a file (not a shell profile) means
# systemd timers see it too — cron jobs never source ~/.bashrc.
CLAUDE_TOKEN_FILE = Path(os.environ.get(
    "CDPILOT_CLAUDE_TOKEN_FILE", str(DATA / "state" / "claude-oauth-token")))

# NVIDIA NIM (second engine) — OpenAI-compatible, free tier.
NIM_BASE = os.environ.get("CDPILOT_NIM_BASE", "https://integrate.api.nvidia.com/v1")
NIM_KEY_FILE = Path(os.environ.get(
    "CDPILOT_NIM_KEY_FILE", str(DATA / "state" / "nvidia-api-key")))
# Model ids are resolved against the live catalog rather than pinned: NIM's
# lineup rotates, and a hardcoded id turns into a silent 404 months later.
# Ordered by measured behaviour on srv21 (2026-08-28, same reply prompt):
#   kimi-k3 13.4s complete · deepseek-v4-flash 76.6s truncated
#   gpt-oss-120b 67.4s content:null · kimi-k2.6 404 despite being in the catalog.
# The 404 is why this is a list and not a pinned id: being listed does not mean
# being served, so candidates are tried in order until one answers.
NIM_PREFERENCE = ("moonshotai/kimi-k3", "deepseek-ai/deepseek-v4-pro",
                  "openai/gpt-oss-120b", "deepseek-ai/deepseek-v4-flash")
NIM_CATALOG_CACHE = DATA / "state" / "nim-catalog.json"
NIM_CATALOG_TTL = 24 * 3600

# Remembered engine failures — path -> unix ts of last failure.
ENGINE_HEALTH = DATA / "state" / "drafter-health.json"
ENGINE_COOLDOWN_S = int(os.environ.get("CDPILOT_ENGINE_COOLDOWN", "3600"))

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

VOICE_RULES_DOC = Path(os.environ.get(
    "CDPILOT_VOICE_RULES", str(Path(__file__).resolve().parent.parent / "voice-rules.md")))

# Mechanically enforced — a model that ignores the prompt gets rejected here.
BANNED_SUBSTRINGS = (
    "\u2014", "\u2013", " -- ",
    "leverage", "utilize", "facilitate", "streamline", "robust", "seamless",
    "delve", "unlock", "harness", "foster", "cultivate",
    "fundamentally", "essentially", "ultimately", "crucially", "notably",
    "landscape", "ecosystem", "paradigm", "realm", "tapestry",
    "game-changer", "deep dive", "needle-mover",
    "great question", "happy to help", "hope this helps", "let me know",
    "at the end of the day", "in today's fast-paced world",
    "it's not just", "its not just",
)


def _voice_rules() -> str:
    try:
        return VOICE_RULES_DOC.read_text()
    except Exception:
        return ""


def _system_prompt() -> str:
    """Base tone profile plus the editable voice-rules doc, so the writing
    doctrine can be tuned without touching code."""
    rules = _voice_rules()
    if not rules:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\n--- VOICE RULES (binding) ---\n{rules}"


def _voice_lint(text: str) -> tuple[str, list[str]]:
    """Return (repaired_text, unfixable_issues).

    Dashes are repaired mechanically because the fix is unambiguous. Vocabulary
    hits are NOT auto-rewritten — swapping words changes meaning — so they are
    reported and the draft is dropped, falling through to the next engine or to
    the manual card.
    """
    repaired = text.replace("\u2014", "..").replace("\u2013", "..").replace(" -- ", " .. ")
    low = repaired.lower()
    issues = [b for b in BANNED_SUBSTRINGS
              if b not in ("\u2014", "\u2013", " -- ") and b in low]
    if repaired.count("#") > 1:
        issues.append("multiple hashtags")
    if len(repaired) > 270:
        issues.append(f"too long ({len(repaired)})")
    return repaired, issues


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _health() -> dict:
    try:
        return json.loads(ENGINE_HEALTH.read_text())
    except Exception:
        return {}


def _mark_unhealthy(engine: str) -> None:
    h = _health()
    h[engine] = int(time.time())
    ENGINE_HEALTH.parent.mkdir(parents=True, exist_ok=True)
    ENGINE_HEALTH.write_text(json.dumps(h))


def _mark_healthy(engine: str) -> None:
    h = _health()
    if h.pop(engine, None) is not None:
        ENGINE_HEALTH.write_text(json.dumps(h))


def _in_cooldown(engine: str) -> bool:
    return (time.time() - _health().get(engine, 0)) < ENGINE_COOLDOWN_S


def _clean(raw: str) -> str:
    """Strip LLM artifacts and fit the weighted tweet limit."""
    cleaned = raw.strip().strip('"').strip("'")
    for prefix in ("Reply:", "reply:", "Tweet:", "Response:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    # Reasoning models sometimes emit a think block before the answer.
    if "</think>" in cleaned:
        cleaned = cleaned.rsplit("</think>", 1)[1].strip()
    if len(cleaned) > 270:
        cleaned = cleaned[:267].rsplit(" ", 1)[0] + "…"
    return cleaned


def _claude_available() -> bool:
    """Binary present AND not in a failure cooldown.

    shutil.which() alone was the 2026-08 blind spot: the binary sat there
    perfectly installed while its token had been expired for two months.
    """
    return shutil.which(CLAUDE_BIN) is not None and not _in_cooldown("claude")


def _claude_env() -> dict:
    """Environment for the claude subprocess, with the stored token if we have one."""
    env = dict(os.environ)
    if "CLAUDE_CODE_OAUTH_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env:
        try:
            tok = CLAUDE_TOKEN_FILE.read_text().strip()
        except Exception:
            tok = ""
        if tok:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    return env


def _nim_key() -> str | None:
    key = os.environ.get("NVIDIA_API_KEY")
    if key:
        return key.strip()
    try:
        return NIM_KEY_FILE.read_text().strip() or None
    except Exception:
        return None


def _nim_models() -> list[str]:
    """Ordered candidate models — first that actually answers wins."""
    pinned = os.environ.get("CDPILOT_NIM_MODEL")
    if pinned:
        return [pinned]
    ids = []
    try:
        cached = json.loads(NIM_CATALOG_CACHE.read_text())
        if time.time() - cached.get("fetched_at", 0) < NIM_CATALOG_TTL:
            ids = cached.get("ids", [])
    except Exception:
        ids = []
    if not ids:
        key = _nim_key()
        if not key:
            return []
        try:
            req = urllib.request.Request(
                f"{NIM_BASE}/models",
                headers={"Authorization": f"Bearer {key}", "accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                ids = [m["id"] for m in json.loads(resp.read()).get("data", [])]
        except Exception as e:
            _log(f"nim catalog fetch failed: {e!r}")
            return []
        NIM_CATALOG_CACHE.parent.mkdir(parents=True, exist_ok=True)
        NIM_CATALOG_CACHE.write_text(
            json.dumps({"fetched_at": int(time.time()), "ids": ids}))
    ordered = []
    for want in NIM_PREFERENCE:
        for mid in ids:
            if mid.startswith(want) and mid not in ordered:
                ordered.append(mid)
    return ordered


def _nim_draft(user_prompt: str, timeout: int) -> tuple[str | None, str]:
    """Second engine. Returns (draft, error_label)."""
    key = _nim_key()
    if not key:
        return None, "nim-no-key"
    models = _nim_models()
    if not models:
        return None, "nim-no-model"
    last = "nim-no-candidate"
    for model in models:
        text, last = _nim_call(key, model, user_prompt, timeout)
        if text:
            return text, model
        _log(f"nim {model} unusable ({last}) — trying next candidate")
    return None, last


def _nim_call(key: str, model: str, user_prompt: str,
              timeout: int) -> tuple[str | None, str]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": _system_prompt()},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.8,
        "max_tokens": 300,
    }).encode()
    req = urllib.request.Request(
        f"{NIM_BASE}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except Exception as e:
        _log(f"nim call failed: {e!r}")
        return None, f"nim-{type(e).__name__}"
    try:
        msg = payload["choices"][0]["message"]
    except (KeyError, IndexError):
        return None, "nim-shape"
    # Reasoning models leave `content` null and put the answer in
    # `reasoning_content` (observed on gpt-oss-120b).
    text = msg.get("content") or msg.get("reasoning_content") or ""
    cleaned, issues = _voice_lint(_clean(text))
    if not cleaned:
        return None, "nim-empty"
    if issues:
        _log(f"nim/{model} draft rejected by voice lint {issues}: {cleaned}")
        return None, f"nim-lint:{','.join(issues)[:40]}"
    _log(f"drafted via nim/{model} ({len(cleaned)} chars): {cleaned}")
    return cleaned, model


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
    user_prompt = _build_user_prompt(incoming, parent, author, lang)
    errors: list[str] = []

    # ── Engine 1: claude CLI (subscription quota) ──
    if _claude_available():
        try:
            proc = subprocess.run(
                [CLAUDE_BIN, "-p", "--model", MODEL,
                 "--append-system-prompt", _system_prompt()],
                input=user_prompt, capture_output=True, text=True, timeout=timeout,
                env=_claude_env(),
            )
            raw = (proc.stdout or "").strip()
            if proc.returncode == 0 and raw:
                cleaned, issues = _voice_lint(_clean(raw))
                if cleaned and not issues:
                    _mark_healthy("claude")
                    _log(f"drafted via claude ({len(cleaned)} chars): {cleaned}")
                    return {"draft": cleaned, "model": MODEL, "engine": "claude",
                            "fallback": False}
                if issues:
                    _mark_healthy("claude")  # engine is alive, the draft is not
                    _log(f"claude draft rejected by voice lint {issues}: {cleaned}")
                    errors.append(f"claude-lint:{','.join(issues)[:60]}")
            err = (proc.stderr or "")[:200]
            _log(f"claude CLI exit={proc.returncode}: {err}")
            errors.append(f"claude-exit{proc.returncode}")
            _mark_unhealthy("claude")
        except subprocess.TimeoutExpired:
            _log(f"claude CLI timeout after {timeout}s")
            errors.append("claude-timeout")
            _mark_unhealthy("claude")
        except Exception as e:
            _log(f"claude CLI exception: {type(e).__name__}: {e}")
            errors.append(f"claude-{type(e).__name__}")
            _mark_unhealthy("claude")
    else:
        reason = "cooldown" if shutil.which(CLAUDE_BIN) else "not installed"
        _log(f"claude skipped ({reason})")
        errors.append(f"claude-{reason.replace(' ', '-')}")

    # ── Engine 2: NVIDIA NIM (API key, immune to OAuth expiry) ──
    if not _in_cooldown("nim"):
        text, label = _nim_draft(user_prompt, timeout=min(timeout, 90))
        if text:
            _mark_healthy("nim")
            return {"draft": text, "model": label, "engine": "nim", "fallback": False}
        errors.append(label)
        _mark_unhealthy("nim")
    else:
        errors.append("nim-cooldown")

    # ── No engine produced anything ──
    # The static line is identical for every target, so unattended callers
    # (search_respond, engagement_scanner) must drop it rather than post it.
    text = _static_fallback(incoming, lang)
    _log(f"ALL ENGINES DOWN ({', '.join(errors)}) → static fallback, do not auto-post")
    return {"draft": text, "model": "fallback-static", "engine": None,
            "fallback": True, "errors": errors}


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
