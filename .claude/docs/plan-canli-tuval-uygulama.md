# Canlı tuval — uygulama planı (`cdpilot canvas`)
Durum: TASLAK, 10.11.2026. Girdi: `plan-canli-tuval.md` (PRD §1–§8, jüri D-0043). Kod yazılmadı.
Bu belge kod şeritlerinin soru sormadan yürüteceği plandır. Kod iddiaları `src/cdpilot.py` (kısaca `py`) ve
`bin/cdpilot.js` içinde grep sonucuna dayanır (işlev adı ya da satır). **[DV]** = doğrulanmadı.
**[ÖLÇÜLDÜ]** = 10.11.2026'da paylaşılan Chrome 152'de (127.0.0.1:9333) ham CDP ile denendi; sekmeler kapatıldı.
Başlama tetiği (PRD §8 S1): çift kip CI yeşil + 0.9.6 belgeleri; o güne dek bu plan yalnız okunur.
## 0. Karar özeti
| # | Karar | Neden (kanıt) |
|---|---|---|
| K1 | Morph betiğini **kendimiz yazarız** (~300 satır), `CANVAS_RUNTIME_JS` dizesi, `WEBMCP_LIST_JS` kalıbı | §1 |
| K2 | Tuval belgesi **sunucu tarafından değil, host süreci tarafından** sunulur: `Fetch.fulfillRequest` ile `http://cdpilot-canvas.invalid/<ad>/` adresine başlıklı yanıt (CSP + `sandbox allow-scripts`) | meta CSP tek başına `window.open` ve gezinmeyi durdurmadı [ÖLÇÜLDÜ] |
| K3 | Uzun ömürlü WebSocket'in evi: yeni **canvas host** süreci (gizli `--_canvas-host`). Daemon değil | §2.0 |
| K4 | `set` = `Page.setDocumentContent`; `patch` = `Runtime.evaluate` içinde morph | §2.2 |
| K5 | Olay: `Runtime.addBinding` host'ta; halka tampon + imleç; MCP imleçli sınırlı yoklama | §2.5 |
| K6 | Ölçüm: çift `requestAnimationFrame` + binding, saat = epoch ms | §4 |
| K7 | Windows v0'da **yok**: host Unix soketi ister; güvenlik koruması olmadan tuval açılmaz | §2.0, §6 |

## 1. Morph (DOM yaması)
### 1.1 Yazmak mı, uyarlamak mı
| Seçenek | Lisans / bağımlılık | Boyut | Karar |
|---|---|---|---|
| idiomorph kodunu gömmek | BSD-2: bildirim paketle dağıtılır | ~1.500 satır | hayır |
| morphdom kodunu gömmek | MIT: bildirim paketle dağıtılır | ~700 satır | hayır |
| **Kendi yazımımız**, algoritma fikri (kimlik kümesi eşleme, yerinde güncelleme) | kod kopyası yok, bildirim gerekmez | ≤ 300 satır, ≤ 10 KB kaynak | **evet** |

- Sıfır bağımlılık kuralı korunur: `package.json` değişmez. Fikir kaynağı `README`'de bir cümleyle anılır.
- Yer: `py` içinde `CANVAS_RUNTIME_JS = r"""..."""` (`WEBMCP_LIST_JS` satır 18227 ve `_SHADOW_QUERY_JS` satır 534 aynı kalıp).
  Düğüm testleri dizeyi `src/cdpilot.py` dosyasından düzenli ifadeyle çıkarır; ikinci kopya yok.
- Çalışma ortamı: ana dünya (isolated world yok). Sayfa betiği `Array.prototype`'ı bozarsa yama bozulur; kendi tuvalidir,
  kabul (risk R5). Çekirdek kapanış içinde `Object.freeze`'li gizli yardımcılar kullanır.
- Genel yüzey (sözleşme, şerit A dondurur): `window.__cdpilotCanvas = {v, patch(html, {final}), emit(o), q}`.
  `patch` → `{ok, ops:{add,del,move,upd}, ms}`. Binding adı `__cdpilotCanvasEmit`.

