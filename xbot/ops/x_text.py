#!/usr/bin/env python3
"""x_text.py — Twitter / X weighted text length counter (twitter-text v3).

Calculates weighted length according to X rules:
1. NFC normalization.
2. Every URL / bare domain counts 23 characters (t.co wrap).
3. Non-URL characters:
   - 1 weight: U+0000..U+10FF, U+2000..U+200D, U+2010..U+201F, U+2032..U+2037
   - 2 weight: all others (CJK, emoji, special symbols).
4. Leading and trailing whitespace counts.

CLI:
  python3 x_text.py "<text>"
  cat tweet.txt | python3 x_text.py
"""
from __future__ import annotations

import re
import sys
import unicodedata

# ~60 common generic Top-Level Domains (gTLDs)
GTLDS: set[str] = {
    # Original / classic
    "com", "org", "net", "edu", "gov", "mil", "int", "arpa",
    # Modern generic
    "info", "biz", "pro", "xyz", "online", "site", "tech", "store",
    "blog", "app", "dev", "cloud", "link", "space", "club", "top",
    "vip", "news", "live", "life", "world", "shop", "work", "page",
    "today", "agency", "group", "zone", "network", "digital", "studio",
    "design", "media", "rocks", "run", "fund", "team", "guru", "art",
    "pub", "bar", "cafe", "law", "eco", "bot", "moe", "press", "style",
    "social", "global", "expert", "click", "help", "guide", "review",
    "video", "systems", "solutions", "services", "company",
}

# 2-letter country-code Top-Level Domains (ccTLDs).
# Note: .py (Paraguay ccTLD) is intentionally not in the TLD list so file
# names like cdpilot.py are not counted as URLs.
CCTLDS: set[str] = {
    "ac", "ad", "ae", "af", "ag", "ai", "al", "am", "ao", "aq", "ar", "as", "at", "au", "aw", "ax", "az",
    "ba", "bb", "bd", "be", "bf", "bg", "bh", "bi", "bj", "bm", "bn", "bo", "br", "bs", "bt", "bw", "by", "bz",
    "ca", "cc", "cd", "cf", "cg", "ch", "ci", "ck", "cl", "cm", "cn", "co", "cr", "cu", "cv", "cw", "cx", "cy", "cz",
    "de", "dj", "dk", "dm", "do", "dz",
    "ec", "ee", "eg", "er", "es", "et", "eu",
    "fi", "fj", "fk", "fm", "fo", "fr",
    "ga", "gd", "ge", "gf", "gg", "gh", "gi", "gl", "gm", "gn", "gp", "gq", "gr", "gs", "gt", "gu", "gw", "gy",
    "hk", "hm", "hn", "hr", "ht", "hu",
    "id", "ie", "il", "im", "in", "io", "iq", "ir", "is", "it",
    "je", "jm", "jo", "jp",
    "ke", "kg", "kh", "ki", "km", "kn", "kp", "kr", "kw", "ky", "kz",
    "la", "lb", "lc", "li", "lk", "lr", "ls", "lt", "lu", "lv", "ly",
    "ma", "mc", "md", "me", "mf", "mg", "mh", "mk", "ml", "mm", "mn", "mo", "mp", "mq", "mr", "ms", "mt", "mu", "mv", "mw", "mx", "my", "mz",
    "na", "nc", "ne", "nf", "ng", "ni", "nl", "no", "np", "nr", "nu", "nz",
    "om",
    "pa", "pe", "pf", "pg", "ph", "pk", "pl", "pm", "pn", "pr", "ps", "pt", "pw",
    # "py" is intentionally excluded from this list
    "qa",
    "re", "ro", "rs", "ru", "rw",
    "sa", "sb", "sc", "sd", "se", "sg", "sh", "si", "sj", "sk", "sl", "sm", "sn", "so", "sr", "ss", "st", "su", "sv", "sx", "sy", "sz",
    "tc", "td", "tf", "tg", "th", "tj", "tk", "tl", "tm", "tn", "to", "tr", "tt", "tv", "tw", "tz",
    "ua", "ug", "uk", "us", "uy", "uz",
    "va", "vc", "ve", "vg", "vi", "vn", "vu",
    "wf", "ws",
    "ye", "yt",
    "za", "zm", "zw",
}

ALL_TLDS: set[str] = GTLDS | CCTLDS

# Sort TLDs by length descending so longer TLDs match before shorter prefixes
_TLD_PATTERN = "|".join(sorted(ALL_TLDS, key=len, reverse=True))

_URL_RE = re.compile(
    r"(?<![\w@])"
    r"(?:https?://|www\.)?"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    rf"(?:{_TLD_PATTERN})"
    r"(?![a-zA-Z0-9])"
    r"(?:[/?#][^\s)\"'\''“”<>]*)?",
    re.IGNORECASE,
)

_TRAILING_PUNCT = ".,:;!?\"'\''“”)]}>"


def _extract_urls(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Find non-overlapping URLs and their character spans in text."""
    urls: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _URL_RE.finditer(text):
        raw = m.group()
        cleaned = raw.rstrip(_TRAILING_PUNCT)
        if not cleaned:
            continue
        start = m.start()
        end = start + len(cleaned)
        urls.append(cleaned)
        spans.append((start, end))
    return urls, spans


def _char_weight(cp: int) -> int:
    """Return weight of a code point outside URLs."""
    if (
        (0x0000 <= cp <= 0x10FF)
        or (0x2000 <= cp <= 0x200D)
        or (0x2010 <= cp <= 0x201F)
        or (0x2032 <= cp <= 0x2037)
    ):
        return 1
    return 2


def weighted_length(text: str) -> int:
    """Compute weighted length of text following twitter-text v3 rules."""
    text_nfc = unicodedata.normalize("NFC", text)
    urls, spans = _extract_urls(text_nfc)
    total = len(urls) * 23
    last_idx = 0
    for start, end in spans:
        chunk = text_nfc[last_idx:start]
        total += sum(_char_weight(ord(ch)) for ch in chunk)
        last_idx = end
    chunk = text_nfc[last_idx:]
    total += sum(_char_weight(ord(ch)) for ch in chunk)
    return total


def check(text: str, limit: int = 280) -> dict:
    """Check text against weighted limit, returning stats and matched URLs."""
    text_nfc = unicodedata.normalize("NFC", text)
    w = weighted_length(text_nfc)
    urls, _ = _extract_urls(text_nfc)
    return {
        "weighted": w,
        "limit": limit,
        "ok": w <= limit,
        "urls": urls,
    }


def main() -> None:
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:]) if len(sys.argv) > 2 else sys.argv[1]
    else:
        text = sys.stdin.read()
    res = check(text)
    print(f"weighted={res['weighted']} limit={res['limit']} ok={res['ok']} urls={res['urls']}")
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
