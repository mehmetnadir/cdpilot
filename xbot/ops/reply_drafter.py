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
import re
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

SYSTEM_PROMPT = """You are drafting a reply tweet for @cdpilot_dev.

WHO THIS ACCOUNT IS
A developer who builds software with AI every day and talks about what actually
makes the work easier. Reads and tries things constantly, then reports what held
up and what did not. Starts and sustains real discussions: asks the question
they genuinely want answered, and engages with the answer.

cdpilot (an open-source browser automation CLI on raw CDP, zero deps) is
something this person built. It is evidence, not the subject. Mention it only
when it is the honest answer to what someone asked, at most once in a while,
never as a pitch in someone else's thread. An account that only talks about its
own product has nothing to say about the work.

WHEN NOT TO REPLY
Output exactly SKIP, alone, when any of these is true:
  - you have nothing specific to add beyond agreement or restatement
  - the tweet is a quiz, a poll, or a company milestone/announcement post
  - answering would require inventing a technical claim you are not sure of
  - the only reply available is a compliment
A reply that says nothing is worse than silence. SKIP is a good outcome, and it
is expected often.

REPLY RULES
1. MAX 2 sentences. Usually 1. NEVER exceed 200 characters.
2. NO helpful-bot phrases: "great question", "happy to help", "hope this helps",
   "let me know if". NO bullet points or lists.
3. Latch onto ONE specific thing they said. No generic platitudes.
4. End with a real question only when you would actually want the answer.
   A question mark is not a substitute for having something to say.
5. Bring something concrete: a number you measured, a failure mode you hit, a
   tradeoff you chose. Opinion without evidence is noise.
6. Never state a technical claim you cannot back. If unsure, say what you tried.
7. Lowercase-prevailing, conversational shorthand (yeah, fair, tho) OK.
8. Emoji only if they used one (max 1).
9. NEVER put URLs in the body. Never link to anything.
10. Match their language: if they wrote in Turkish, reply Turkish. Else English.
11. Peer voice: not aloof, not eager. Don't suck up, don't lecture, don't sell.

Examples of good replies (EN):
  "raw CDP makes nested-frame traversal cheaper than playwright here.. what timeout are you hitting?"
  "we measured 3 parallel as the ceiling, 5 gave 29 timeouts. did yours degrade gradually or fall over?"
  "the spoof was the tell for us: randomized plugin names scored worse than patching nothing at all."

OUTPUT FORMAT: the reply text ONLY, or the single word SKIP. No quotes, no
preamble, no explanation."""

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


# Phrases that only appear when the model narrates its own instructions instead
# of answering. Cheap insurance: one such draft reached @vercel's timeline.
LEAK_MARKERS = ("reply tweet for", "max 2 sentences", "banned vocabulary",
                "we need to craft", "the user wrote", "system prompt",
                "character limit", "output format")


def _looks_like_leaked_prompt(text: str) -> bool:
    low = (text or "").lower()
    return sum(1 for m in LEAK_MARKERS if m in low) >= 2


def _without_quotes(text: str) -> str:
    """Drop quoted spans before checking vocabulary.

    A reply about which AI cliches to watch for has to be able to name them:
    "my money's on \"delve\" but \"it's not just X, it's Y\" keeps sneaking past"
    is good writing, and the lint rejected it for containing the words it was
    discussing. Quoting is mention, not use.
    """
    return re.sub(r'"[^"]{1,80}"|\u201c[^\u201d]{1,80}\u201d|\'[^\']{2,80}\'', " ", text or "")


# First-person empirical claims. The drafting model has no access to anything
# we measured, so "we found X" from it is invented by construction — and it
# kept happening: "we found randomized plugin names were the biggest
# uniqueness signal", "we found replaying the same session with DOM snapshots
# caught more divergence" (2026-09). No bench record in the repo backs either.
# The maker's own story ("i built cdpilot after playwright kept...") is not a
# measurement and stays allowed. A real, backed finding is written by a human.
_UNBACKED_CLAIM = re.compile(
    r"\b(?:we|i)(?:'ve| have)? (?:found|tested|measured|benchmarked|noticed|"
    r"discovered|observed|learned)\b"
    r"|\bin our (?:tests?|benchmarks?|runs?|experiments?|data|numbers)\b"
    r"|\bour (?:benchmarks?|numbers|data|tests?) (?:show|showed|shows|suggest)\b"
    r"|\bwhen we (?:tried|tested|ran|measured)\b"
)


