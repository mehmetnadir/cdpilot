#!/usr/bin/env python3
"""poster.py — Local Mac queue worker.

Scans ~/cdpilot-twitter-data/queue/ for items where scheduled_time <= now,
posts via Vivaldi CDP (port 9227, @cdpilot_dev session), notifies Telegram,
moves the item to posted/ or failed/.

Designed to be invoked by launchd every 5 minutes. Idempotent: only picks
items with status == "pending" and scheduled_time elapsed.

Supported kinds: tweet, reply, quote.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _phase0_lib import open_tab, page_eval, _http  # type: ignore
from _paths import bot_home  # type: ignore

DATA = bot_home()
QUEUE_DIR = DATA / "queue"
POSTED_DIR = DATA / "posted"
FAILED_DIR = DATA / "failed"
LOG_FILE = DATA / "logs" / "poster.log"
TELEGRAM_BRIDGE = Path(__file__).parent / "telegram_bridge.py"


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _telegram_notify(text: str) -> None:
    """Send a plain status message to Telegram via the bridge."""
    try:
        import subprocess
        subprocess.run(
            ["/opt/homebrew/bin/python3.13", str(TELEGRAM_BRIDGE), "send", text],
            timeout=15, check=False,
        )
    except Exception as e:
        _log(f"telegram notify failed: {e}")


def _check_browser_alive() -> bool:
    """Verify Vivaldi CDP is reachable on port 9227."""
    try:
        _http("/json/version")
        return True
    except Exception:
        return False


async def _post_tweet(text: str) -> dict:
    """Compose dialog'da tweet at. Returns {ok, tweet_url}."""
    tid, pws = await open_tab("https://x.com/compose/post")
    await asyncio.sleep(5)
    # Type
    js_type = """(() => {
      const ta = document.querySelector('[data-testid="tweetTextarea_0"]');
      if (!ta) return {ok:false, err:'no textarea'};
      ta.focus();
      const ok = document.execCommand('insertText', false, %s);
      return {ok, len: ta.innerText.length};
    })()""" % json.dumps(text)
    r1 = await page_eval(pws, js_type)
    _log(f"type result: {r1}")
    if not r1 or not r1.get("ok"):
        return {"ok": False, "err": f"type-failed: {r1}"}
    await asyncio.sleep(2)
    # Click button
    js_post = """(() => {
      const btn = document.querySelector('[data-testid="tweetButton"]') || document.querySelector('[data-testid="tweetButtonInline"]');
      if (!btn) return {ok:false, err:'no button'};
      if (btn.getAttribute('aria-disabled') === 'true') return {ok:false, err:'disabled'};
      btn.click();
      return {ok:true};
    })()"""
    r2 = await page_eval(pws, js_post)
    _log(f"post result: {r2}")
    if not r2 or not r2.get("ok"):
        return {"ok": False, "err": f"post-failed: {r2}"}
    await asyncio.sleep(6)
    # Profile'a git, en üst tweet URL'sini al
    await page_eval(pws, "location.href='https://x.com/cdpilot_dev'")
    await asyncio.sleep(5)
    tweet_url = await page_eval(
        pws,
        "Array.from(document.querySelectorAll('article a[href*=\"/status/\"]'))"
        ".map(a=>a.href).filter(h=>h.includes('cdpilot_dev/status'))[0] || null"
    )
    return {"ok": True, "tweet_url": tweet_url}


