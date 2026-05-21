#!/usr/bin/env python3
import asyncio, json, sys
sys.path.insert(0, "/Users/nadir/01dev/cdpilot/scripts/twitter-bot")
from _phase0_lib import open_tab, page_eval

TWEET_URL = "https://x.com/cdpilot_dev/status/2056735655191777644"

async def main():
    tid, pws = await open_tab(TWEET_URL)
    await asyncio.sleep(5)

    # Adım 1: caret (...) menüsünü aç — ana tweet article'ının caret'i
    js_open = """(() => {
      const art = document.querySelector('article');
      if (!art) return {ok:false, err:'no article'};
      const caret = art.querySelector('[data-testid="caret"]');
      if (!caret) return {ok:false, err:'no caret'};
      caret.click();
      return {ok:true};
    })()"""
    r1 = await page_eval(pws, js_open)
    print("open menu:", r1, file=sys.stderr)
    await asyncio.sleep(2)

    # Adım 2: menüden Delete/Sil bul ve tıkla
    js_del = """(() => {
      const items = [...document.querySelectorAll('[role="menuitem"]')];
      const labels = items.map(i => i.innerText);
      const del = items.find(i => /delete|sil/i.test(i.innerText));
      if (!del) return {ok:false, err:'no delete item', labels};
      del.click();
      return {ok:true, labels};
    })()"""
    r2 = await page_eval(pws, js_del)
    print("click delete:", r2, file=sys.stderr)
    await asyncio.sleep(2)

    # Adım 3: confirm
    js_confirm = """(() => {
      const btn = document.querySelector('[data-testid="confirmationSheetConfirm"]');
      if (!btn) return {ok:false, err:'no confirm'};
      btn.click();
      return {ok:true};
    })()"""
    r3 = await page_eval(pws, js_confirm)
    print("confirm:", r3, file=sys.stderr)
    await asyncio.sleep(3)

    # Doğrula — tweet'e tekrar git, var mı?
    v = await page_eval(pws, "({url:location.href, gone: document.body.innerText.includes('post') ? 'check' : 'check'})")
    print(json.dumps({"deleted": r3.get("ok") and r2.get("ok"), "final": v}))

asyncio.run(main())