def _voice_lint(text: str) -> tuple[str, list[str]]:
    """Return (repaired_text, unfixable_issues).

    Dashes are repaired mechanically because the fix is unambiguous. Vocabulary
    hits are NOT auto-rewritten — swapping words changes meaning — so they are
    reported and the draft is dropped, falling through to the next engine or to
    the manual card.
    """
    repaired = text.replace("\u2014", "..").replace("\u2013", "..").replace(" -- ", " .. ")
    if _looks_like_leaked_prompt(repaired):
        return repaired, ["leaked prompt text"]
    low = _without_quotes(repaired).lower()
    issues = [b for b in BANNED_SUBSTRINGS
              if b not in ("\u2014", "\u2013", " -- ") and b in low]
    if _UNBACKED_CLAIM.search(low):
        issues.append("unbacked experience claim")
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
    """Two consecutive failures put an engine in cooldown, not one.

    A single timeout is often ours: a caller passing a tight deadline, or one
    slow request. Disabling a working engine for an hour over that costs more
    than the retry does — it happened while testing with a 20s budget.
    """
    h = _health()
    entry = h.get(engine)
    if isinstance(entry, dict):
        prior = entry.get("fails", 0)
    elif entry is None:
        prior = 0
    else:  # legacy bare timestamp from an older build
        prior = 1
    fails = prior + 1
    h[engine] = {"fails": fails, "since": int(time.time())}
    ENGINE_HEALTH.parent.mkdir(parents=True, exist_ok=True)
    ENGINE_HEALTH.write_text(json.dumps(h))


def _mark_healthy(engine: str) -> None:
    h = _health()
    if h.pop(engine, None) is not None:
        ENGINE_HEALTH.write_text(json.dumps(h))


def _in_cooldown(engine: str) -> bool:
    entry = _health().get(engine)
    if entry is None:
        return False
    if not isinstance(entry, dict):  # legacy: bare timestamp
        return (time.time() - entry) < ENGINE_COOLDOWN_S
    if entry.get("fails", 0) < 2:
        return False
    return (time.time() - entry.get("since", 0)) < ENGINE_COOLDOWN_S


def _is_skip(text: str) -> bool:
    """The model declining to reply. Silence beats a reply that says nothing."""
    stripped = (text or "").strip().strip('".\'').upper()
    return stripped == "SKIP"


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
        # Chopping at a character count ends the reply mid-thought — one went
        # into the queue reading "..which is why i…" (2026-09-08). Fall back to
        # the last complete sentence; if that leaves nothing usable, return the
        # over-length text so _voice_lint refuses it and another engine tries.
        cut = max(cleaned.rfind(m, 0, 270) for m in (". ", "! ", "? "))
        end = cleaned.rfind(".", 0, 270)
        cut = max(cut, end)
        if cut > 80:
            cleaned = cleaned[:cut + 1].strip()
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


def _nim_draft(user_prompt: str, timeout: int, system_prompt: str | None = None,
               validate=None, max_tokens: int = 300) -> tuple[str | None, str]:
    """Second engine. Returns (draft, error_label)."""
    key = _nim_key()
    if not key:
        return None, "nim-no-key"
    models = _nim_models()
    if not models:
        return None, "nim-no-model"
    last = "nim-no-candidate"
    for model in models:
        text, last = _nim_call(key, model, user_prompt, timeout,
                               system_prompt=system_prompt, validate=validate,
                               max_tokens=max_tokens)
        if text:
            return text, model
        if last == "skip":
            return None, "skip"  # a judgement, not a failure — don't shop around
        _log(f"nim {model} unusable ({last}) — trying next candidate")
    return None, last