async def _post_reply(text: str, to_url: str) -> dict:
    """Reply at: to_url tweet sayfasına git, reply textarea'sına yaz, post et."""
    if not to_url:
        return {"ok": False, "err": "missing reply target url"}
    tid, pws = await open_tab(to_url)
    await asyncio.sleep(5)
    js_type = """(() => {
      // Reply textarea — main tweet altındaki
      const ta = document.querySelector('[data-testid="tweetTextarea_0"]');
      if (!ta) return {ok:false, err:'no textarea'};
      ta.focus();
      const ok = document.execCommand('insertText', false, %s);
      return {ok, len: ta.innerText.length};
    })()""" % json.dumps(text)
    r1 = await page_eval(pws, js_type)
    _log(f"reply type: {r1}")
    if not r1 or not r1.get("ok"):
        return {"ok": False, "err": f"type-failed: {r1}"}
    await asyncio.sleep(2)
    js_send = """(() => {
      const btn = document.querySelector('[data-testid="tweetButtonInline"]') || document.querySelector('[data-testid="tweetButton"]');
      if (!btn) return {ok:false, err:'no button'};
      if (btn.getAttribute('aria-disabled') === 'true') return {ok:false, err:'disabled'};
      btn.click();
      return {ok:true};
    })()"""
    r2 = await page_eval(pws, js_send)
    _log(f"reply send: {r2}")
    if not r2 or not r2.get("ok"):
        return {"ok": False, "err": f"send-failed: {r2}"}
    await asyncio.sleep(5)
    return {"ok": True, "tweet_url": to_url}


async def _process_one(item: dict) -> dict:
    kind = item.get("kind", "tweet")
    text = item["text"]
    if kind == "tweet":
        return await _post_tweet(text)
    if kind == "reply":
        return await _post_reply(text, item.get("to_url") or item.get("to") or "")
    if kind == "quote":
        # Quote: compose tweet + paste tweet URL at end (simplest approach)
        quoted_url = item.get("quote_url") or item.get("to") or ""
        full = f"{text}\n{quoted_url}".strip() if quoted_url else text
        return await _post_tweet(full)
    return {"ok": False, "err": f"unsupported kind: {kind}"}


def main() -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    POSTED_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)

    now = int(time.time())
    pending = sorted(QUEUE_DIR.glob("*.json"))
    if not pending:
        return

    due = []
    for p in pending:
        try:
            item = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            _log(f"corrupt queue file {p.name}: {e}")
            continue
        if item.get("status") != "pending":
            continue
        if item.get("scheduled_time", 0) > now:
            continue
        due.append((p, item))

    if not due:
        return

    if not _check_browser_alive():
        _log("CDP not reachable on port 9227 — Vivaldi closed or not logged in")
        _telegram_notify("⚠️ Poster: Vivaldi CDP (9227) ulaşılmıyor. Atılamadı.")
        return

    _log(f"due items: {len(due)}")
    for p, item in due:
        try:
            _log(f"posting {item['id']} ({item.get('kind')}): {item['text'][:80]}...")
            result = asyncio.run(_process_one(item))
            if result.get("ok"):
                item["status"] = "posted"
                item["posted_at"] = int(time.time())
                item["tweet_url"] = result.get("tweet_url")
                dest = POSTED_DIR / p.name
                dest.write_text(json.dumps(item, ensure_ascii=False, indent=2))
                p.unlink()
                _log(f"✅ posted {item['id']} → {item.get('tweet_url')}")
                _telegram_notify(
                    f"🟢 `{item['id']}` atıldı\n{item.get('tweet_url') or '(URL alınamadı)'}"
                )
            else:
                err = result.get("err", "unknown")
                item["status"] = "failed"
                item["failed_at"] = int(time.time())
                item["error"] = err
                dest = FAILED_DIR / p.name
                dest.write_text(json.dumps(item, ensure_ascii=False, indent=2))
                p.unlink()
                _log(f"❌ failed {item['id']}: {err}")
                _telegram_notify(f"🔴 `{item['id']}` ATIM HATASI: {err}")
        except Exception as e:
            tb = traceback.format_exc()
            _log(f"exception on {item['id']}: {tb}")
            item["status"] = "failed"
            item["error"] = str(e)
            item["traceback"] = tb
            dest = FAILED_DIR / p.name
            dest.write_text(json.dumps(item, ensure_ascii=False, indent=2))
            p.unlink()
            _telegram_notify(f"🔴 `{item['id']}` ATIM EXCEPTION: {str(e)[:200]}")


if __name__ == "__main__":
    main()
