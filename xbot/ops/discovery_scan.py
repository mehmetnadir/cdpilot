#!/usr/bin/env python3
"""discovery_scan.py — HN / GitHub / arXiv / X search tarama.

Cowork sabah invocation'ında bu scripti çağırır, çıktısı `discoveries/<date>.json`
olarak yazılır. Cowork bu dosyayı okuyup günün tweet draft seed'lerini üretir.

Tüm istekler stdlib (urllib + json) — hiçbir extra dep yok.
Twitter trends için twikit kullanır (zaten kurulu).

Kullanım:
  python discovery_scan.py [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from twikit import Client  # type: ignore

DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
DISCOVERIES_DIR = DATA / "discoveries"
COOKIES_PATH = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES",
    str(DATA / "cookies" / "cdpilot_dev.json"),
))
LANG = os.environ.get("CDPILOT_TWIKIT_LANG", "en-US")
LOG_FILE = DATA / "logs" / "discovery.log"

UA = "Mozilla/5.0 (Macintosh) cdpilot-discovery/1.0"


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _http_json(url: str, timeout: int = 15, retries: int = 2) -> dict | list | None:
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    _log(f"http_json fail {url}: {last_err}")
    return None


# ── Hacker News ──
def scan_hn(limit: int = 10) -> list:
    """Top HN stories matching browser/automation/AI agent keywords."""
    ids = _http_json("https://hacker-news.firebaseio.com/v0/topstories.json") or []
    keywords = ["browser", "playwright", "puppeteer", "selenium", "stealth",
                "anti-bot", "scraping", "automation", "agent", "captcha",
                "fingerprint", "headless", "chromium", "cdp", "claude",
                "anthropic", "openai", "llm", "rag"]
    results = []
    for sid in ids[:200]:
        if len(results) >= limit:
            break
        s = _http_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=5)
        if not s or s.get("type") != "story":
            continue
        title = (s.get("title") or "").lower()
        text = (s.get("text") or "").lower()
        if any(k in title or k in text for k in keywords):
            results.append({
                "id": s["id"],
                "title": s.get("title"),
                "url": s.get("url") or f"https://news.ycombinator.com/item?id={s['id']}",
                "score": s.get("score"),
                "comments": s.get("descendants", 0),
                "hn_url": f"https://news.ycombinator.com/item?id={s['id']}",
            })
    return results


# ── GitHub Trending (use Github search by date filter) ──
def scan_github(limit: int = 10) -> list:
    """Search GitHub for repos modified recently in our niche."""
    since = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    queries = [
        "browser automation stars:>50",
        "puppeteer alternative stars:>30",
        "stealth scraping stars:>30",
        "anti-bot detection stars:>30",
        "ai agent browser stars:>30",
        "claude code stars:>50",
    ]
    seen = set()
    results = []
    for q in queries:
        if len(results) >= limit:
            break
        url = (f"https://api.github.com/search/repositories?"
               f"q={urllib.parse.quote(q + ' pushed:>2026-04-01')}&sort=updated&per_page=5")
        data = _http_json(url, timeout=10)
        if not data:
            continue
        for repo in (data.get("items") or [])[:5]:
            full = repo.get("full_name")
            if not full or full in seen:
                continue
            seen.add(full)
            results.append({
                "repo": full,
                "url": repo.get("html_url"),
                "description": (repo.get("description") or "")[:160],
                "stars": repo.get("stargazers_count"),
                "language": repo.get("language"),
                "pushed_at": repo.get("pushed_at"),
                "query": q,
            })
            if len(results) >= limit:
                break
    return results


# ── arXiv ──
def scan_arxiv(limit: int = 5) -> list:
    """Recent arXiv papers in cs.HC, cs.AI, cs.CR (relevant categories)."""
    # Search arxiv via Atom API
    query = "(cat:cs.AI OR cat:cs.HC OR cat:cs.CR) AND (browser OR agent OR scraping OR stealth)"
    # NOTE: arxiv export endpoint is slow + flaky; use https + 30s timeout + 2 retries
    url = (f"https://export.arxiv.org/api/query?"
           f"search_query={urllib.parse.quote(query)}&sortBy=submittedDate&sortOrder=descending&max_results={limit}")
    xml: str | None = None
    last_err: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                xml = r.read().decode()
                break
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                # arxiv rate-limits aggressively; back off significantly
                time.sleep(10.0 * (attempt + 1))
            else:
                time.sleep(2.0 * (attempt + 1))
        except Exception as e:
            last_err = e
            time.sleep(2.0 * (attempt + 1))
    if xml is None:
        _log(f"arxiv fail after 3 tries: {last_err} — skipping (likely 429 rate-limit; harmless)")
        return []
    # Quick parse — no extra deps
    results = []
    import re
    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL)
    for entry in entries[:limit]:
        title_m = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
        link_m = re.search(r'<id>(http[^<]+)</id>', entry)
        published_m = re.search(r"<published>(.*?)</published>", entry)
        summary_m = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
        if not title_m or not link_m:
            continue
        results.append({
            "title": title_m.group(1).strip().replace("\n", " ")[:180],
            "url": link_m.group(1).strip(),
            "published": published_m.group(1) if published_m else None,
            "summary": (summary_m.group(1) or "").strip().replace("\n", " ")[:300] if summary_m else "",
        })
    return results


# ── X search (Latest tweets on our niche) ──
async def scan_x_search(limit: int = 10) -> list:
    """Search X for recent niche conversations."""
    if not COOKIES_PATH.exists():
        _log(f"cookies missing for x search: {COOKIES_PATH}")
        return []
    client = Client(LANG)
    client.load_cookies(str(COOKIES_PATH))
    # Simpler queries — twikit's strict search ('-is:retweet') frequently 404s on the
    # mobile graphql endpoint X uses. Plain keywords with min_faves filtering work better.
    queries = [
        "playwright stealth",
        "selenium detection",
        "puppeteer captcha",
        "browser-use",
        "chrome devtools protocol",
    ]
    results = []
    seen_ids = set()
    for q in queries:
        if len(results) >= limit:
            break
        tweets = None
        for product in ("Latest", "Top"):
            try:
                tweets = await client.search_tweet(q, product, count=10)
                break
            except Exception as e:
                _log(f"x search '{q}' [{product}] fail: {e}")
                await asyncio.sleep(1.5)
        if not tweets:
            continue
        for tw in tweets:
            tid = str(tw.id)
            if tid in seen_ids:
                continue
            seen_ids.add(tid)
            # Engagement filter: skip if no traction
            likes = getattr(tw, "favorite_count", 0) or 0
            replies = getattr(tw, "reply_count", 0) or 0
            if likes < 50 and replies < 20:
                continue
            author = tw.user.screen_name if tw.user else "unknown"
            results.append({
                "id": tid,
                "url": f"https://x.com/{author}/status/{tid}",
                "author": f"@{author}",
                "text": (tw.text or "")[:240],
                "likes": likes,
                "replies": replies,
                "rt": getattr(tw, "retweet_count", 0) or 0,
                "query": q,
            })
            if len(results) >= limit:
                break
    return results


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()

    DISCOVERIES_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    _log("starting discovery scan")
    hn = scan_hn(args.limit)
    _log(f"hn: {len(hn)}")
    gh = scan_github(args.limit)
    _log(f"github: {len(gh)}")
    ax = scan_arxiv(5)
    _log(f"arxiv: {len(ax)}")
    xs = await scan_x_search(args.limit)
    _log(f"x search: {len(xs)}")

    payload = {
        "date": today,
        "generated_at": int(time.time()),
        "hn": hn,
        "github": gh,
        "arxiv": ax,
        "x_search": xs,
    }
    out = DISCOVERIES_DIR / f"{today}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _log(f"saved → {out}")
    print(json.dumps({
        "out": str(out),
        "counts": {"hn": len(hn), "github": len(gh), "arxiv": len(ax), "x_search": len(xs)},
    }))


if __name__ == "__main__":
    asyncio.run(main())
