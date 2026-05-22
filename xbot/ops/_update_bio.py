#!/usr/bin/env python3
import asyncio, json, sys
sys.path.insert(0, "/Users/nadir/01dev/cdpilot/scripts/twitter-bot")
from _phase0_lib import open_tab, page_eval

BIO = ("I build cdpilot — browser automation without the driver tax. "
       "pure CDP over a WebSocket, zero deps. protocol-level notes for devs & AI agents")

async def main():
    tid, pws = await open_tab("https://x.com/cdpilot_dev")
    await asyncio.sleep(5)

    # Edit profile butonu
    js_edit = """(() => {
      const btn = document.querySelector('[data-testid="editProfileButton"]');
      if (!btn) {
        // fallback: metin ile bul
        const cand = [...document.querySelectorAll('a,div[role=button],span')].find(e=>/edit profile|profili düzenle/i.test(e.innerText||''));
        if (cand) { cand.click(); return {ok:true, via:'text'}; }
        return {ok:false, err:'no edit button'};
      }
      btn.click();
      return {ok:true, via:'testid'};
    })()"""
    r1 = await page_eval(pws, js_edit)
    print("edit click:", r1, file=sys.stderr)
    await asyncio.sleep(3)

    # Bio textarea — temizle + yeni yaz
    js_bio = """(() => {
      const ta = document.querySelector('[data-testid="bioTextarea"]') || document.querySelector('textarea[name="description"]');
      if (!ta) return {ok:false, err:'no bio textarea'};
      ta.focus();
      // mevcut içeriği seç + sil
      document.execCommand('selectAll', false, null);
      document.execCommand('delete', false, null);
      const ok = document.execCommand('insertText', false, %s);
      return {ok, value: ta.value !== undefined ? ta.value : ta.innerText};
    })()""" % json.dumps(BIO)
    r2 = await page_eval(pws, js_bio)
    print("bio set:", json.dumps(r2, ensure_ascii=False), file=sys.stderr)
    await asyncio.sleep(2)

    # Save
    js_save = """(() => {
      const btn = document.querySelector('[data-testid="Profile_Save_Button"]');
      if (!btn) return {ok:false, err:'no save'};
      btn.click();
      return {ok:true};
    })()"""
    r3 = await page_eval(pws, js_save)
    print("save:", r3, file=sys.stderr)
    await asyncio.sleep(4)

    # Doğrula — profilde bio görünüyor mu
    v = await page_eval(pws, "(document.querySelector('[data-testid=\"UserDescription\"]')?.innerText)||null")
    print(json.dumps({"saved": r3.get("ok"), "bio_now": v}, ensure_ascii=False))

asyncio.run(main())
