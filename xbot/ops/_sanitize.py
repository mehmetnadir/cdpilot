#!/usr/bin/env python3
"""_sanitize.py — strip prompt-injection patterns from inbound text.

Used by mention_scraper, dm_handler, engagement_scanner. Returns a dict:
  {"clean": str, "flags": list[str], "drop": bool}

Rules: see ../security.md
"""
from __future__ import annotations
import re
import unicodedata

# zero-width + bidi override chars
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁯﻿]")

# command-like injection patterns (case-insensitive substring match)
_INJECT_PATTERNS = [
    r"ignore (all |previous |prior |the )+(instructions|rules|prompts|above)",
    r"disregard (the )?(above|previous|system)",
    r"system\s*:\s*you (are|will)",
    r"you are now (a |an )?",
    r"act as (a |an )?",
    r"new instructions?:",
    r"\[INST\]|\[\\?INST\\?\]",
    r"<\|im_start\|>|<\|im_end\|>",
    r"print (your |the )?system prompt",
    r"reveal (your )?(prompt|instructions|tools)",
    r"list (your )?tools",
    r"forget (everything|all|your)",
    r"jailbreak",
    r"DAN mode",
]
_INJECT_RE = re.compile("|".join(_INJECT_PATTERNS), re.IGNORECASE)

# crisis keywords (avoid topic entirely) — minimal anchor list
_CRISIS = re.compile(
    r"\b(politik|election|trump|biden|gaza|israel|palestine|nazi|"
    r"scam|fraud|rug pull|airdrop|kyc dox|"
    r"child|minor|csam|"
    r"racist|sexist|"
    r"copyright violation|dmca takedown)\b",
    re.IGNORECASE,
)

_URL_RE = re.compile(r"https?://\S+")
_MAX_LEN = 4000


def sanitize(text: str | None) -> dict:
    """Return {clean, flags, drop}."""
    flags: list[str] = []
    if not text:
        return {"clean": "", "flags": ["empty"], "drop": True}

    # 1) normalize + strip invisibles
    t = unicodedata.normalize("NFKC", text)
    t = _INVISIBLE.sub("", t)

    # 2) length cap
    if len(t) > _MAX_LEN:
        flags.append(f"truncated_{len(t)}")
        t = t[:_MAX_LEN]

    # 3) injection pattern scan (flag, don't strip — keep human-readable)
    if _INJECT_RE.search(t):
        flags.append("injection_flag")

    # 4) crisis topic scan
    if _CRISIS.search(t):
        flags.append("crisis_topic")

    # 5) URL count
    urls = _URL_RE.findall(t)
    if len(urls) >= 5:
        flags.append(f"url_bomb_{len(urls)}")
    elif len(urls) >= 3:
        flags.append(f"url_high_{len(urls)}")

    # 6) self-reference flag
    if re.search(r"@?cdpilot(_dev)?\b", t, re.IGNORECASE):
        flags.append("self_ref")

    drop = "crisis_topic" in flags or "url_bomb" in [f.split("_")[0] + "_bomb" for f in flags if "url_bomb" in f]

    return {"clean": t.strip(), "flags": flags, "drop": drop}


def wrap_external(clean: str) -> str:
    """Wrap sanitized content for LLM consumption — clear data/instruction split."""
    return f"<external_content>\n{clean}\n</external_content>"


def render_flags(flags: list[str]) -> str:
    """Human-readable flag summary for Telegram."""
    if not flags:
        return "✅ temiz"
    return " · ".join(f"⚠️ {f}" for f in flags)


if __name__ == "__main__":
    import json, sys
    src = sys.stdin.read() if not sys.argv[1:] else " ".join(sys.argv[1:])
    print(json.dumps(sanitize(src), ensure_ascii=False, indent=2))