### 1.2 Korunacak durum
| Durum | Kural |
|---|---|
| Odak | Eşleşen düğüm yerinde güncellenir, taşınmaz. Odaklı düğüm `insertBefore` ile taşınmaz (Chrome taşınan düğümün odağını bırakır): çevresindeki düğümler taşınır |
| Seçim (input/textarea) | Düğüm kalıcı olduğundan `selectionStart/End/Direction` kalır |
| Seçim (`Range`) | Değişen metin düğümünde `nodeValue` yazmadan önce (düğüm, ofset) çiftleri kaydedilir; sonra uzunluğa kırpılarak geri konur |
| Kaydırma | Belge değişmez → pencere kaydırması kalır. Eşleşen öğenin `scrollTop/Left` değeri düğümle kalır. Eşleşmeyen yeni düğüm 0'dan başlar |
| Form değeri (`value`, `checked`, `selected`, textarea metni) | Canlı değer korunur. Yeni HTML'in özniteliği **önceki uygulanan** öznitelikten farklıysa (LLM bilerek değiştirdi) yazılır. Önceki öznitelik `WeakMap(düğüm → son uygulanan)` içinde tutulur |
| `<details open>` | Form değeri gibi: kullanıcı açtıysa `open` korunur; LLM `open` özniteliğini değiştirirse yazılır |
| `<dialog>` | `:modal` olan açık dialog'un `open` özniteliğine dokunulmaz, düğüm silinmez ya da değiştirilmez; yalnız içeriği eşitlenir. LLM yeni `<dialog open>` yazarsa kipsiz açılır |
| `<script>` | Yeni ve kapanmış betik düğümü yeniden oluşturulup çalıştırılır. Eşleşen eşit betik **bir daha çalışmaz**. `stream` betikleri son yamaya (EOF) kadar tutar (§2.4) |
| `<meta http-equiv>` CSP/refresh, `<base>` | Gelen HTML'den ayıklanır; CSP meta'sı her yamada başta yoksa eklenir (§3.3) |

Zamanlayıcı sızıntısı: `setTimeout/setInterval/requestAnimationFrame` sarmalayıcısı kimlikleri tutar; `set` hepsini temizler
(≈ 15 satır). Aynı pencere `setDocumentContent` ile sürdüğü için eski zamanlayıcılar yoksa yaşar [ÖLÇÜLDÜ: pencere ve dinleyiciler kalıyor].

### 1.3 Anahtarlı eşleme
- Anahtar = `id`, yoksa `data-key`. Anahtar yoksa konum + `nodeName` ile yumuşak eşleme.
- Çocuk listesi iki geçişlidir: (1) yeni anahtar kümesi çıkarılır; kümede olmayan anahtarlı eski düğümler silinir;
  (2) yeni çocuklar sırayla gezilir: imleçteki eski düğüm uyuşursa yerinde; anahtarlıysa haritadan alınıp (odaklı değilse) taşınır;
  anahtarsızsa aynı etiketli ilk anahtarsız eski düğüm; yoksa yeni düğüm eklenir. Artan eski düğümler silinir.
- Farklı etiket → `replaceWith`. Odağı içeren alt ağaç değiştirilirse odak kaybı kabul edilir ve `ops` içinde sayılır.
- Öznitelik: eksik olan silinir, farklı olan yazılır; `value/checked/open/selected` §1.2 kuralıyla.
- Yarım HTML: `DOMParser`/`<template>` kapanmamış etiketi tamamlar. Yamadan önce ayrıştırma hatası beklenmez; boş girdi = yama yok.

### 1.4 Boyut bütçesi
Morph çekirdeği ≤ 300 satır / ≤ 10 KB kaynak; tüm `CANVAS_RUNTIME_JS` (morph, emit, zamanlayıcı sarmalayıcı, CSP kontrolü) ≤ 14 KB.
Betik bir kez yüklenir; çağrı başına yalnız HTML gider (`__cdpilotCanvas.v === N` sorgusu ~1 gidiş-dönüş). `test.js` uzunluk üst sınırını sabit tutar.

### 1.5 Tarayıcısız test kararı: **ikisi birden**
| Katman | Dosya | Ne kanıtlar | Ne zaman |
|---|---|---|---|
| Küçük sahte DOM (≤ 250 satır: Node/Element/Text, attr Map, `insertBefore/removeChild`, `value/checked/open`, `activeElement`, taşımada blur simülasyonu, işlem sayaçları, fixture HTML için küçük ayrıştırıcı) | `test/canvas_fake_dom.js` + `test/canvas_morph.js` | anahtarlı yeniden sıralama, **en az işlem sayısı**, öznitelik farkı, §1.2 kuralları, idempotans (tohumlu 200 rastgele ağaç: `morph(a→b)` sonrası seri hâl = `b`) | her `node test/test.js` |
| Paylaşılan başsız Chrome, kapılı e2e (`CDPILOT_E2E=1`, kalıp `test.js:5220`) | `test/canvas_e2e.js` (şerit A) | gerçek odak/selection/kaydırma/`<details>`/`<dialog>` (modal), IME'siz yazma, 1.000 yama bellek (`Performance.getMetrics`) | CI `e2e` işi + elle |
Sahte DOM yalnız mantığı tutar; tarayıcı anlambilimi (taşımada blur, modal dialog) yalnız e2e'de kanıtlanır. İlk kalıp:
`test/webmcp_fake_page.js` (Node `vm` içinde kayıt tutan sahte belge) ve `test/webmcp_fake_cdp.py` — aynı biçim.

