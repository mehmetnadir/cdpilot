#!/usr/bin/env python3
"""Faz 0 ortak kütüphane — browser WS bağlan, tab aç, eval helper."""
import asyncio, json, sys, urllib.request
import websockets

PORT = 9227

def _http(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=5) as r:
        return json.loads(r.read())

def browser_ws():
    return _http("/json/version")["webSocketDebuggerUrl"]

async def rpc(ws, method, params=None, _ids={"n": 0}):
    _ids["n"] += 1
    mid = _ids["n"]
    await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        r = json.loads(await ws.recv())
        if r.get("id") == mid:
            return r

async def open_tab(url):
    """Browser WS üzerinden yeni tab aç, page WS url döndür."""
    bws = browser_ws()
    async with websockets.connect(bws, max_size=100*1024*1024) as ws:
        r = await rpc(ws, "Target.createTarget", {"url": url})
        target_id = r["result"]["targetId"]
    # page WS url'i /json'dan al
    await asyncio.sleep(1)
    for t in _http("/json"):
        if t.get("id") == target_id:
            return target_id, t["webSocketDebuggerUrl"]
    raise RuntimeError("target not found after create")

async def page_eval(page_ws, expr, await_promise=False):
    async with websockets.connect(page_ws, max_size=100*1024*1024) as ws:
        await rpc(ws, "Runtime.enable")
        r = await rpc(ws, "Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": await_promise
        })
        return r.get("result", {}).get("result", {}).get("value")


async def _test():
    tid, pws = await open_tab("https://x.com/home")
    await asyncio.sleep(5)
    v = await page_eval(pws, "({url:location.href, loggedIn:!!document.querySelector('[data-testid=AppTabBar_Home_Link]'), handle:document.querySelector('[data-testid=SideNav_AccountSwitcher_Button]')?.innerText?.split('\\n').pop()||null})")
    print(json.dumps({"target_id": tid, "page_ws": pws, "state": v}, indent=2))

if __name__ == "__main__":
    asyncio.run(_test())
