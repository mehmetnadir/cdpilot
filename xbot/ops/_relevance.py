#!/usr/bin/env python3
"""_relevance.py — is this tweet ours to answer?

Field evidence (2026-06, all actually posted by @cdpilot_dev):
  - a UK tax-policy argument between two strangers
  - a RADIUS multiple-choice quiz, where we answered the quiz and then asked
    the quizmaster whether they were studying for a cert
  - VoipNow's 20th-anniversary post, answered with a claim about running "a raw
    SIP stack through CDP", which is not a thing
  - a Pokémon pre-order guide, where we pitched cdpilot for looking "less
    botlike to their anti-bot" — advertising our own tool for scalping

None of these were bugs in drafting. The candidate filter only asked "is it a
question?", and the ranking rewarded follower count, so big off-topic accounts
outranked small on-topic ones. This module is the missing gate: a reply we do
not post costs nothing, an off-niche reply costs the account.
"""
from __future__ import annotations

import re

# Terms that place a tweet squarely in our domain. One is enough.
#
# The domain is "building software with AI", not "browser automation". cdpilot
# is what we happen to have built, not what we talk about — a product-shaped
# niche gives us nothing to say about the thing we do all day.
STRONG = (
    # building with AI
    "claude code", "claude 5", "cursor", "copilot", "codex", "aider",
    "windsurf", "cline", "roo code", "zed agent", "coding agent",
    "ai pair programming", "pair programming with ai", "vibe coding",
    "ai-generated code", "ai generated code", "llm agent", "agentic coding",
    "agent loop", "subagent", "multi-agent", "orchestrat",
    "model context protocol", "mcp server", "tool use", "function calling",
    "context window", "prompt engineering", "system prompt", "eval harness",
    "rag pipeline", "embedding model", "fine-tune", "token budget",
    # the craft around it
    "developer experience", "dx", "code review", "refactoring", "tech debt",
    "ci pipeline", "flaky test", "regression test", "observability",
    # what we actually built
    "playwright", "puppeteer", "selenium", "webdriver", "devtools protocol",
    "chrome devtools", "cdp", "headless chrome", "headless browser",
    "browser automation", "automate the browser", "browserbase", "browser-use",
    "anti-bot", "antibot", "bot detection", "datadome", "perimeterx", "kasada",
    "cloudflare challenge", "turnstile", "recaptcha", "captcha",
    "browser fingerprint", "fingerprinting", "navigator.webdriver",
    "web scraping", "webscraping", "scraper", "scraping", "crawler",
    "xvfb", "chromedriver", "browser agent", "computer use",
)

# Weaker signals: two of them together are enough. Deliberately common words
# live here, never in STRONG — "agent" and "llm" alone match plenty of posts
# that have nothing to do with us.
WEAK = (
    "ai", "llm", "model", "prompt", "agent", "token", "context", "inference",
    "anthropic", "openai", "gemini", "opus", "sonnet", "haiku",
    "chrome", "chromium", "brave", "firefox", "browser", "automation",
    "headless", "stealth", "proxy", "user agent", "user-agent", "session",
    "cookie", "e2e", "end-to-end test", "screenshot", "dom", "iframe",
    "shadow dom", "selector", "xpath", "http 403", "403", "rate limit",
    "cli", "node_modules", "npm", "python", "typescript", "repo", "commit",
    "debug", "shipped", "build", "workflow", "pipeline", "test suite",
)

# Someone showing what they made. Paired with a single domain word this is the
# most interesting conversation on the timeline for us — "my LLM cliche
# highlighter is up to 38 patterns now" carries one domain term and would
# otherwise be filtered out as noise.
BUILDER = (
    "built", "building", "shipped", "made", "released", "launched",
    "open source", "open-source", "wrote a", "i made", "just added",
    "working on", "prototype", "side project", "v0.", "v1.", "beta",
)


# Never reply, however well it matches. Reach is not worth the association.
OFF_LIMITS = {
    "siyaset": ("election", "vote for", "voter", "labour", "tory", "reform uk",
                "manifesto", "parliament", "senator", "congress", "president",
                "immigration", "refugee", "war in", "genocide", "zionist",
                "palestin", "israel", "ukraine war", "tax by stealth",
                "working class", "left wing", "right wing", "woke"),
    "din": ("islam", "christian", "muslim", "jewish", "quran", "bible", "allah"),
    "perakende-kapma": ("restock", "pre-order", "preorder", "drop live",
                        "sneaker", "pokemon", "pokémon", "ticketmaster",
                        "concert tickets", "supreme drop", "raffle"),
    "kripto-shill": ("airdrop", "presale", "pump", "moonshot", "to the moon",
                     "1000x", "memecoin", "$pepe", "nft mint"),
    "sinav-sorusu": ("a.", "b.", "c.", "d."),  # multiple-choice quiz layout
}


def off_limits(text: str) -> str | None:
    """Return the category name when a tweet is a no-go, else None."""
    low = (text or "").lower()
    for label, terms in OFF_LIMITS.items():
        if label == "sinav-sorusu":
            # Only a real A/B/C/D block counts, not a stray "a." in prose.
            opts = sum(1 for t in terms if re.search(rf"(^|\s){re.escape(t)}\s", low))
            if opts >= 3:
                return label
            continue
        for t in terms:
            if t in low:
                return label
    return None


def _hit(term: str, low: str) -> bool:
    """Substring matching finds "cli" inside "cliche" and "dom" inside "domain",
    which is how a tweet about LLM cliches once read as on-topic. Short terms
    must match as whole words; long ones may appear inside a phrase."""
    if len(term) <= 4 or term.isalpha() and len(term) <= 6:
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", low) is not None
    return term in low


def relevance(text: str) -> tuple[int, list[str]]:
    """(score, matched terms). 0 means: not our conversation."""
    low = (text or "").lower()
    strong_hits = [t for t in STRONG if _hit(t, low)]
    weak_hits = [t for t in WEAK if _hit(t, low)]
    if strong_hits:
        return 2 + len(strong_hits), strong_hits + weak_hits
    if len(weak_hits) >= 2:
        return 1, weak_hits
    builder_hits = [t for t in BUILDER if _hit(t, low)]
    if weak_hits and builder_hits:
        return 1, weak_hits + builder_hits[:1]
    return 0, weak_hits


def should_reply(text: str) -> tuple[bool, str]:
    """Cheap pre-filter for every automated reply path. Returns (ok, reason).

    Keywords are good at exclusion and bad at inclusion: no term list decides
    whether "my LLM cliche highlighter is up to 38 patterns now" is worth
    answering. So this stage only removes what must never be answered and what
    carries no domain signal at all; whether we actually have something to add
    is judged by the drafting model, which can return SKIP.
    """
    blocked = off_limits(text)
    if blocked:
        return False, f"off-limits:{blocked}"
    low = (text or "").lower()
    if not any(_hit(t, low) for t in STRONG) and not any(_hit(t, low) for t in WEAK):
        return False, "off-niche:no domain signal"
    score, hits = relevance(text)
    return True, f"relevant({score}):{','.join(hits[:3])}"
