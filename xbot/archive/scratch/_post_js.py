#!/usr/bin/env python3
"""Doğrudan Vivaldi 9227 → eval ile post."""
import asyncio, json, os, sys, time
import websockets
import urllib.request

PORT = 9227
CONTENT = ("webdriver was designed for cross-browser testing in 2011. "
           "cdp was designed to build devtools. one is for compliance, "
           "the other for deep surgical control of the engine. "
           "different tools, different problems")

def get_compose_target():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5) as r:
        targets = json.loads(r.read())
    # /compose/post sayfasını bul
    for t in targets:
        if t.get("type") == "page" and "compose" in (t.get("url") or ""):
            return t
    # fallback: ilk page
    for t in targets:
        if t.get("type") == "page":
            return t
    return None

async def main():
    t = get_compose_target()
    if not t:
        print("No compose target", file=sys.stderr); sys.exit(1)
    ws_url = t["webSocketDebuggerUrl"]
    print(f"Connecting: {ws_url}", file=sys.stderr)

    async with websockets.connect(ws_url, max_size=100*1024*1024) as ws:
        msg_id = 0
        async def call(method, params=None):
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == msg_id:
                    return r
        # Enable Runtime
        await call("Runtime.enable")

        # Step 1: focus textarea + type content via execCommand
        js1 = f"""(() => {{
          const ta = document.querySelector('[data-testid="tweetTextarea_0"]');
          if (!ta) return {{ok: false, err: 'no textarea'}};
          ta.focus();
          const ok = document.execCommand('insertText', false, {json.dumps(CONTENT)});
          return {{ok, len: ta.innerText.length, sample: ta.innerText.slice(0, 60)}};
        }})()"""
        r1 = await call("Runtime.evaluate", {"expression": js1, "returnByValue": True})
        print("Step1:", r1.get("result", {}).get("result", {}).get("value"), file=sys.stderr)
        await asyncio.sleep(1.5)

        # Step 2: button durumu kontrol
        js2 = """(() => {
          const btn = document.querySelector('[data-testid="tweetButton"]') || document.querySelector('[data-testid="tweetButtonInline"]');
          if (!btn) return {ok: false, err: 'no button'};
          return {ok: true, disabled: btn.getAttribute('aria-disabled') === 'true', text: btn.innerText};
        })()"""
        r2 = await call("Runtime.evaluate", {"expression": js2, "returnByValue": True})
        print("Step2:", r2.get("result", {}).get("result", {}).get("value"), file=sys.stderr)

        # Step 3: button click
        js3 = """(() => {
          const btn = document.querySelector('[data-testid="tweetButton"]') || document.querySelector('[data-testid="tweetButtonInline"]');
          if (!btn) return {ok: false};
          btn.click();
          return {ok: true, clicked_at: Date.now()};
        })()"""
        r3 = await call("Runtime.evaluate", {"expression": js3, "returnByValue": True})
        print("Step3:", r3.get("result", {}).get("result", {}).get("value"), file=sys.stderr)

        await asyncio.sleep(6)

        # Step 4: final URL
        r4 = await call("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
        final_url = r4.get("result", {}).get("result", {}).get("value")
        print("Final URL:", final_url, file=sys.stderr)
        print(json.dumps({"final_url": final_url}))

asyncio.run(main())
