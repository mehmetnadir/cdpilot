#!/usr/bin/env python3
"""_novelty.py — have we already said this?

Exact-duplicate blocking (poster_twikit) catches a broken generator repeating
one sentence. It does not catch the slower failure: saying the same thing in
different words, week after week, until the account reads like a loop.

Three axes, because repetition shows up in three ways:
  - subject: same topic/entity covered again too soon
  - wording: high token overlap with something already posted
  - rhythm: every post opening the same way ("just shipped...", "TIL...")

Nothing here is a hard guarantee; it is a cheap check that runs before queueing
and refuses the obvious repeats.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

STOP = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this",
    "these", "those", "is", "are", "was", "were", "be", "been", "being", "to",
    "of", "in", "on", "at", "for", "with", "from", "by", "as", "it", "its",
    "you", "your", "we", "our", "i", "my", "me", "they", "them", "he", "she",
    "not", "no", "so", "just", "now", "up", "out", "how", "what", "why", "when",
    "can", "will", "would", "should", "could", "do", "does", "did", "have",
    "has", "had", "get", "got", "one", "two", "more", "most", "some", "any",
    "all", "here", "there", "about", "into", "over", "after", "before", "still",
}

SIMILARITY_LIMIT = 0.45     # Jaccard over content words
SUBJECT_WINDOW_DAYS = 21    # same subject may return after three weeks
OPENER_WINDOW = 8           # how many recent posts share an opening pattern


def _words(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9][a-z0-9'\-\.]{2,}", (text or "").lower())
    return {t.strip(".'-") for t in toks if t not in STOP and len(t) > 3}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _opener(text: str) -> str:
    """First two words, as a rhythm fingerprint.

    Two, not three: "just shipped a" and "just shipped support" are the same
    tic, and a three-word key treats them as different openings.
    """
    toks = re.findall(r"[a-zA-Z']+", (text or "").lower())
    return " ".join(toks[:2])


def _subjects(text: str) -> set[str]:
    """Named things: repo paths, domains, and CamelCase/product-looking tokens."""
    low = (text or "")
    found = set(re.findall(r"[a-z0-9\-]+/[a-z0-9\-\.]+", low.lower()))
    found |= set(re.findall(r"\b[a-z0-9\-]+\.(?:com|dev|io|ai|org|net)\b", low.lower()))
    found |= {w.lower() for w in re.findall(r"\b[A-Z][a-zA-Z]{3,}\b", low)}
    return {f for f in found if f not in ("this", "that", "here")}


def _history(bot_home: Path, days: int = 30) -> list[dict]:
    cutoff = time.time() - days * 86400
    out: list[dict] = []
    for sub in ("posted", "queue"):
        d = bot_home / sub
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            try:
                item = json.loads(f.read_text())
            except Exception:
                continue
            ts = item.get("posted_at") or item.get("approved_at") or 0
            if ts and ts < cutoff:
                continue
            texts = item.get("texts") or ([item.get("text")] if item.get("text") else [])
            body = " ".join(t for t in texts if t)
            if body:
                out.append({"id": item.get("id"), "text": body, "ts": ts})
    out.sort(key=lambda r: r["ts"], reverse=True)
    return out


def check(text: str, bot_home: Path, days: int = 30) -> tuple[bool, str]:
    """(ok, reason). ok=False means we have effectively said this already."""
    hist = _history(bot_home, days)
    if not hist:
        return True, "no history"

    mine_w, mine_s, mine_o = _words(text), _subjects(text), _opener(text)

    for prev in hist:
        sim = _jaccard(mine_w, _words(prev["text"]))
        if sim >= SIMILARITY_LIMIT:
            return False, f"too similar to {prev['id']} ({sim:.2f} overlap)"

    if mine_s:
        cutoff = time.time() - SUBJECT_WINDOW_DAYS * 86400
        for prev in hist:
            if prev["ts"] and prev["ts"] < cutoff:
                continue
            shared = mine_s & _subjects(prev["text"])
            if shared:
                return False, f"same subject as {prev['id']}: {', '.join(sorted(shared)[:2])}"

    recent_openers = [_opener(p["text"]) for p in hist[:OPENER_WINDOW]]
    if mine_o and recent_openers.count(mine_o) >= 2:
        return False, f'opening "{mine_o}" already used {recent_openers.count(mine_o)}x recently'

    return True, "novel"
