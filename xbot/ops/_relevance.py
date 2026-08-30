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
STRONG = (
    "playwright", "puppeteer", "selenium", "webdriver", "devtools protocol",
    "chrome devtools", "cdp", "headless chrome", "headless browser",
    "browser automation", "automate the browser", "browserbase", "browser-use",
    "anti-bot", "antibot", "bot detection", "datadome", "perimeterx", "kasada",
    "cloudflare challenge", "turnstile", "recaptcha", "captcha",
    "browser fingerprint", "fingerprinting", "navigator.webdriver",
    "web scraping", "webscraping", "scraper", "scraping", "crawler",
    "xvfb", "chromedriver", "browser agent", "computer use",
)

# Weaker signals: two of them together are enough.
WEAK = (
    "chrome", "chromium", "brave", "firefox", "browser", "automation",
    "headless", "stealth", "proxy", "user agent", "user-agent", "session",
    "cookie", "e2e", "end-to-end test", "screenshot", "dom", "iframe",
    "shadow dom", "selector", "xpath", "http 403", "403", "rate limit",
    "agent", "llm", "cli", "node_modules", "npm",
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
    return 0, weak_hits


def should_reply(text: str) -> tuple[bool, str]:
    """Gate used by every automated reply path. Returns (ok, reason)."""
    blocked = off_limits(text)
    if blocked:
        return False, f"off-limits:{blocked}"
    score, hits = relevance(text)
    if score == 0:
        return False, "off-niche:no domain terms"
    return True, f"relevant:{','.join(hits[:3])}"
