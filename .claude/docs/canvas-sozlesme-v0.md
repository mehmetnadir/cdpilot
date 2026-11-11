# Canlı tuval v0 — gün 0 sözleşmesi (dondurulmuş, 11.11.2026)

Girdi: `plan-canli-tuval-uygulama.md` (§1–§7, jüri koşulları §7 bağlayıcı), `plan-canli-tuval.md` (PRD).
Bu belge şeritlerin birbirine verdiği sözü sabitler. Sözleşmeyi yalnız lider değiştirir; şerit değişiklik
isterse raporunda yazar, kendisi değiştirmez.

## 1. Bölgeler ve sahiplik

| Şerit | `src/cdpilot.py` | `test/test.js` | Yeni dosyalar |
|---|---|---|---|
| A morph + sayfa betiği | `CANVAS-A BEGIN/END` | `CANVAS-A TESTS` (`canvas morph:`) | `test/canvas_fake_dom.js`, `test/canvas_morph.js`, `test/canvas_e2e.js`, `test/fixtures/canvas/state.html` |
| B host + istemci + CLI + güvenlik | `CANVAS-B BEGIN/END`, `CANVAS-B DISPATCH BEGIN/END` (`_cli_main` içi), `_slog_redact_args` içinde `canvas` dalı | `CANVAS-B TESTS` (`canvas host:`) | `test/canvas_fake_cdp.py`, `test/fixtures/canvas/exfil.html` |
| C stream + watch + ölçüm | `CANVAS-C BEGIN/END` | `CANVAS-C TESTS` (`canvas stream:`) | `test/canvas_bench.py`, `.claude/docs/olcum/canvas-*` |
| D events + MCP + örnek | `CANVAS-D BEGIN/END` | `CANVAS-D TESTS` (`canvas events:`) | `test/canvas_events_fake.py`, `examples/canvas/` |

Lider gün 0'da koydu (şerit değiştirmez): bölge başındaki ortak sabitler ve `CanvasError`, `_canvas_dir`,
`_canvas_check_name`, `_canvas_paths`; `DAEMON_SPAWN_SUBCMDS` (py ve `bin/cdpilot.js`) satırı;
`MCPServer.__init__` içinde `+ list(CANVAS_TOOLS)` ve `tools/call` içinde `_CANVAS_TOOL_NAMES` kancası.

## 2. Ortak sabitler (bölge başı)

| Ad | Değer | Not |
|---|---|---|
| `CANVAS_HOST_FLAG` | `--_canvas-host` | gizli host süreci; `--_` önekli, daemon'a girmez |
| `CANVAS_NAME_RE` | `^[a-z0-9_-]{1,32}$` | ad dosya yolu parçasıdır (K3) |
| `CANVAS_DEFAULT_NAME` | `main` | `--name` yoksa |
| `CANVAS_URL_FMT` | `http://cdpilot-canvas.invalid/{name}/` | host YALNIZ bu tam adresi doldurur; başka ad/yol/sorgu → 204 (K2) |
| `CANVAS_BINDING` | `__cdpilotCanvasEmit` | `Runtime.addBinding` |
| `CANVAS_OPS` | `set patch events close ping` | soket protokolü kapalı listesi (K3) |
| `CANVAS_PAGE_EVENT_TYPES` | `click submit input` | sayfanın binding ile diyebileceği türler (K5) |
| `CANVAS_HTML_MAX` / `CANVAS_MCP_HTML_MAX` | 1 MB / 256 KB | host içinde de uygulanır |
| `CANVAS_EVENT_RING` / `_BYTES` / `_ITEM_MAX` | 1.000 / 64 KB / 1 KB | halka tampon |
| `CANVAS_IDLE_EXIT_S` | 1.800 | host boşta çıkışı |

Dosyalar: `_canvas_dir()` = `<PROFILE_DIR>/canvas` (0700). `_canvas_paths(ad)` → `sock` (0600), `reg`
(`{name, targetId, browserContextId, pid, sock, started, allow_net, v}`, `_atomic_write_json`), `ready`.
Soket yolu 100 baytı aşarsa B kısa kullanıcı dizinine taşır (`bin/cdpilot.js` `daemonSockPath` kalıbı).

