#!/usr/bin/env python3
"""settle-t0.py - High-precision t=0 settle & DOM text change measurement via raw CDP.

Measures DOM text changes (via in-page MutationObserver throttled to 5ms) from t=0,
tracks network requests at Page.loadEventFired and thereafter, and evaluates
Option B shortcut safety (pending requests == 0 at load and no new request in 30ms).
"""

import asyncio
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import websockets

CDP_HTTP_BASE = "http://127.0.0.1:9333"

INJECT_OBSERVER_JS = """(function() {
  window.__t0log = [];
  window.__t0dcl = null;
  window.__t0load = null;

  let lastReadTime = -999;
  let scheduledTimer = null;
  let lastRecordedLen = -1;

  function sample(extra) {
    const now = performance.now();
    lastReadTime = now;
    if (scheduledTimer) {
      clearTimeout(scheduledTimer);
      scheduledTimer = null;
    }
    let len = 0;
    try {
      len = document.body ? (document.body.innerText || '').length : 0;
    } catch(e) {
      len = 0;
    }
    const item = { t: now, len: len };
    if (extra) {
      for (const k in extra) {
        item[k] = extra[k];
      }
    }
    if (item.len !== lastRecordedLen || extra) {
      lastRecordedLen = item.len;
      window.__t0log.push(item);
    }
    return len;
  }

  function onMutation() {
    const now = performance.now();
    const elapsed = now - lastReadTime;
    if (elapsed >= 5) {
      sample();
    } else if (!scheduledTimer) {
      scheduledTimer = setTimeout(() => {
        sample();
      }, 5 - elapsed);
    }
  }

  window.addEventListener('DOMContentLoaded', () => {
    window.__t0dcl = performance.now();
    sample({ isDCL: true });
  }, { capture: true, once: true });

  window.addEventListener('load', () => {
    window.__t0load = performance.now();
    sample({ isLoad: true });
  }, { capture: true, once: true });

  const observer = new MutationObserver(() => {
    onMutation();
  });

  function startObserver() {
    const el = document.documentElement || document;
    if (el) {
      try {
        observer.observe(el, { childList: true, characterData: true, subtree: true });
      } catch(e) {}
    }
  }

  startObserver();
  if (document.readyState === 'loading') {
    document.addEventListener('readystatechange', startObserver);
  }
})();"""

EVAL_PAGE_JS = """(() => {
  let len = 0;
  try {
    len = document.body ? (document.body.innerText || '').length : 0;
  } catch(e) {
    len = 0;
  }
  const now = performance.now();
  window.__t0log.push({ t: now, len: len, isEnd: true });

  let nav = null;
  try {
    const entries = performance.getEntriesByType('navigation');
    if (entries && entries.length > 0) {
      const e = entries[0];
      nav = {
        loadEventStart: e.loadEventStart,
        loadEventEnd: e.loadEventEnd,
        domContentLoadedEventStart: e.domContentLoadedEventStart,
        domContentLoadedEventEnd: e.domContentLoadedEventEnd,
        responseStart: e.responseStart,
        duration: e.duration
      };
    }
  } catch(e) {}

  const title = document.title || '';
  const bodyText = (document.body ? (document.body.innerText || '') : '').slice(0, 500);

  return {
    dcl: window.__t0dcl,
    load: window.__t0load,
    log: window.__t0log,
    nav: nav,
    title: title,
    bodySnippet: bodyText,
    finalLen: len
  };
})()"""


def get_uptime_load():
    """Return 1m, 5m, 15m load averages as string."""
    try:
        with open("/proc/loadavg", "r") as f:
            parts = f.read().split()
            return f"{parts[0]} {parts[1]} {parts[2]}"
    except Exception:
        pass
    try:
        import subprocess
        out = subprocess.check_output(["uptime"], text=True)
        m = re.search(r"load averages?:\s*([0-9\.\s]+)", out)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return "unknown"


def is_bot_challenge(title, body):
    haystack = f"{title} {body}".lower()
    patterns = [
        "just a moment...",
        "attention required! | cloudflare",
        "verify you are human",
        "are you a human",
        "robot or human?",
        "cf-chl-widget",
        "turnstile challenge",
    ]
    return any(p in haystack for p in patterns)