## 2. CDP planı (komut başına)
### 2.0 Uzun ömürlü bağlantının evi: canvas host
| Gerçek | Kanıt |
|---|---|
| Daemon istek sonunda havuzdaki WebSocket'leri kapatır; Page/Fetch/Emulation durumu oturuma bağlıdır | `_daemon_request_teardown` (22858), başlık yorumu (22735 civarı) |
| `cdp_send` yalnız `id`'li yanıtı toplar; `Runtime.bindingCalled` ve `Fetch.requestPaused` gibi olayları atar | `cdp_send` (3849), döngü `if "id" in data and data["id"] in pending` |
| Uzun ömürlü, olay güdümlü CDP istemcisi için emsal var | `_BotAuthSigner` (3028: `send`, `run`, `Fetch.enable`, `Target.setAutoAttach`); `bot-auth` daemon'da yasaklı komut |
| Daemon yalnız Unix soketi, Windows'ta kapalı | `socket.AF_UNIX` (23071, 23096); `daemonEnabled()` Windows'ta `false` (`bin/cdpilot.js:96`, `plan-windows-sicak-surec.md` §1) |

Karar: her tuval için **bir host süreci** (`python cdpilot.py --_canvas-host <ad>`; `--_` önekli komutlar daemon'a girmez, `_daemon_spawn_only`).

| Konu | Karar |
|---|---|
| Sahip | Host: sekme WS'si, `Fetch` koruması, binding, olay halka tamponu, çalışma betiği kurulumu |
| İletişim | Unix soketi `$PROFILE_DIR/canvas/<ad>.sock` (0600, dizin 0700, kalıp `_daemon_serve_entry` 23091). Satır tabanlı JSON: `{op:set|patch|events|close|ping, ...}` |
| Kayıt | `$PROFILE_DIR/canvas/<ad>.json`: `{targetId, pid, sock, started, name}` (`_atomic_write_json` 11122) |
| Ömür | Sekme kapanınca (`Target.targetDestroyed`/`Inspector.detached`), `close` ile, 30 dk boşta, SIGTERM'de çıkar; soketi siler |
| CLI | `set/patch/close/events` ince istemcidir: soketle konuşur, CDP açmaz. Bu yüzden daemon altında da güvenle koşar |
| Sıcak/taze | `canvas open` (host doğurur), `canvas stream`, `canvas watch`, `canvas events --follow` taze süreçte: `DAEMON_SPAWN_SUBCMDS`'e `canvas open/stream/watch/events` eklenir (`py` ~22755 ve `bin/cdpilot.js:93`). `watch` adı eski `watch` komutuyla (`py` 23345) karışmaz: `canvas watch` alt komuttur |
| Liste testi | `test.js:129-130` yalnız `DAEMON_SPAWN_CMDS`'i karşılaştırır. **[DV]** `SUBCMDS` karşılaştırması var mı; şerit B aynı testi `SUBCMDS` için ekler |
| Yetim host | `close`, `stop-all`, `project-stop` host'ları öldürür. **[DV]** bu komutların kayıt dizinini nasıl taradığı; şerit B grep'ler, yoksa `canvas close --all` ekler |

### 2.1 `canvas open [--name n] [--allow-net host]`
1. Sekme: `connect` kipinde `_external_create_tab('about:blank')` (3535; yeni pencere, etkin değil; kimlik döner).
   Normal kipte `PUT /json/new?about:blank` + `_mark_owned_tab(id)` (9761). `cmd_new_tab` (10462) kimlik **yazdırır, döndürmez**:
   şerit B iki dalı `_canvas_new_tab()` içinde yeniden kullanır, `cmd_new_tab`'ı değiştirmez.
2. Host doğar (`subprocess.Popen(..., start_new_session=True)`), hazır dosyasını bekler (≤ 5 s).
3. Host: sayfa WS'sine bağlanır → `Page.enable`, `Runtime.enable`, `Runtime.addBinding(__cdpilotCanvasEmit)`,
   `Fetch.enable{patterns:[{urlPattern:"*"}]}`, `Target.setAutoAttach` (§3.2) → `Page.navigate http://cdpilot-canvas.invalid/<ad>/`.
4. `Fetch.requestPaused` (Document, canvas URL'si): `Fetch.fulfillRequest` 200 + `Content-Security-Policy` başlığı + boş iskelet + `CANVAS_RUNTIME_JS` (satır içi betik).
5. Çıkış: `canvas: <ad> <targetId>` bir satır. Günlüğe HTML yazılmaz (§3.5).

### 2.2 `set` ve `patch`
| | `set` | `patch` |
|---|---|---|
| CDP | `Page.setDocumentContent{frameId, html}` (`Page.getFrameTree` ile alınan çerçeve, host önbelleğe alır) | `Runtime.evaluate("__cdpilotCanvas.patch(<json html>,{final})")`; `v` farklıysa önce betiği yükler |
| Belge | Aynı belge ve pencere sürer; betikler yeniden çalışır [ÖLÇÜLDÜ] | Aynı belge; yalnız fark uygulanır |
| Enjekte çalışma betiği | Pencere kalıcı → betik kalır; her `set` önce zamanlayıcıları temizler | Kalır |
| CSP | Başlık belgeyle kalır: `setDocumentContent` ve `document.write` sonrası `window.open` hâlâ `null`, depolama hâlâ `SecurityError` [ÖLÇÜLDÜ] | Aynı |
| Geçmiş | Girdi eklemez: `history.length` değişmedi (2: `about:blank` + tuval) [ÖLÇÜLDÜ] | Eklemez |
| Süre | **[ÖLÇÜLDÜ]** 20 KB: gönderimden çift rAF'a medyan 114 ms (n=10, min 10, maks 264); `Runtime.evaluate` ile `innerHTML` medyan 66 ms (n=10, min 9, maks 123). Yük: 342 (`uptime`). Tek koşu, ön ölçüm; kapı §4'te |
- Belge kaybı (çöktü, gezindi): host `location.href` ve `window.__cdpilotCanvas.v`'yi `set/patch` öncesi kontrol eder;
  tutmuyorsa canvas URL'sine yeniden gider (başlık yeniden uygulanır) ve sonra işi yapar.
- Boyut sınırı: HTML ≤ 1 MB (CLI), ≤ 256 KB (MCP). Aşan istek hata (çıkış 2).

### 2.3 `close`
Host `Page.close` yollar (`cmd_close_tab` aynı CDP çağrısını kullanır; `connect` kipinde son sekmeyi kapatmama kuralı orada). Kayıt/soket silinir; host çıkar.

### 2.4 `stream` (taze süreç, tek uzun istek)
- Okuma: `stdin`'den `os.read(0, 4096)`; asyncio `connect_read_pipe`.
- Tetik: (a) son bayttan **50 ms sessizlik**; (b) tampon kapanış etiketiyle bitti (`</…>`) ve son yamadan ≥ 16 ms; (c) EOF → `final:true`.
- Kesme: içerik son tam `>` karakterine kadar kesilir; açık `<script>`/`<style>` kapanana dek yamaya girmez. Betikler yalnız `final:true` yamada çalışır.
- Her yama **birikmiş tüm belgedir**; uçuştaki yama varsa en yeni durum kazanır (birleştirme).
- Zaman: `t_son_bayt = time.time_ns()` son okumada alınır, host'a `t_cli` olarak gider.
Sınır: toplam 1 MB; aşılırsa `stream` hatayla biter, son durum tuvalde kalır.

### 2.5 `watch <dosya>` ve `events`
- `watch` (taze süreç): 100 ms'de bir `os.stat` (`st_mtime_ns`, `st_size`); değişince 30 ms sönümle dosyayı okur, `patch` yollar; Ctrl+C temiz çıkar.
- `events`: host halka tamponu (1.000 olay, 64 KB toplam; taşarsa en eskisi düşer, `dropped` sayacı artar).
  Kaynak: `Runtime.bindingCalled`. Yük 1 KB'a kesilir; olay hızı ≤ 100/s. **[ÖLÇÜLDÜ]** `bindingCalled` sandbox'lı belgede çalışıyor.
  Şema: `{seq, t, type, action, id, data}`; `type`: `click|submit|input|blocked|paint`.
- Yalnız `data-action`/`data-emit` öğeleri ve form olayları taşınır (PRD §5). `blocked` olayları (§3) host üretir ve sızıntı testinin kanıtıdır.
- CLI `events --follow`: `after` imleciyle döngü; `--after N --max N --wait-ms N` tek seferlik yoklama.
- MCP `browser_canvas_events{after, max≤100, wait_ms≤25000}` → `{events, next, dropped}`. `TOOL_TIMEOUT_S = 30` (`py` 18719) altında kalır. İzleme (push) yok.

## 3. Güvenlik uygulaması
### 3.1 CSP teslimi: neden meta yetmez
| Deneme (`about:blank` + meta CSP, Chrome 152) | Sonuç [ÖLÇÜLDÜ] |
|---|---|
| `fetch(no-cors)` → `connect-src` | engellendi (ihlal olayı `connect-src`; CSP'siz kontrolde `REACHED`) |
| `window.open("http://127.0.0.1:9333/json/version")` | **açıldı ve gezindi (sızıntı)**; meta `sandbox` desteklemez |
| `location.href = dış URL` | gezindi (CSP'de `navigate-to` yok) |
| Meta CSP `setDocumentContent`/`document.write` sonrası | kalıcı: sonraki yazımlarda `fetch` engelli kalıyor |
Başlık yolu (K2): `Fetch` ile servis edilen belge, `sandbox allow-scripts` + CSP başlığıyla [ÖLÇÜLDÜ]:
`window.open` → `null`; depolama → `SecurityError`; `fetch` ve WebSocket engelli; `form.submit()` gezinmedi.
`data:`/`blob:` kökeni **gerekmez**: başlıklı sanal kök, opak köken (`sandbox`) verir; `data:` URL başlık taşıyamaz ve 2 MB sınırlıdır.

Başlık metni (taban; `--allow-net h` yalnız `connect-src h`; `--allow-img` `img-src … https:` ekler):
`default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; img-src data: blob:; form-action 'none'; base-uri 'none'; frame-src 'none'; sandbox allow-scripts`

### 3.2 Gezinme ve `window.open` engeli — seçim
| Seçenek | Sonuç | Karar |
|---|---|---|
| `Page.frameRequestedNavigation` | Yalnız bildirim; istek zaten çıkar. `reason: scriptInitiated` görülür [ÖLÇÜLDÜ] | yalnız `blocked` olayı için |
| `Fetch.requestPaused` + `failRequest` | Gezinme durur ama belge `chrome-error://` olur: **tuval ölür** [ÖLÇÜLDÜ] | hayır |
| `Fetch.requestPaused` + `fulfillRequest` **204** | Belge yerinde kalır (`#x` metni duruyor) [ÖLÇÜLDÜ] | **evet** |
| `Target.setAutoAttach` (`waitForDebuggerOnStart`) | Açılan pencereyi kapatmak için; `sandbox` zaten `window.open`'ı `null` yapar | yalnız ikinci savunma: açılan hedef `Target.closeTarget` |
| Sayfa içi Navigation API | Denemem anlamsız çıktı (belge gezindi, `__nav` yok) | **[DV]** kullanılmaz |
Kural: canvas URL'si dışındaki her `Fetch.requestPaused` → 204 + `blocked{url (kesik), resourceType}` olayı. Alt kaynak yok (CSP);
varsa zaten `failRequest(BlockedByClient)`. Host düşerse başlık korur (sandbox/CSP), **yalnız `location=` gezinmesi açılır**:
bu yüzden host ölünce sekme `Page.close` ile kapatılır (yetim host yok, yetim açık tuval de yok). **[DV]** host'un `SIGKILL`'de sekmeyi kapatması: yedek olarak sekme `Inspector`/oturum kaybında `about:blank`'a döner mi denenecek.

### 3.3 CSP'nin her `set/patch`te yeniden uygulanması (jüri koşulu)
1. `set`: HTML'in başına aynı CSP'yi `<meta http-equiv>` olarak ekler (ikinci katman; başlık sandbox'ı taşır, meta taşımaz).
2. `patch`: morph, gelen HTML'deki CSP/refresh meta'sını ve `<base>`'i atar; başta CSP meta'sı yoksa ekler.
3. Her işten önce host belgeyi doğrular (§2.2); başlık kaybolmuşsa yeniden navigasyonla geri gelir.
4. `canvas open --allow-net` bayrağı host'ta durur; HTML içinden gevşetme yolu yoktur (meta yalnız daraltabilir).

### 3.4 Sızıntı fixture'ı ve kanıt
`test/fixtures/canvas/exfil.html` sayfa yüklenince 8 deneme yapar; her deneme `try/catch` içinde sonucu `window.__r[ad]`'a yazar.
Sunucu: `127.0.0.1` üstünde geçici dinleyici (3001+; 3000/9222 yasak) gelen isteği sayar. Kanıt iki yönlüdür:
(1) sayfa tarafı sonuç (`blocked`/`null`/`SecurityError`), (2) **dinleyici sayacı = 0** ve host `blocked` olayları.

| Deneme | Beklenen engel | Kanıt |
|---|---|---|
| `fetch(url,{mode:'no-cors'})` | CSP `connect-src` | reddedildi; sayaç 0 |
| `new Image().src = url` (işaretçi) | CSP `img-src` | `onerror`; sayaç 0 |
| `location.href = url` | Fetch 204 | belge sürer; `blocked` olayı; sayaç 0 |
| `form.submit()` | `form-action 'none'` + sandbox | gezinme yok; sayaç 0 |
| `new WebSocket(ws://…)` | `connect-src` | `error`; sayaç 0 |
| `window.open(url)` | `sandbox` (popup yok) | dönüş `null`; `/json/list` yeni hedef yok |
| `<meta refresh>` ve `<a target=_blank>` tıklaması | Fetch 204 / sandbox | belge sürer; sayaç 0 |
| `<iframe src>` / `<link rel=prefetch>` | `frame-src`, `default-src` | sayaç 0 |
Karşı deney (testin geçerliliği): fixture CSP'siz `about:blank`'ta açılır → en az `window.open` ve `location` sayaçları > 0 olmalı
(ölçülen: meta tek başına `window.open`'ı geçirdi). Karşı deney geçmezse test hükümsüz sayılır.
Taze Chrome sürümünde (CI) aynı fixture koşar; `Fetch`/`sandbox` davranışı sürüme bağlıdır → sürüm `blocked` raporuna yazılır.

### 3.5 Günlük ve olay güvenliği
- `_slog_redact_args` (21194): `canvas` için `set|patch` argümanları `«html:N chars»`; `--html` değeri aynı. `stdin` HTML günlüğe girmez (PRD §5).
- `data-action` adı `[a-z0-9_-]{1,64}` dışıysa olay atılır.
- Soket 0600; host başka UID'den bağlantıyı reddeder (`SO_PEERCRED`/`getpeereid`). **[DV]** macOS'ta `LOCAL_PEERCRED` kullanımı; yoksa dizin izni (0700) yeterli sayılır.

## 4. Ölçüm
### 4.1 Zaman damgaları
| Nokta | Nasıl |
|---|---|
| T0 son token girdi | CLI: `time.time_ns()` EOF okunurken (`stream`) ya da `set/patch` isteği yazılmadan önce; soket mesajında `t_cli` |
| T1 host aldı | host `time.time_ns()` |
| T2 CDP gönderildi | host, `Runtime.evaluate`/`setDocumentContent` yazmadan önce |
| T3 ilk boyama | sayfada yamadan sonra `rAF(()=>rAF(()=>emit({type:'paint', id, t: performance.timeOrigin+performance.now()})))` |
| Sonuç | `T3 − T0` (epoch ms; aynı makine, aynı duvar saati) |
Çift rAF: ilk rAF kareden önce, ikincisi ilk karenin işlenmesinden sonra çalışır; boyama sınırının makul üst tahminidir.
**[ÖLÇÜLDÜ]** düzenek çalışıyor (binding + çift rAF, §2.2 sayıları). Sapma bilinmiyor: **kalibrasyon** koşusu (n=20, kapı dışı)
`Page.startScreencast` karesinin `metadata.timestamp` değerini çift rAF ile karşılaştırır ve farkı belgeler.
Gizli/örtülü sekmede rAF durur → `Emulation.setFocusEmulationEnabled{enabled:true}` + `Page.bringToFront` açılışta; **[DV]** `connect` kipinin
arka plan penceresinde (`_external_create_tab` yorumu: gizli sayfa) rAF hızı. Kapı başsız Chrome'da koşar.

### 4.2 Koşu düzeni
| Madde | Karar |
|---|---|
| Harness | `test/canvas_bench.py` (şerit C); gerçek host + gerçek CLI istemcisi; `python3.13 -I` |
| Yük | 20 KB belge, 1.000 yama bellek turu ayrı |
| Tur | n=50 çift: `patch` (morph) ve `set` **ardışık dönüşümlü** (A/B), arada 150 ms; boşta ve yük altında (başka süreçle CPU doldurma yok: yük zaten makinede; `uptime` önce/sonra yazılır) |
| Çıktı | `.claude/docs/olcum/canvas-<tarih>.json`: ham ms dizisi, p50, p95, `uptime` yükü, Chrome sürümü |
| Kapı | **boyama** (model süresi hariç, belgede yazılı): p50 ≤ 100, p95 ≤ 200 ms (jüri S3); `set` 20 KB ≤ 50 ms (PRD §4) boyama kapısı değil, rapor |
| Yük kuralı | `uptime` 1 dk yükü > 4×çekirdek ise koşu `yük-geçersiz` işaretlenir ve en çok 3 kez yinelenir; 3'ünde de geçersizse kapı **geçmedi** sayılır (sessiz geçme yok). Yerel sayılar bilgidir; kapı temiz CI makinesinde |
| Ağır komut | tüm koşular `bash /Users/nadir/01dev/conductor/perf-1910/agir.sh <komut>` ile |
**[DV]** Bugünkü ön ölçüm (medyan 114 ms, yük 342) p50 ≤ 100 kapısını bu makinede geçmez; temiz makinede bekleneni bilmiyoruz.

## 5. Şeritler
Çakışmayı önlemek için lider, şeritlerden önce `src/cdpilot.py`'a boş **bölge işaretleri** koyar:
`# ═══ CANVAS-A BEGIN/END ═══`, `…-B…`, `…-C…`, `…-D…` ve `main()` içinde `'canvas'` yönlendirmesi (şerit B'nin bölgesi). Şerit yalnız kendi bölgesine yazar.

| Şerit | Dosya / bölge | İş | Kabul testi | Sıra |
|---|---|---|---|---|
| **A** morph + çalışma betiği | `py` bölge A (`CANVAS_RUNTIME_JS`); `test/canvas_fake_dom.js`, `test/canvas_morph.js`, `test/canvas_e2e.js`, `test/fixtures/canvas/state.html` | §1 hepsi; sözleşme dondurma (gün 0: imza + `ops` şeması) | sahte DOM testleri (`CDPILOT_TEST_ONLY='canvas morph'`); e2e: odak/selection/kaydırma/details/dialog korunur; bozuk HTML hata vermez; 1.000 yama bellek ≤ 2× | ilk; B ve C sözleşmeyi gün 0'da alır |
| **B** host + CLI + güvenlik | `py` bölge B (host, `open/set/patch/close`, `_canvas_new_tab`, DAEMON_SPAWN_SUBCMDS satırı, `_slog_redact_args` dalı); `bin/cdpilot.js:93` satırı; `test/canvas_fake_cdp.py`, `test/fixtures/canvas/exfil.html` | §2.0–2.3, §3 hepsi | sahte-CDP: CDP yöntem sırası (`Fetch.enable` → `navigate` → `fulfillRequest` başlığı tam metin), canvas dışı belge 204, `set` → `setDocumentContent`, belge kaybında yeniden navigasyon; liste testi; slog `«html:N chars»`; e2e sızıntı fixture'ı + karşı deney | A'nın sözleşmesi (stub ile başlar); C ve D, B'nin `patch/events` soket işlemini bekler |
| **C** stream/watch + ölçüm | `py` bölge C (`stream`, `watch`); `test/canvas_bench.py`; `.claude/docs/olcum/canvas-*.json` | §2.4, §2.5 (watch), §4 | `stream` birim testi (sahte soket: 50 ms sessizlik, kapanış etiketi, yarım `<script>` tutulur, EOF `final`); bench kapısı; yük kaydı | B'nin `patch` işlemi |
| **D** events + MCP + örnek | `py` bölge D (`events`, MCP `browser_canvas_set/patch/events`, `WEBMCP_TOOLS` benzeri `CANVAS_TOOLS`, `browser_*` argv eşlemesi, `CORE_TOOLS` dışında); `examples/canvas/`; `test/canvas_events_fake.py` | §2.5, MCP: şema token maliyeti ölçümü | imleç: `after/max/dropped`, olay 1 KB kesme, hız sınırı; MCP: üç araç `tools/list`'te, `core`'da yok, HTML 256 KB sınırı, slog redaksiyonu; 3 aracın şema token sayısı değişiklik notuna (PRD §8 S4) | B'nin `events` işlemi + A'nın `emit` sözleşmesi |

Sıra: **gün 0** lider bölge işaretlerini ve sözleşmeyi koyar → **A ‖ B** paralel → **C ‖ D** (B'nin soket işlemleri hazır olunca) → güvenlik incelemesi (B + D çıktısı; PRD §7).
Her şerit kendi testini yazmadan "bitti" demez; hedefli koşu: `CDPILOT_TEST_ONLY='canvas' node test/test.js`; tam paket `agir.sh` ile.
Ortak dosya `test/test.js`: her şerit yalnız kendi `describe`-benzeri bloğunu ekler (başlık öneki `canvas morph:`, `canvas host:`, `canvas stream:`, `canvas events:`).

## 6. Riskler ve açık noktalar
| # | Risk / açık nokta | Etki | Ne yapılır |
|---|---|---|---|
| R1 | Host = yeni süreç ömrü. Yetim host/sekme, `stop-all` ve `project-stop` kapsamı **[DV]** | kaynak sızıntısı | Boşta çıkış 30 dk; `close --all`; testte yetim denetimi |
| R2 | Boyama kapısı bu makinede (yük ~340) geçmeyebilir; ön ölçüm medyan 114 ms | kapı kırmızı | Kapı temiz CI'da; yük kuralı §4.2; yerel yalnız bilgi |
| R3 | `connect` kipinde sekme arka plan penceresinde; rAF durabilir **[DV]** | ölçüm geçersiz | `setFocusEmulationEnabled`; başsız kapı |
| R4 | Host düşerse `location=` gezinmesi açılır (başlık kalır) | sızıntı penceresi | Sekmeyi host ölümünde kapat; `SIGKILL` yolu **[DV]** |
| R5 | Morph ana dünyada; sayfa prototipleri bozabilir | yama bozulur | kabul (kendi tuvali); çekirdek dondurulmuş yardımcılar |
| R6 | `set` aynı pencerede betikleri yeniden çalıştırır; eski zamanlayıcı/dinleyici kalır | sürpriz davranış | zamanlayıcı sarmalayıcısı temizler; dinleyici temizliği yok → belge: "tam sıfırlama = `close` + `open`" |
| R7 | Windows'ta daemon da host da yok | özellik yok | `canvas` Windows'ta "desteklenmiyor" ile çıkış 1; güvenliksiz yedek yol **yok** |
| R8 | `Fetch` + `sandbox` davranışı Chrome sürümüne bağlı (yalnız 152'de denendi) | CI farkı | e2e sürümü raporlar; karşı deney testin geçerliliğini korur |
| R9 | MCP argümanı büyük HTML: argv sınırı ve günlük | hata/sızıntı | 256 KB sınırı, `--html` redaksiyonu; `subprocess.run` `input` yok (`py` 19044) |
| R10 | `unsafe-eval` + satır içi betik (PRD §5 kararı); sahte DOM tarayıcıdan ayrışabilir; Navigation API koruması denenemedi **[DV]** | kabul / yanlış güven | CSP ağı ve gezinmeyi keser; e2e gerçeği belirler; Navigation API v0'a girmez |

Doğrulanamayanlar: R1 (`stop-all` taraması), R3, R4 (SIGKILL), `SUBCMDS` liste testi, `LOCAL_PEERCRED`, Navigation API, rAF–ekran karesi sapması, temiz makinede p50/p95. Windows'ta hiçbir şey denenmedi.

## 7. Jüri kararı (10.11.2026 23:2x, D-tuval-v0; J1 Opus 5.5 · J2 Sonnet 5.5 · J3 gpt-oss-120b)
Plan yönü 3/3 kabul; RET yok. K1, K6, K7, K10 3/3 KABUL. Koşullar (J1 ve J2 birleşimi) şeritlerin kabul ölçütüne girer:

| Karar | Koşul (bağlayıcı) |
|---|---|
| K2 | Host yalnız tam `http://cdpilot-canvas.invalid/<kendi-adı>/` adresini doldurur; başka ad/yol/sorgu → 204. Sızıntı fixture'ına ek vektörler, her biri loopback dinleyici sayacıyla: `RTCPeerConnection` STUN/TURN (IP ve ad), `<link rel=dns-prefetch/preconnect>`, `<a ping>`, `blob:`/`data:`/`about:blank` üst düzey gezinme |
| K3 | Soket protokolü kapalı liste: `set|patch|events|close|ping`; eval, ham CDP geçişi, CSP/`--allow-net` değiştirme yok (`--allow-net` host açılışında sabit). Ad `[a-z0-9_-]{1,32}`. Boyut sınırları host içinde de. Dizin 0700, soket 0600 |
| K4 | HTML `Runtime.evaluate`'e yalnız `json.dumps` ile girer. "Belge kayıp mı" denetimi tarayıcı gerçeğinden: `Page.getFrameTree` URL'si + `Page.frameNavigated` izi; sayfanın yazabildiği `window` alanlarına güvenilmez |
| K5 | Binding olayları güvenilmez: sayfa yalnız `click|submit|input` diyebilir; `blocked` ve host'a özgü türler binding'den gelirse düşer. Host olayları `src:'host'`; sızıntı testi yalnız `src:'host'` sayar |
| K8 | Kapalı başarısızlık: `Fetch.requestPaused` işleyicisinde her hata → gezinmeye 204, alt kaynağa `failRequest(BlockedByClient)`; asla `continueRequest`. `Fetch.enable` yalnız tuvalin kendi oturumunda, `requestStage:'Request'`; `_BotAuthSigner` kalıbı (tarayıcı düzeyi `setAutoAttach`, her sekmede Fetch) YASAK — kullanıcı sekmelerini 204'lerdi |
| K9 | Genişletilmiş sızıntı e2e'si (karşı deney dahil) ve C1 SIGKILL e2e'si şerit B'nin birleşme kapısıdır; şerit D bunlar yeşil olmadan birleşmez. Güvenlik incelemesi A (meta/refresh/base ayıklama, emit) ve C'yi (stream) de kapsar; uçtan uca `canvas stream` ve `canvas patch` üzerinden koşar |
| C1 | Host'tan bağımsız koruma şart: tercih `Target.createBrowserContext{disposeOnDetach:true}` (SIGKILL'de tarayıcı bağlamı ve sekmeyi atar; kullanıcı çerezlerinden de ayırır); olmazsa ayrı oturumda bekçi süreç. Ölçülmeden `canvas open` koşmaz |
| C2 | Tuval MCP araçları `CORE_TOOLS` dışında. MCP katmanı HTML'i alt sürece argv ile değil stdin ya da 0600 geçici dosyayla verir (argv'yi her yerel kullanıcı `ps` ile okur) |

Eksik ölçümler (kod şeritlerinden önce, ölçüm şeridi): WebRTC STUN/TURN ve preconnect/ping sızıntısı (Chrome 152, başlık CSP + sandbox) ·
`blob:`/`data:`/`about:blank` üst düzey gezinmede CSP/sandbox mirası · host SIGKILL/SIGSTOP sonrası sekme durumu ve `location=` ·
`createBrowserContext{disposeOnDetach:true}` connect kipinde ve CI Chrome'da · tek sekme oturumunda `Fetch.enable{*}` öteki sekmelere dokunuyor mu.
Başlama tetiği değişmedi (K10): çift kip CI yeşil (K-0027).