## 3. Sayfa betiği (şerit A verir, B yükler)

```
window.__cdpilotCanvas = Object.freeze({
  v,                       // CANVAS_RUNTIME_V (A: 1)
  patch(html, {final}),    // → Promise<{ok, ops:{add,del,move,upd}, ms, t_paint}>
  reset(),                 // B, set'ten önce çağırır: sarılan zamanlayıcıları temizler
  emit(o),                 // o = {type, action, id, data}; binding yoksa q'ya
  q,                       // binding gelmeden biriken olaylar
})
```

- `t_paint` = ikinci `requestAnimationFrame` içinde `Date.now()` (epoch ms). Boyama ölçümü binding'den
  DEĞİL, `Runtime.evaluate{awaitPromise:true}` dönüşünden gelir (K5: sayfa host türü olay yazamaz).
  Plan §1.1'deki eşzamanlı `{ok, ops, ms}` dönüşü bu nedenle Promise oldu (lider kararı, 11.11).
- Betikler yalnız `final:true` yamada çalışır. Gelen HTML'den `<meta http-equiv=refresh|content-security-policy>`
  ve `<base>` ayıklanır; CSP meta'sı her yamada başta yoksa eklenir (§3.3).
- Olay dinleyicisi: `[data-action]`/`[data-emit]` tık, form `submit`/`input` → `emit`. Başka tür yok.

## 4. Host soketi (şerit B sunar; B, C, D kullanır)

Tek satır JSON istek → tek satır JSON yanıt. İstek `op` ∈ `CANVAS_OPS`; başka op → `{ok:false, code:2}`.
Satır sınırı `CANVAS_HTML_MAX + 64 KB`.

| İstek | Yanıt |
|---|---|
| `{op:"set", html, t_cli?}` | `{ok, ms, t_paint}` |
| `{op:"patch", html, final, t_cli?}` | `{ok, ops, ms, t_paint}` |
| `{op:"events", after, max≤100, wait_ms≤25000}` | `{ok, events, next, dropped}` |
| `{op:"close"}` | `{ok}`; host sekmeyi ve bağlamı kapatır, soketi siler, çıkar |
| `{op:"ping"}` | `{ok, name, targetId, v, pid, uptime_s}` |
| hata | `{ok:false, error, code}` (code 1 çalışma, 2 kullanım/sınır) |

`t_cli` = `time.time_ns()` (son bayt okuma anı, C). Eval, ham CDP geçişi, CSP ya da `--allow-net` değiştirme
YOK; `--allow-net` yalnız host açılışında verilir.