def compute_silence_return(t_load, event_times, silence_thresh, cap=0.300):
    """Simulate cdpilot's event silence wait loop.

    Returns the time (in ms relative to load) when the rule would return.
    """
    t_curr = t_load
    for e in event_times:
        if e > t_load + cap:
            break
        gap = e - t_curr
        if gap >= silence_thresh:
            return round((min(t_curr + silence_thresh, t_load + cap) - t_load) * 1000, 1)
        t_curr = e
    if (t_load + cap) - t_curr >= silence_thresh:
        return round((min(t_curr + silence_thresh, t_load + cap) - t_load) * 1000, 1)
    return round(cap * 1000, 1)


async def run_single_measurement(browser_ws_url, url, post_load_wait=2.5, page_timeout=35.0):
    """Run one measurement on a site using raw CDP."""
    load_avg = get_uptime_load()
    t_start = time.monotonic()

    # Step 1: Create fresh target
    async with websockets.connect(browser_ws_url, max_size=100 * 1024 * 1024) as b_ws:
        await b_ws.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": "about:blank"}}))
        res = json.loads(await b_ws.recv())
        target_id = res["result"]["targetId"]

    page_ws_url = f"ws://127.0.0.1:9333/devtools/page/{target_id}"

    try:
        async with websockets.connect(page_ws_url, max_size=100 * 1024 * 1024) as p_ws:
            # Enable domains & inject observer
            await p_ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
            await p_ws.send(json.dumps({"id": 2, "method": "Network.enable"}))
            await p_ws.send(json.dumps({"id": 3, "method": "Runtime.enable"}))
            await p_ws.send(json.dumps({
                "id": 4,
                "method": "Page.addScriptToEvaluateOnNewDocument",
                "params": {"source": INJECT_OBSERVER_JS}
            }))

            # Drain setup confirmations
            got = set()
            while got != {1, 2, 3, 4}:
                msg = json.loads(await p_ws.recv())
                if msg.get("id") in (1, 2, 3, 4):
                    got.add(msg["id"])

            # Navigate
            nav_sent_time = time.monotonic()
            await p_ws.send(json.dumps({"id": 10, "method": "Page.navigate", "params": {"url": url}}))

            load_fired = False
            load_mono_time = None
            pending_requests = set()
            pending_at_load = 0
            requests_in_30ms = 0
            all_requests = {}
            cdp_events_after_load = []

            while True:
                now = time.monotonic()
                if load_fired:
                    remaining = (load_mono_time + post_load_wait) - now
                    if remaining <= 0:
                        break
                    timeout = remaining
                else:
                    if now - nav_sent_time > page_timeout:
                        return {
                            "status": "timeout",
                            "url": url,
                            "load_avg": load_avg,
                            "error": f"Page did not fire load event within {page_timeout}s"
                        }
                    timeout = 1.0

                try:
                    raw = await asyncio.wait_for(p_ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    if load_fired:
                        break
                    continue

                msg = json.loads(raw)
                m = msg.get("method", "")
                now = time.monotonic()

                if load_fired:
                    cdp_events_after_load.append(now)

                if m == "Network.requestWillBeSent":
                    rid = msg["params"]["requestId"]
                    req_url = msg["params"].get("request", {}).get("url", "")
                    ts = msg["params"].get("timestamp")
                    pending_requests.add(rid)
                    all_requests[rid] = {"url": req_url, "start_ts": ts, "start_mono": now}
                    if load_fired and load_mono_time:
                        dt = now - load_mono_time
                        if 0 <= dt <= 0.030:
                            requests_in_30ms += 1

                elif m in ("Network.loadingFinished", "Network.loadingFailed"):
                    rid = msg["params"]["requestId"]
                    pending_requests.discard(rid)
                    if rid in all_requests:
                        all_requests[rid]["end_mono"] = now

                elif m == "Page.loadEventFired":
                    load_fired = True
                    load_mono_time = now
                    pending_at_load = len(pending_requests)

            # Evaluate in-page log and navigation entries
            await p_ws.send(json.dumps({
                "id": 100,
                "method": "Runtime.evaluate",
                "params": {"expression": EVAL_PAGE_JS, "returnByValue": True}
            }))

            eval_res = None
            eval_deadline = time.monotonic() + 5.0
            while time.monotonic() < eval_deadline:
                try:
                    raw = await asyncio.wait_for(p_ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    break
                msg = json.loads(raw)
                if msg.get("id") == 100:
                    eval_res = msg.get("result", {}).get("result", {}).get("value")
                    break

            if not eval_res:
                return {
                    "status": "eval_error",
                    "url": url,
                    "load_avg": load_avg,
                    "error": "Failed to read __t0log from page"
                }

            # Check bot challenge
            title = eval_res.get("title", "")
            body_snippet = eval_res.get("bodySnippet", "")
            if is_bot_challenge(title, body_snippet):
                return {
                    "status": "bot_challenge",
                    "url": url,
                    "title": title,
                    "load_avg": load_avg,
                    "note": "Bot challenge detected"
                }

            # Process timing & logs
            log = eval_res.get("log", [])
            nav = eval_res.get("nav") or {}
            dcl_time = eval_res.get("dcl")
            load_time = eval_res.get("load")
            if load_time is None and nav.get("loadEventStart"):
                load_time = nav["loadEventStart"]
            if load_time is None:
                # If page load event listener did not fire, infer from last log before settle
                load_time = log[-1]["t"] if log else 0.0

            # Option B trigger condition:
            # pending == 0 at load AND no request starts within 30 ms after load
            b_triggered = (pending_at_load == 0) and (requests_in_30ms == 0)

            # Silence return times
            ret_100ms = compute_silence_return(load_mono_time, cdp_events_after_load, 0.100, 0.300)
            ret_30ms = compute_silence_return(load_mono_time, cdp_events_after_load, 0.030, 0.300)

            # Analyze text lengths at specific relative time points
            def get_len_at(rel_ms):
                target_t = load_time + rel_ms
                last_len = 0
                for item in log:
                    if item.get("t", 0) <= target_t:
                        last_len = item.get("len", 0)
                    else:
                        break
                return last_len

            len_load = get_len_at(0)
            len_30 = get_len_at(30)
            len_100 = get_len_at(100)
            len_300 = get_len_at(300)
            len_2000 = get_len_at(2000)

            # Changes in windows: (load, load+30], (load+30, load+100], (load+100, load+300], (load+300, load+2000]
            def analyze_window(rel_start, rel_end):
                w_start = load_time + rel_start
                w_end = load_time + rel_end
                changes = 0
                prev_len = None
                first_len = None
                last_len = None
                for item in log:
                    t = item.get("t", 0)
                    cur_len = item.get("len", 0)
                    if t <= w_start:
                        prev_len = cur_len
                        continue
                    if t <= w_end:
                        if first_len is None:
                            first_len = prev_len
                        if prev_len is not None and cur_len != prev_len:
                            changes += 1
                        prev_len = cur_len
                        last_len = cur_len
                    else:
                        break
                delta = abs((last_len if last_len is not None else len_load) - (first_len if first_len is not None else len_load))
                return changes, delta

            ch_0_30, delta_0_30 = analyze_window(0, 30)
            ch_30_100, delta_30_100 = analyze_window(30, 100)
            ch_100_300, delta_100_300 = analyze_window(100, 300)
            ch_300_2000, delta_300_2000 = analyze_window(300, 2000)

            # Last text change after load
            last_change_ms = 0
            cur_l = len_load
            for item in log:
                t = item.get("t", 0)
                if t > load_time:
                    if item.get("len", 0) != cur_l:
                        last_change_ms = max(last_change_ms, round(t - load_time, 1))
                        cur_l = item.get("len", 0)

            return {
                "status": "ok",
                "url": url,
                "title": title,
                "load_avg": load_avg,
                "dcl_ms": round(dcl_time, 1) if dcl_time else None,
                "load_ms": round(load_time, 1) if load_time else None,
                "pending_at_load": pending_at_load,
                "requests_in_30ms": requests_in_30ms,
                "b_triggered": b_triggered,
                "ret_100ms": ret_100ms,
                "ret_30ms": ret_30ms,
                "len_load": len_load,
                "len_30": len_30,
                "len_100": len_100,
                "len_300": len_300,
                "len_2000": len_2000,
                "changes_0_30": ch_0_30,
                "delta_0_30": delta_0_30,
                "changes_30_100": ch_30_100,
                "delta_30_100": delta_30_100,
                "changes_100_300": ch_100_300,
                "delta_100_300": delta_100_300,
                "changes_300_2000": ch_300_2000,
                "delta_300_2000": delta_300_2000,
                "last_change_ms": last_change_ms,
                "log_count": len(log),
                "cdp_events_after_load": len(cdp_events_after_load)
            }

    finally:
        # Step 3: Always close target
        try:
            req = urllib.request.Request(f"{CDP_HTTP_BASE}/json/close/{target_id}")
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass


async def main_suite():
    import argparse
    parser = argparse.ArgumentParser(description="settle-t0 measurement")
    parser.add_argument("--runs", type=int, default=5, help="Number of runs per site (default: 5)")
    parser.add_argument("--sites", type=str, default=None, help="Comma-separated sites or None for default")
    parser.add_argument("--wait", type=float, default=2.5, help="Post-load wait in seconds (default: 2.5)")
    parser.add_argument("--timeout", type=float, default=35.0, help="Page load timeout in seconds (default: 35.0)")
    args = parser.parse_args()

    v = json.loads(urllib.request.urlopen(f"{CDP_HTTP_BASE}/json/version").read())
    b_ws_url = v["webSocketDebuggerUrl"]

    if args.sites:
        sites = [s.strip() for s in args.sites.split(",") if s.strip()]
    else:
        # Target sites (18 sites covering SPAs, framework docs, service workers, feeds)
        sites = [
            "https://react.dev/",
            "https://angular.dev/",
            "https://vuejs.org/",
            "https://svelte.dev/",
            "https://nextjs.org/",
            "https://astro.build/",
            "https://remix.run/",
            "https://github.com/mehmetnadir/cdpilot",
            "https://news.ycombinator.com/",
            "https://en.wikipedia.org/wiki/Web_browser",
            "https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver",
            "https://web.dev/",
            "https://squoosh.app/",
            "https://excalidraw.com/",
            "https://www.npmjs.com/package/cdpilot",
            "https://example.com/",
            "https://httpbin.org/forms/post",
            "https://lobste.rs/",
            "https://www.youtube.com/",
        ]

    total_runs = args.runs
    raw_dir = tempfile.mkdtemp(prefix="settle_t0_")
    print(f"Settle t=0 ölçümü başlıyor. Ham veriler: {raw_dir}")
    print(f"Toplam {len(sites)} site × {total_runs} tur (Tur 1 ısınma, Tur 2-{total_runs} ölçüm).")
    print(f"Başlangıç sistem yükü: {get_uptime_load()}\n", flush=True)

    results_by_site = {s: [] for s in sites}

    # Interleaved runs across sites
    for r in range(1, total_runs + 1):
        is_warmup = (r == 1)
        label = "Isınma (Tur 1)" if is_warmup else f"Ölçüm (Tur {r})"
        print(f"=== {label} Başlıyor (yük: {get_uptime_load()}) ===", flush=True)

        for s in sites:
            try:
                res = await run_single_measurement(b_ws_url, s, post_load_wait=args.wait, page_timeout=args.timeout)
            except Exception as e:
                res = {"status": "error", "url": s, "error": str(e), "load_avg": get_uptime_load()}

            res["run"] = r
            res["is_warmup"] = is_warmup
            results_by_site[s].append(res)

            # Save raw json
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_")
            raw_path = os.path.join(raw_dir, f"{slug}_run{r}.json")
            with open(raw_path, "w") as f:
                json.dump(res, f)

            st = res.get("status")
            if st == "ok":
                b_trig = "EVET" if res["b_triggered"] else "HAYIR"
                print(f"  [{r}/{total_runs}] {s:45s} | B:{b_trig:5s} | Bekleyen:{res['pending_at_load']} | "
                      f"Metin ch[30-100]:{res['changes_30_100']} | Son:{res['last_change_ms']}ms | Yük:{res['load_avg']}", flush=True)
            elif st == "bot_challenge":
                print(f"  [{r}/{total_runs}] {s:45s} | BOT CHALLENGE: Atlandı | Yük:{res.get('load_avg')}", flush=True)
            else:
                print(f"  [{r}/{total_runs}] {s:45s} | {st.upper()}: {res.get('error','')} | Yük:{res.get('load_avg')}", flush=True)

            # Brief breather between navigations
            await asyncio.sleep(0.5)

    print("\nTüm koşular tamamlandı. Rapor üretiliyor...", flush=True)
    generate_markdown_report(results_by_site, raw_dir)


def median(values):
    if not values:
        return 0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2 == 1:
        return s[mid]
    return round((s[mid - 1] + s[mid]) / 2, 1)


def generate_markdown_report(results_by_site, raw_dir):
    report_path = "/Users/nadir/01dev/cdpilot/.claude/docs/olcum/settle-t0-2026-11-10.md"

    # Aggregates across measurement runs (runs 2..5)
    total_valid_runs = 0
    total_b_triggered = 0
    total_text_changes_30_100_when_b = 0
    total_text_changes_30_100_all = 0

    table_rows = []
    skipped_sites = []

    for site, runs in results_by_site.items():
        meas_runs = [r for r in runs if not r.get("is_warmup")]
        warmup_run = next((r for r in runs if r.get("is_warmup")), None)

        valid_meas = [r for r in meas_runs if r.get("status") == "ok"]

        if not valid_meas:
            fallback = meas_runs[0] if meas_runs else (runs[0] if runs else {})
            st = fallback.get("status", "unknown")
            note = fallback.get("note") or fallback.get("error") or st
            skipped_sites.append((site, st, note))
            continue

        n_meas = len(valid_meas)
        b_count = sum(1 for r in valid_meas if r["b_triggered"])
        b_rate = f"{b_count}/{n_meas} (%{round(b_count / n_meas * 100)})"

        total_valid_runs += n_meas
        total_b_triggered += b_count

        # Text changes in windows across valid measurement runs
        ch_0_30 = sum(r["changes_0_30"] for r in valid_meas)
        ch_30_100 = sum(r["changes_30_100"] for r in valid_meas)
        ch_100_300 = sum(r["changes_100_300"] for r in valid_meas)
        ch_300_2000 = sum(r["changes_300_2000"] for r in valid_meas)

        total_text_changes_30_100_all += ch_30_100

        # Check re-open condition: changes in 30-100ms when B triggered
        b_runs = [r for r in valid_meas if r["b_triggered"]]
        ch_30_100_b = sum(r["changes_30_100"] for r in b_runs)
        total_text_changes_30_100_when_b += ch_30_100_b

        med_last_change = median([r["last_change_ms"] for r in valid_meas])
        avg_ret_30 = round(sum(r["ret_30ms"] for r in valid_meas) / n_meas, 1)
        avg_ret_100 = round(sum(r["ret_100ms"] for r in valid_meas) / n_meas, 1)

        sample_load = valid_meas[0].get("load_avg", "unknown")

        table_rows.append({
            "site": site,
            "b_rate": b_rate,
            "ch_0_30": ch_0_30,
            "ch_30_100": ch_30_100,
            "ch_100_300": ch_100_300,
            "ch_300_2000": ch_300_2000,
            "med_last_ms": med_last_change,
            "ret_30": avg_ret_30,
            "ret_100": avg_ret_100,
            "load": sample_load,
            "warmup_b": "EVET" if (warmup_run and warmup_run.get("b_triggered")) else "HAYIR",
            "warmup_ch_30_100": warmup_run.get("changes_30_100", 0) if warmup_run and warmup_run.get("status") == "ok" else "-"
        })

    # Build markdown content
    md = []
    md.append("# t=0 DOM Yerleşme ve 30 ms Kısayolu (Seçenek B) Ölçüm Raporu")
    md.append("")
    md.append(f"**Tarih:** 10.11.2026  ")
    md.append(f"**Ortam:** Apple M1 Max (macOS arm64), ortak başsız Chrome 152 (`127.0.0.1:9333`), raw CDP.  ")
    md.append(f"**Sistem yükü (uptime):** `bash /Users/nadir/01dev/conductor/perf-1910/agir.sh` kuyruğu altında ölçüldü.  ")
    md.append("")
    md.append("## 1. Metot ve Sınırlar")
    md.append("")
    md.append("- **t=0 Doğrudan Gözlem:** Her sayfa için `Target.createTarget` ile bağımsız sekme açıldı. Sayfa henüz yüklenmeden `Page.addScriptToEvaluateOnNewDocument` ile `MutationObserver` (childList, characterData, subtree) enjekte edildi. `document.body.innerText.length` okuması reflow maliyetini sınırlamak için en çok 5 ms'de 1 defa örneklendi (trailing timer ile son durum kaçırılmadı).")
    md.append("- **Ağ ve Olay Takibi:** `Page.loadEventFired` anındaki bekleyen istekler (`Network.requestWillBeSent` − `loadingFinished/Failed`) ve yük sonrası ilk 30 ms'de başlayan istekler izlendi.")
    md.append("- **Seçenek B Tetik Koşulu:** Yükleme anında bekleyen istek sayısı == 0 VE yükleme sonrası ilk 30 ms içinde yeni istek başlamamışsa Seçenek B tetiklenir.")
    md.append("- **Sessizlik Penceresi Simülasyonu:** `Page.loadEventFired` sonrasındaki tüm CDP olay varış zamanları kaydedildi; 100 ms kuralı (100 ms sessizlik veya 300 ms tavan) ile 30 ms kuralının (30 ms sessizlik veya 300 ms tavan) dönüş zamanları hesaplandı.")
    md.append("- **Koşu Düzeni:** Her site için 5 tur (Tur 1 ısınma, Tur 2-5 ölçüm). Önbellek ve makine yük dalgalanmasını dengelemek için siteler ardışık değil turlar arası çapraz (interleaved) çalıştırıldı.")
    md.append("- **Sınırlar:** Aşırı makine yükü altında DNS ve harici varlık gecikmeleri nedeniyle bazı siteler yükleme zaman aşımına uğrayabilir; bot doğrulaması (Cloudflare/Turnstile) gösteren siteler kural gereği atlanmıştır.")
    md.append("")
    md.append("## 2. Ölçüm Sonuçları (Tur 2–5 Ölçüm Koşuları)")
    md.append("")
    md.append("| Site | B Tetikleme | Metin Değişimi (0-30ms] | Metin Değişimi (30-100ms] | Metin Değişimi (100-300ms] | Metin Değişimi (300-2000ms] | Medyan Son Değişim (+ms) | 30ms Kural Dönüş | 100ms Kural Dönüş | Yük Ortalaması |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")

    for r in table_rows:
        md.append(f"| {r['site']} | {r['b_rate']} | {r['ch_0_30']} | {r['ch_30_100']} | {r['ch_100_300']} | {r['ch_300_2000']} | +{r['med_last_ms']} ms | +{r['ret_30']} ms | +{r['ret_100']} ms | {r['load']} |")

    md.append("")
    md.append("### Isınma Koşusu (Tur 1) Özeti")
    md.append("")
    md.append("| Site | Tur 1 B Tetikledi mi? | Tur 1 (30-100ms] Değişim |")
    md.append("|---|---|---|")
    for r in table_rows:
        md.append(f"| {r['site']} | {r['warmup_b']} | {r['warmup_ch_30_100']} |")

    if skipped_sites:
        md.append("")
        md.append("### Atlanan / Zaman Aşımına Uğrayan Siteler")
        md.append("")
        for s, st, note in skipped_sites:
            md.append(f"- **{s}**: `{st}` — {note}")

    md.append("")
    md.append("## 3. Toplamlar ve İstatistikler")
    md.append("")
    overall_b_rate = round(total_b_triggered / max(1, total_valid_runs) * 100, 1)
    md.append(f"- **Geçerli Ölçüm Koşusu Sayısı:** {total_valid_runs} (ısınma hariç)")
    md.append(f"- **Seçenek B Tetikleme Sayısı:** {total_b_triggered} / {total_valid_runs} (%{overall_b_rate})")
    md.append(f"- **(30, 100] ms Aralığında Toplam Metin Değişimi (Tüm Koşular):** {total_text_changes_30_100_all}")
    md.append(f"- **(30, 100] ms Aralığında Metin Değişimi (B'nin Tetiklendiği Koşular):** **{total_text_changes_30_100_when_b}**")
    md.append("")
    md.append("## 4. Karar ve Yeniden Açma Şartı (Verdict)")
    md.append("")
    if total_text_changes_30_100_when_b == 0:
        md.append("> [!IMPORTANT]")
        md.append(f"> **Yeniden Açma Şartı SAĞLANDI (0 Kaçak).**")
        md.append(f"> Seçenek B'nin tetiklendiği {total_b_triggered} koşunun hiçbirinde (%100 güvenlik) load+30 ms ile load+100 ms arasında metin (`innerText`) değişimi gerçekleşmemiştir (değişim sayısı = 0).")
        md.append(f"> Seçenek B, bekleyen ağ isteği bulunmadığında 100 ms sabit bekleme yerine 30 ms sessizlik sonrası dönerek güvenle ~70 ms kazandırmaktadır.")
    else:
        md.append("> [!WARNING]")
        md.append(f"> **Yeniden Açma Şartı SAĞLANAMADI.**")
        md.append(f"> Seçenek B'nin tetiklendiği koşullarda load+30 ms ile load+100 ms arasında {total_text_changes_30_100_when_b} adet metin değişimi gözlemlenmiştir. Erken dönüş DOM metninin eksik okunmasına yol açabilir.")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print(f"\nRapor başarıyla yazıldı: {report_path}")


if __name__ == "__main__":
    asyncio.run(main_suite())
