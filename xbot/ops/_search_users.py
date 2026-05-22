#!/usr/bin/env python3
"""Vivaldi 9227 → X user search, gerçek handle'ları çek."""
import asyncio, json, sys, urllib.request
import websockets

PORT = 9227
QUERIES = [
    "browser automation",
    "playwright puppeteer",
    "web scraping",
    "AI browser agent",
    "headless chrome CDP",
]

def get_page_target():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5) as r:
        targets = json.loads(r.read())
    for t in targets:
        if t.get("type") == "page" and "x.com" in (t.get("url") or ""):
            return t
    for t in targets:
        if t.get("type") == "page":
            return t
    return None

async def main():
    t = get_page_target()
    ws_url = t["webSocketDebuggerUrl"]
    async with websockets.connect(ws_url, max_size=100*1024*1024) as ws:
        mid = 0
        async def call(method, params=None):
            nonlocal mid
            mid += 1
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == mid:
                    return r
        await call("Page.enable")
        await call("Runtime.enable")

        all_users = {}
        for q in QUERIES:
            url = f"https://x.com/search?q={urllib.parse.quote(q)}&f=user"
            await call("Page.navigate", {"url": url})
            await asyncio.sleep(5)
            js = """(() => {
              const cells = document.querySelectorAll('[data-testid="UserCell"]');
              const out = [];
              cells.forEach(c => {
                const handleEl = Array.from(c.querySelectorAll('span')).find(s => s.innerText.startsWith('@'));
                const link = c.querySelector('a[href^="/"]');
                const handle = handleEl ? handleEl.innerText : null;
                const name = link ? (link.querySelector('span')?.innerText || '') : '';
                const bioEl = c.querySelector('[dir="auto"]:last-child');
                const bio = bioEl ? bioEl.innerText.slice(0,120) : '';
                if (handle) out.push({handle, name, bio});
              });
              return out.slice(0, 12);
            })()"""
            r = await call("Runtime.evaluate", {"expression": js, "returnByValue": True})
            users = r.get("result", {}).get("result", {}).get("value", []) or []
            print(f"\n=== {q} ({len(users)}) ===", file=sys.stderr)
            for u in users:
                h = u.get("handle")
                if h and h not in all_users:
                    all_users[h] = u
                    print(f"  {h:25} {u.get('bio','')[:70]}", file=sys.stderr)

        print(json.dumps(list(all_users.values()), indent=2, ensure_ascii=False))

import urllib.parse
asyncio.run(main())