İstemci (lider gün 0'da yazdı, ortak alanda; herkes çağırır, kimse değiştirmez):
- `_canvas_request(name, msg, timeout=10.0) -> dict` — host yok / zaman aşımı → `CanvasError(code 1)`.
- `_canvas_resolve_name(args) -> (name, kalan_args)` — `--name n` ya da `--name=n`.
- `_canvas_read_html(src) -> str` — dosya yolu ya da `-` (stdin); sınır aşımı → `CanvasError(code 2)`.

## 5. Olay şeması

`{seq, t, src, type, action, id, data}` — `t` epoch ms; `src` `page` ya da `host`.
Sayfa türleri `click|submit|input`; binding'den başka tür gelirse düşer. Host türleri `blocked|nav|closed`
(`src:"host"`). Sızıntı testi yalnız `src:"host"` `blocked` olaylarını sayar. `data` en çok 1 KB (kesilir).

## 6. CLI yüzeyi

| Komut | Sahibi | Çıktı |
|---|---|---|
| `canvas open [--name n] [--allow-net host]...` | B | `canvas: <ad> <targetId>` |
| `canvas set <dosya\|-> [--name n]` | B | `ok <ms> ms` |
| `canvas patch <dosya\|-> [--name n]` | B | `ok +add -del ~upd ↕move <ms> ms` (CLI yaması `final:true`) |
| `canvas stream [--name n]` | C | stdin bitince özet satırı |
| `canvas watch <dosya> [--name n]` | C | değişiklik başına bir satır; Ctrl+C temiz çıkış |
| `canvas events [--name n] [--follow] [--after N] [--max N] [--wait-ms N]` | D | satır başına bir JSON olay |
| `canvas close [--name n \| --all]` | B | `closed <ad>` |
| `canvas list` | B | ad, targetId, pid, yaş |

Çıkış kodları: 0 başarı · 1 çalışma hatası (host yok, CDP) · 2 kullanım ya da sınır. Windows: `canvas` her alt
komutta "not supported on Windows" + çıkış 1 (K7). Taze süreçte koşanlar (`DAEMON_SPAWN_SUBCMDS`):
`canvas open|stream|watch|events`; `set|patch|close|list` ince istemcidir, sıcak süreçte de koşar.

## 7. MCP (şerit D)

`browser_canvas_set{html, name?}`, `browser_canvas_patch{html, name?}`, `browser_canvas_events{after?, max?, wait_ms?, name?}`.
`CORE_TOOLS` dışında (C2). HTML alt sürece argv ile gitmez; stdin ya da 0600 geçici dosya. Sıcak kipte
(`CDPILOT_DAEMON=1`) çağrı süreç içinde koşar: `_canvas_request` doğrudan çağrılır. `wait_ms` +
iş ≤ `TOOL_TIMEOUT_S` (30 sn). 3 aracın şema token sayısı değişiklik notuna girer (PRD §8 S4).

## 8. Güvenlik koşulları (jüri §7 — birleşme kapısı)

K2 tam adres + 204 · K3 kapalı op listesi, ad deseni, sınırlar host içinde, dizin 0700 / soket 0600 ·
K4 HTML `Runtime.evaluate`'e yalnız `json.dumps` ile; belge kaybı `Page.getFrameTree` + `Page.frameNavigated`
ile, `window` alanlarıyla değil · K5 binding türleri süzülür · K8 `Fetch.requestPaused` hatası → gezinmeye
204, alt kaynağa `failRequest(BlockedByClient)`, asla `continueRequest`; `Fetch.enable` yalnız tuval
oturumunda, `requestStage:"Request"`; tarayıcı düzeyi `setAutoAttach` YASAK · C1 `Target.createBrowserContext{disposeOnDetach:true}`
(host SIGKILL'de bağlam ve sekme kapanır) · C2 MCP HTML argv'de yok · K9 genişletilmiş sızıntı e2e'si
(karşı deney dahil) ve SIGKILL e2e'si B'nin birleşme kapısı; D bunlar yeşil olmadan birleşmez.

## 9. Sıra

gün 0 (bu commit) → A ‖ B → C ‖ D (B'nin `_canvas_request` + host `patch/events` hazır) → güvenlik incelemesi
(A, B, C, D; `canvas stream` ve `canvas patch` uçtan uca) → jüri (yayın).

## v0.1 değişiklikleri (11.11, B2 güvenlik turu)

Kaynak: şerit B güvenlik incelemesi (ORTA-1, ORTA-2, DÜŞÜK D2–D9), lider kararı. Önceki bölümler yerinde kalır; bu
bölüm onları daraltır.

| Konu | v0.1 kuralı |
|---|---|
| Ad ve beyaz listeler | `CANVAS_NAME_RE` = `^[a-z0-9_-]{1,32}\Z`, her yerde `.fullmatch`. `--allow-net` ad deseni ve `data-action` deseni de `fullmatch` + `\Z`. Sebep: `$` sondaki `\n`'den önce de eşleşir; `'main\n'` geçiyordu. |
| Belge kanıtı (K4) | Host, yüklemeden sonra ve her `set`/`patch`'ten önce `Page.getFrameTree` ana çerçeve URL'sini tuval adresiyle karşılaştırır. Yazım, kanıtlanan belgenin varsayılan bağlamına (`uniqueContextId`) bağlanır. URL ya da bağlam değişmişse yazım `{ok:false, code:1}` ile reddedilir, host tuvali yeniden açar, `nav` olayı yazar. Başka belgeye yazım yok. |
| Açılış hatası | `Page.navigate` `errorText` döndürürse `canvas open` çıkış 1 verir; host sekmeyi ve bağlamı kapatıp çıkar. Hazır bekleme 5 sn → 60 sn (yükleme + kanıt; yüklü makinede 20 sn yetmedi). |
| Geçmiş (D1) | Her tuval yüklemesinden sonra `Page.resetNavigationHistory`: `history.back()` CSP'siz `about:blank` girdisine dönemez. |
| `set` temizliği (§3.3) | `set` HTML'inden `<base>`, `<meta http-equiv=refresh\|content-security-policy>` ve sayfanın `data-cdpilot-csp` meta'sı atılır; host CSP meta'sı başa (doctype varsa ondan sonra) eklenir. |
| WebRTC | CSP ve sandbox `RTCPeerConnection`'ı durdurmaz. Host, tuval oturumunda gezinmeden önce `Page.addScriptToEvaluateOnNewDocument{runImmediately:true}` ile 12 kurucuyu (`RTCPeerConnection` … `RTCCertificate`) `window` üstünde yapılandırılamaz `undefined` yapar. |
| Yanıt başlığı | Tuval yanıtı `X-DNS-Prefetch-Control: off` taşır. |
| `--allow-net` | `continueRequest` yalnız `https` ve port yok ya da 443 için. |
| Olay `data.url` | `blocked`/`nav` olaylarındaki `data.url` sayfa denetimindedir (page-controlled), en çok 256 karakter. İki tür ortak sınır: 100/sn, aşım `dropped`. |
| Sayfa dönüş alanları | Güvenilmez: `ms` sayı ya da `null` (CLI `?` yazar); `error` `"page: "` önekli, en çok 200 karakter; `code` {1, 2} değilse 1; `ops` yalnız tamsayı `add/del/move/upd`; geçersiz `t_paint` → host saati. |
| Soket | `op` dize değilse `{ok:false, code:2}`. Bozuk binding yükü (JSON hatası, `RecursionError`, biçim) düşer, `dropped`'a sayılır; host sürer. Hız sınırı ayrıştırmadan önce. |
| Süreç güvenliği | Kayıttaki pid'e SIGTERM yalnız `ps -o command=` `--_canvas-host <ad>` gösterirse; yoksa yalnız bayat dosyalar silinir. `canvas open` canlı ama yavaş hostun dosyalarını silmez (çıkış 1, `close` önerisi). |
| Windows | `os.name == 'nt'` ya da `AF_UNIX` yok → "not supported on Windows", çıkış 1 (Python 3.13+ Windows'ta `AF_UNIX` verebilir). |
| `project-stop` | Tuvalleri yalnız durdurulan proje geçerli proje ise kapatır (tuval dizini `PROFILE_DIR`'e aittir); `stop-all` geçerli projenin tuvallerini kapatmayı sürdürür. |
| e2e tarayıcısı | `CDPILOT_CANVAS_E2E_CDP=127.0.0.1:<port>` → o tarayıcı (yerelde ortak Chrome 9333; başlatma yok). Tanımsız ve `CDPILOT_E2E=1` → test kendi headless Chrome'unu boş portta, geçici `CDPILOT_HOME` ile `cdpilot launch` eder, sonunda `stop` eder. Dinleyici IP'si: loopback dışı IPv4 (macOS'ta loopback; `CDPILOT_CANVAS_E2E_LISTEN` ile değişir). |
| K9 karşı deneyi | Fixture'daki her vektörün adı ve kendi dinleyici kanalı var. Korumasız koşuda her vektör > 0 olmalı ya da testteki `UNMEASURABLE` haritasında gerekçesiyle durmalı; korumalı koşuda hepsi 0. |
