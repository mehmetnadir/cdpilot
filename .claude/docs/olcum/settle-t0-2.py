#!/opt/homebrew/bin/python3.13
"""settle-t0-2.py - go sonrasi t=0 yerlesme olcumu (K-0074 A-0141), dürüst sürüm.

Eski betikten farklar:
- Her koşu kayıt üretir; düşen koşu sebebiyle JSONL'a yazılır (sessiz atlama yok).
- Ağ zamanları CDP monotonic timestamp'inden gelir (ws varış gecikmesi yok).
- Metin değişimi = innerText özeti (uzunluk + hash) değişimi, sayfa saatiyle.
- Sekme öne alınır (arka plan zamanlayıcı kısıtı olmasın).
- Rapor ayrı mod: --report. Boş veri "SAĞLANDI" demez.

Kullanım:
  /opt/homebrew/bin/python3.13 -I settle-t0-2.py --smoke
  /opt/homebrew/bin/python3.13 -I settle-t0-2.py --runs 5
  /opt/homebrew/bin/python3.13 -I settle-t0-2.py --report
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

import websockets

BASE = "http://127.0.0.1:9333"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "settle-t0-2")
JSONL = os.path.join(OUT_DIR, "kosu.jsonl")
REPORT = os.path.join(HERE, "settle-t0-2026-11-11.md")

SITES = [
    ("example.com", "statik", "https://example.com/"),
    ("info.cern.ch", "statik", "http://info.cern.ch/"),
    ("sqlite.org", "belge", "https://www.sqlite.org/index.html"),
    ("docs.python.org", "belge", "https://docs.python.org/3/library/asyncio.html"),
    ("mdn", "belge", "https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver"),
    ("wikipedia", "wiki", "https://en.wikipedia.org/wiki/Web_browser"),
    ("hn", "haber", "https://news.ycombinator.com/"),
    ("lobsters", "haber", "https://lobste.rs/"),
    ("bbc", "haber", "https://www.bbc.com/news"),
    ("guardian", "haber", "https://www.theguardian.com/international"),
    ("github", "kod", "https://github.com/mehmetnadir/cdpilot"),
    ("react.dev", "spa", "https://react.dev/"),
    ("vuejs", "spa", "https://vuejs.org/"),
    ("svelte", "spa", "https://svelte.dev/"),
    ("nextjs", "spa", "https://nextjs.org/"),
    ("astro", "spa", "https://astro.build/"),
    ("excalidraw", "spa", "https://excalidraw.com/"),
    ("books.toscrape", "e-ticaret", "https://books.toscrape.com/"),
    ("webscraper-shop", "e-ticaret", "https://webscraper.io/test-sites/e-commerce/static"),
    ("todomvc", "spa", "https://todomvc.com/examples/react/dist/"),
]

OBSERVER_JS = r"""(function(){
  if (window.__t0log) return;
  window.__t0log = []; window.__t0load = null;
  var last = -999, timer = null, lastSig = null;
  function sig(){
    var s = '';
    try { s = document.body ? (document.body.innerText || '') : ''; } catch(e) {}
    var h = 5381;
    for (var i = 0; i < s.length; i++) { h = ((h << 5) + h + s.charCodeAt(i)) | 0; }
    return s.length + ':' + h;
  }
  function sample(tag){
    var now = performance.now(); last = now;
    if (timer) { clearTimeout(timer); timer = null; }
    var g = sig();
    if (g !== lastSig) { lastSig = g; window.__t0log.push({t: now, g: g, tag: tag || null}); }
    else if (tag) { window.__t0log.push({t: now, g: g, tag: tag, same: true}); }
  }
  function onMut(){
    var e = performance.now() - last;
    if (e >= 5) sample();
    else if (!timer) timer = setTimeout(sample, 5 - e);
  }
  window.addEventListener('load', function(){ window.__t0load = performance.now(); sample('load'); }, {capture:true, once:true});
  var mo = new MutationObserver(onMut);
  try { mo.observe(document, {childList:true, characterData:true, subtree:true, attributes:true}); } catch(e) {}
})();"""

EVAL_JS = r"""(function(){
  var s=''; try { s = document.body ? (document.body.innerText||'') : ''; } catch(e){}
  return {load: window.__t0load, log: window.__t0log || [], title: document.title||'',
          snippet: s.slice(0,400), url: location.href, vis: document.visibilityState,
          now: performance.now()};
})()"""

BOT = ["just a moment", "attention required", "verify you are human", "are you a human",
       "robot or human", "cf-chl", "turnstile", "captcha", "access denied"]


def loadavg():
    try:
        out = subprocess.check_output(["sysctl", "-n", "vm.loadavg"], text=True)
        return float(out.strip("{} \n").split()[0])
    except Exception:
        return None


def http_json(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=5).read())


async def cdp_call(ws, mid, method, params=None, wait=True, timeout=10):
    await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    if not wait:
        return None
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - time.monotonic()))
        m = json.loads(raw)
        if m.get("id") == mid:
            return m
    raise TimeoutError(method)


async def one_run(name, kind, url, tur, post_wait=1.5, page_timeout=30.0):
    rec = {"site": name, "tur": tur, "url": url, "kind": kind, "load_avg": loadavg(),
           "t": time.strftime("%H:%M:%S")}
    bws = http_json("/json/version")["webSocketDebuggerUrl"]
    target_id = None
    try:
        async with websockets.connect(bws, max_size=64 * 1024 * 1024) as b:
            r = await cdp_call(b, 1, "Target.createTarget", {"url": "about:blank"})
            target_id = r["result"]["targetId"]
        rec["target"] = target_id
        async with websockets.connect(f"ws://127.0.0.1:9333/devtools/page/{target_id}",
                                      max_size=64 * 1024 * 1024) as p:
            mid = 1
            for meth, prm in [("Page.enable", {}), ("Network.enable", {}), ("Runtime.enable", {}),
                              ("Page.bringToFront", {}),
                              ("Emulation.setFocusEmulationEnabled", {"enabled": True}),
                              ("Page.addScriptToEvaluateOnNewDocument", {"source": OBSERVER_JS})]:
                mid += 1
                await cdp_call(p, mid, meth, prm)
            reqs = {}      # rid -> [start_ts, end_ts|None, url]
            load_ts = None
            load_wall = None
            mid += 1
            await p.send(json.dumps({"id": mid, "method": "Page.navigate", "params": {"url": url}}))
            t_nav = time.monotonic()
            while True:
                now = time.monotonic()
                if load_wall is not None:
                    left = load_wall + post_wait - now
                    if left <= 0:
                        break
                    to = left
                else:
                    if now - t_nav > page_timeout:
                        rec.update(status="drop", reason="load_timeout_%ds" % page_timeout)
                        return rec
                    to = 1.0
                try:
                    raw = await asyncio.wait_for(p.recv(), timeout=to)
                except asyncio.TimeoutError:
                    continue
                m = json.loads(raw)
                if m.get("id") == mid and "error" in m:
                    rec.update(status="drop", reason="navigate_error:" + str(m["error"])[:120])
                    return rec
                me = m.get("method")
                pr = m.get("params", {})
                if me == "Network.requestWillBeSent":
                    u = pr.get("request", {}).get("url", "")
                    if not u.startswith("data:") and not u.startswith("blob:"):
                        reqs.setdefault(pr["requestId"], [pr["timestamp"], None, u])
                elif me in ("Network.loadingFinished", "Network.loadingFailed"):
                    if pr.get("requestId") in reqs:
                        reqs[pr["requestId"]][1] = pr["timestamp"]
                elif me == "Page.loadEventFired" and load_ts is None:
                    load_ts = pr["timestamp"]
                    load_wall = time.monotonic()
            mid += 1
            ev = await cdp_call(p, mid, "Runtime.evaluate",
                                {"expression": EVAL_JS, "returnByValue": True}, timeout=15)
            val = ev.get("result", {}).get("result", {}).get("value")
            if not val:
                rec.update(status="drop", reason="eval_bos:" + json.dumps(ev)[:160])
                return rec
            hay = (val["title"] + " " + val["snippet"]).lower()
            if any(b in hay for b in BOT):
                rec.update(status="drop", reason="bot_dogrulama:" + val["title"][:60])
                return rec
            if val["load"] is None:
                rec.update(status="drop", reason="sayfada_load_olayi_yok")
                return rec
            if val["url"].startswith("chrome-error") or val["url"] == "about:blank":
                rec.update(status="drop", reason="gezinme_basarisiz:" + val["url"][:60])
                return rec
            pending = [u for (s, e, u) in reqs.values()
                       if s <= load_ts and (e is None or e > load_ts)]
            started30 = [u for (s, e, u) in reqs.values() if load_ts < s <= load_ts + 0.030]
            started100 = [u for (s, e, u) in reqs.values() if load_ts < s <= load_ts + 0.100]
            L = val["load"]
            changes = []
            for it in val["log"]:
                if it.get("same") or it.get("tag") == "load":
                    continue
                changes.append(round(it["t"] - L, 1))
            after = [c for c in changes if c > 0]
            rec.update(
                status="ok", vis=val["vis"], load_ms=round(L, 1), n_req=len(reqs),
                pending_at_load=len(pending), req_30ms=len(started30), req_100ms=len(started100),
                b_triggered=(len(pending) == 0 and len(started30) == 0),
                changes_before_load=len([c for c in changes if c <= 0]),
                change_ms_after_load=[c for c in after if c <= 1500],
                n_0_30=len([c for c in after if c <= 30]),
                n_30_100=len([c for c in after if 30 < c <= 100]),
                n_100_300=len([c for c in after if 100 < c <= 300]),
                pending_urls=[u[:90] for u in pending[:3]],
                late_urls=[u[:90] for u in started100[:3]],
            )
            return rec
    except Exception as ex:
        rec.update(status="drop", reason="istisna:%s:%s" % (type(ex).__name__, str(ex)[:140]))
        return rec
    finally:
        if target_id:
            try:
                urllib.request.urlopen(f"{BASE}/json/close/{target_id}", timeout=4).read()
            except Exception as ex:
                rec["kapatma_hatasi"] = str(ex)[:80]


async def suite(runs, sites, jsonl):
    os.makedirs(OUT_DIR, exist_ok=True)
    print("baslangic yuk:", loadavg(), flush=True)
    for tur in range(1, runs + 1):
        for (name, kind, url) in sites:
            rec = await one_run(name, kind, url, tur)
            with open(jsonl, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if rec["status"] == "ok":
                print(f"[{tur}] {name:16s} ok B={int(rec['b_triggered'])} pend={rec['pending_at_load']} "
                      f"r30={rec['req_30ms']} n30-100={rec['n_30_100']} yuk={rec['load_avg']}", flush=True)
            else:
                print(f"[{tur}] {name:16s} DROP {rec.get('reason')} yuk={rec['load_avg']}", flush=True)
            await asyncio.sleep(0.4)


def report():
    rows = [json.loads(l) for l in open(JSONL, encoding="utf-8") if l.strip()]
    ok = [r for r in rows if r["status"] == "ok"]
    meas = [r for r in ok if r["tur"] >= 2]
    drops = [r for r in rows if r["status"] != "ok"]
    ncpu = 10
    loads = [r["load_avg"] for r in rows if r.get("load_avg") is not None]
    b = [r for r in meas if r["b_triggered"]]
    leak = [r for r in b if r["n_30_100"] > 0]
    L = []
    L.append("# t=0 yerleşme ölçümü, ikinci koşu (K-0074 A-0141)")
    L.append("")
    L.append("Tarih: 11.11.2026. Ham veri: `settle-t0-2/kosu.jsonl`. Betik: `settle-t0-2.py`. "
             "Ortak başsız tarayıcı 127.0.0.1:9333, ham CDP.")
    L.append("")
    if loads and max(loads) >= 20:
        L.append("**UYARI: yük altında; zaman değerleri ±.** Yük (1 dk, 10 çekirdek): "
                 f"{min(loads):.1f} – {max(loads):.1f}.")
        L.append("")
    L.append("## Yöntem")
    L.append("")
    L.append("- Her koşu yeni sekme. Gezinmeden önce sayfaya MutationObserver (en çok 5 ms'de 1 örnek) girer.")
    L.append("- Metin değişimi = `document.body.innerText` uzunluk+hash özetinin değişimi. Zaman sayfa saatiyle, load olayına göre.")
    L.append("- Bekleyen istek ve load+30 ms istekleri CDP monotonic zaman damgasından hesaplanır (ws gecikmesi yok).")
    L.append("- B tetiklendi = load anında bekleyen istek 0 VE load'dan sonraki 30 ms'de yeni istek yok.")
    L.append("- Tur 1 ısınma, ölçüme girmez. Turlar siteler arası çapraz. `data:`/`blob:` istekleri sayılmaz.")
    L.append("- Sınır: ağır yükte sayfa saati ve CDP saati arasında birkaç ms sapma olabilir. Özet hash'i değişimi görsel olmayan metin (gizli) için de sayar.")
    L.append("")
    L.append("## Site tablosu (tur 2-5)")
    L.append("")
    L.append("| Site | Tür | Geçerli | B tetik | Bekleyen (ort) | load+30ms istek | (0,30] | (30,100] | (100,300] | B koşusunda (30,100] | Düşen |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    names = []
    for r in rows:
        if r["site"] not in names:
            names.append(r["site"])
    leak_sites = {}
    for n in names:
        sm = [r for r in meas if r["site"] == n]
        sd = [r for r in drops if r["site"] == n]
        kind = next(r["kind"] for r in rows if r["site"] == n)
        if sm:
            sb = [r for r in sm if r["b_triggered"]]
            lk = sum(r["n_30_100"] for r in sb)
            if lk:
                leak_sites[n] = lk
            L.append(f"| {n} | {kind} | {len(sm)} | {len(sb)}/{len(sm)} | "
                     f"{sum(r['pending_at_load'] for r in sm)/len(sm):.1f} | "
                     f"{sum(r['req_30ms'] for r in sm)} | {sum(r['n_0_30'] for r in sm)} | "
                     f"{sum(r['n_30_100'] for r in sm)} | {sum(r['n_100_300'] for r in sm)} | "
                     f"{lk} | {len(sd)} |")
        else:
            L.append(f"| {n} | {kind} | 0 | - | - | - | - | - | - | - | {len(sd)} |")
    L.append("")
    L.append("## Düşen koşular (sebepleriyle)")
    L.append("")
    if drops:
        L.append("| Site | Tur | Sebep |")
        L.append("|---|---|---|")
        for r in drops:
            L.append(f"| {r['site']} | {r['tur']} | {r.get('reason','?')} |")
    else:
        L.append("Düşen koşu yok.")
    L.append("")
    L.append("## Toplamlar")
    L.append("")
    L.append(f"- Toplam koşu denemesi: {len(rows)} (ısınma dahil). Isınma geçerli: {len([r for r in ok if r['tur']==1])}.")
    L.append(f"- **Geçerli ölçüm koşusu (tur 2-5): {len(meas)}**")
    L.append(f"- Düşen koşu: {len(drops)}")
    L.append(f"- **B tetiklenen koşu: {len(b)} / {len(meas)}**" + (f" (%{round(100*len(b)/len(meas))})" if meas else ""))
    L.append(f"- **B koşularında (30,100] ms metin değişimi: {sum(r['n_30_100'] for r in b)}** ({len(leak)} koşuda)")
    L.append(f"- Kaçak siteler: {', '.join(f'{k} ({v})' for k, v in leak_sites.items()) or 'yok'}")
    L.append(f"- Tüm koşularda (30,100] değişim toplamı: {sum(r['n_30_100'] for r in meas)}")
    if loads:
        L.append(f"- Yük ortalaması aralığı (1 dk): {min(loads):.1f} – {max(loads):.1f} ({ncpu} çekirdek)")
    L.append("")
    L.append("## Karar")
    L.append("")
    if len(meas) < 60:
        L.append(f"**BİLGİ YETERSİZ** — geçerli koşu {len(meas)} < 60.")
    elif len(b) == 0:
        L.append("**BİLGİ YETERSİZ** — B hiç tetiklenmedi; şart sınanamadı.")
    elif leak:
        L.append(f"**D1 SAĞLANMADI** — B koşularında {sum(r['n_30_100'] for r in b)} adet (30,100] ms metin değişimi ({len(leak)} koşu).")
    else:
        L.append(f"**D1 SAĞLANDI (bu örneklemde)** — {len(b)} B koşusunda (30,100] ms metin değişimi 0.")
    open(REPORT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("rapor:", REPORT, "gecerli", len(meas), "B", len(b), "kacak", len(leak))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--out", default=JSONL)
    a = ap.parse_args()
    if a.report:
        report()
    elif a.smoke:
        pick = [s for s in SITES if s[0] in ("example.com", "hn", "wikipedia")]
        asyncio.run(suite(1, pick, os.path.join(OUT_DIR, "duman.jsonl")))
    else:
        asyncio.run(suite(a.runs, SITES, a.out))
