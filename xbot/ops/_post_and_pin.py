#!/usr/bin/env python3
import asyncio, json, sys
sys.path.insert(0, "/Users/nadir/01dev/cdpilot/scripts/twitter-bot")
from _phase0_lib import open_tab, page_eval

PINNED = (
    "browser automation without the driver tax\n\n"
    "no selenium, no playwright, no puppeteer — just raw CDP over a websocket. "
    "zero deps, one npx command\n\n"
    "building cdpilot in public ↓"
)

async def main():
    tid, pws = await open_tab("https://x.com/compose/post")
    await asyncio.sleep(5)

    # Type content
    js_type = """(() => {
      const ta = document.querySelector('[data-testid="tweetTextarea_0"]');
      if (!ta) return {ok:false, err:'no textarea'};
      ta.focus();
      const ok = document.execCommand('insertText', false, %s);
      return {ok, text: ta.innerText, len: ta.innerText.length};
    })()""" % json.dumps(PINNED)
    r1 = await page_eval(pws, js_type)
    print("type:", json.dumps(r1, ensure_ascii=False), file=sys.stderr)
    await asyncio.sleep(2)

    # Button check + click
    js_post = """(() => {
      const btn = document.querySelector('[data-testid="tweetButton"]') || document.querySelector('[data-testid="tweetButtonInline"]');
      if (!btn) return {ok:false, err:'no button'};
      if (btn.getAttribute('aria-disabled') === 'true') return {ok:false, err:'disabled'};
      btn.click();
      return {ok:true};
    })()"""
    r2 = await page_eval(pws, js_post)
    print("post:", r2, file=sys.stderr)
    await asyncio.sleep(6)

    # Profile'a git, en üstteki tweet'i bul (yeni atılan), URL al
    url = await page_eval(pws, "location.href")
    print("after post url:", url, file=sys.stderr)

    # cdpilot_dev profiline git
    await page_eval(pws, "location.href='https://x.com/cdpilot_dev'")
    await asyncio.sleep(5)
    tweet_url = await page_eval(pws,
        "Array.from(document.querySelectorAll('article a[href*=\"/status/\"]')).map(a=>a.href).filter(h=>h.includes('cdpilot_dev/status'))[0] || null")
    print("newest tweet:", tweet_url, file=sys.stderr)

    # En üstteki tweet'in caret menüsünü aç → Profiline sabitle
    js_pin_open = """(() => {
      const art = document.querySelector('article');
      const caret = art && art.querySelector('[data-testid="caret"]');
      if (!caret) return {ok:false, err:'no caret'};
      caret.click();
      return {ok:true};
    })()"""
    rp1 = await page_eval(pws, js_pin_open)
    print("pin menu open:", rp1, file=sys.stderr)
    await asyncio.sleep(2)

    js_pin_click = """(() => {
      const items = [...document.querySelectorAll('[role="menuitem"]')];
      const pin = items.find(i => /sabitle|pin to profile|pin/i.test(i.innerText));
      if (!pin) return {ok:false, labels: items.map(i=>i.innerText)};
      pin.click();
      return {ok:true};
    })()"""
    rp2 = await page_eval(pws, js_pin_click)
    print("pin click:", rp2, file=sys.stderr)
    await asyncio.sleep(2)

    # Confirm dialog (varsa)
    js_pin_confirm = """(() => {
      const btn = document.querySelector('[data-testid="confirmationSheetConfirm"]');
      if (btn) { btn.click(); return {ok:true, confirmed:true}; }
      return {ok:true, confirmed:false};
    })()"""
    rp3 = await page_eval(pws, js_pin_confirm)
    print("pin confirm:", rp3, file=sys.stderr)
    await asyncio.sleep(3)

    print(json.dumps({"tweet_url": tweet_url, "posted": r2.get("ok"), "pinned": rp2.get("ok")}))

asyncio.run(main())