def _nim_call(key: str, model: str, user_prompt: str, timeout: int,
              system_prompt: str | None = None, validate=None,
              max_tokens: int = 300) -> tuple[str | None, str]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system_prompt or _system_prompt()},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.8,
        "max_tokens": max_tokens,
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
    # `reasoning_content` is the model thinking out loud, NOT its answer.
    # Reading it as the draft put "We need to craft a reply tweet for
    # @cdpilot_dev account. Limit: max 2 sentences..." under a @vercel post on
    # 2026-08-29. A model that leaves `content` empty has not answered.
    text = msg.get("content") or ""
    if _is_skip(text):
        _log(f"nim/{model} returned SKIP — nothing worth adding")
        return None, "skip"
    if validate is not None:
        cleaned, issues = validate(text)
    else:
        cleaned, issues = _clean(text), []
    if not cleaned:
        return None, "nim-empty"
    if issues:
        _log(f"nim/{model} output rejected {issues}: {cleaned[:120]}")
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


def generate(system_prompt: str, user_prompt: str, timeout: int = 120,
             validate=None, max_tokens: int = 300) -> dict:
    """Run the engine chain for any prompt. Reply drafting is one caller of this.

    Returns {text, engine, model} on success, {skip: True} when the model
    declined, {fallback: True} when nothing answered. `validate(text)` may
    return (repaired_text, issues); a draft with issues is refused so the next
    engine gets a turn.
    """
    errors: list[str] = []

    def _check(raw: str):
        # _clean carries reply-shaped rules, including a 270-char trim. Applying
        # it before a caller's validator silently truncated a 4-tweet JSON array
        # into malformed output. A validator owns its own normalization.
        if validate is None:
            return _clean(raw), []
        return validate((raw or "").strip())

    # ── Engine 1: claude CLI (subscription quota) ──
    if _claude_available():
        try:
            proc = subprocess.run(
                [CLAUDE_BIN, "-p", "--model", MODEL,
                 "--append-system-prompt", system_prompt],
                input=user_prompt, capture_output=True, text=True, timeout=timeout,
                env=_claude_env(),
            )
            raw = (proc.stdout or "").strip()
            if proc.returncode == 0 and raw:
                if _is_skip(raw):
                    _mark_healthy("claude")
                    _log("claude returned SKIP — nothing worth adding")
                    return {"text": None, "engine": "claude", "skip": True,
                            "fallback": False}
                cleaned, issues = _check(raw)
                if cleaned and not issues:
                    _mark_healthy("claude")
                    _log(f"generated via claude ({len(cleaned)} chars)")
                    return {"text": cleaned, "model": MODEL, "engine": "claude",
                            "fallback": False}
                if issues:
                    _mark_healthy("claude")  # engine is alive, the draft is not
                    _log(f"claude output rejected {issues}: {cleaned[:120]}")
                    errors.append(f"claude-lint:{','.join(issues)[:60]}")
            else:
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
        text, label = _nim_draft(user_prompt, timeout=min(timeout, 150),
                                 system_prompt=system_prompt, validate=_check,
                                 max_tokens=max_tokens)
        if text:
            _mark_healthy("nim")
            return {"text": text, "model": label, "engine": "nim", "fallback": False}
        if label == "skip":
            _mark_healthy("nim")
            return {"text": None, "engine": "nim", "skip": True, "fallback": False}
        errors.append(label)
        _mark_unhealthy("nim")
    else:
        errors.append("nim-cooldown")

    _log(f"ALL ENGINES DOWN ({', '.join(errors)})")
    return {"text": None, "engine": None, "fallback": True, "errors": errors}


def draft(incoming: str, parent: str | None = None, author: str | None = None,
          lang: str | None = None, timeout: int = 120) -> dict:
    user_prompt = _build_user_prompt(incoming, parent, author, lang)
    res = generate(_system_prompt(), user_prompt, timeout=timeout,
                   validate=lambda t: _voice_lint(_clean(t)))
    if res.get("skip"):
        return {"draft": None, "engine": res.get("engine"), "skip": True,
                "fallback": False}
    if res.get("text"):
        return {"draft": res["text"], "model": res.get("model"),
                "engine": res.get("engine"), "fallback": False}
    # The static line is identical for every target, so unattended callers
    # (search_respond, engagement_scanner) must drop it rather than post it.
    text = _static_fallback(incoming, lang)
    _log("→ static fallback, do not auto-post")
    return {"draft": text, "model": "fallback-static", "engine": None,
            "fallback": True, "errors": res.get("errors", [])}


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
