# İnsan hızı — kalıcı süreç (daemon) ve sıcak oturum

Durum: UYGULANDI v1 (opt-in `CDPILOT_DAEMON=1`), 08.11.2026. Ölçüm tabanı: `perf-taban-2026-11-08.md`.
Nadir'in sorusu (08.11): "sekmeyi açıp ilk boyamayı yapman, siteye girmemle aynı hız olabilir mi?"

## 0. Özet

Tarayıcı sayfayı 16–20 ms'de boyuyor. cdpilot `go` uçtan uca ~1 s idi. A adımı (bytecode önbelleği, 01f47fc) tarayıcısız
komutu 500 → 270 ms'ye indirdi. Kalan maliyet ve kalıcı sürecin etkisi:

| Parça | Taze süreç (ms) | Kalıcı süreçle |
|---|---|---|
| node açılışı (`node -e 0`) | ~110 | kalır (ince istemci yine node) |
| Python yorumlayıcı + import zinciri | ~140 | 0 (bir kez) |
| CDP oturumu: `/json`, WS, hedef, stealth betiği, bekleme | ~500 | ~0 (sıcak WS havuzu `_WS_POOL`) |
| komutun kendisi (`go`: navigasyon + yükleme) | 20–50 | aynı |

Hedef: yerel sayfada `go` ≤ 150 ms uçtan uca; tarayıcısız komut ≤ 150 ms (node tabanı 110). Kapı: taban tablosuna karşı
5 tekrar, p50. Ölçüm sonucu §5.

## 1. Tasarım: "tek yürütücü, istek = eski süreç"

```
node bin/cdpilot.js go <url>
  │ CDPILOT_DAEMON=1 ∧ komut sayfa komutu ∧ --timeout yok
  ├─ anahtar = sha1(python, sürüm, src, HOME, CDPILOT_*, CDP_*, CHROME_BIN)[:16]
  ├─ soket = $CDPILOT_HOME/daemon/<anahtar>.sock  (yol >100 bayt ise $TMPDIR/cdpilot-<uid>-daemon/)
  ├─ bağlan → 150 ms içinde {"hello", version} gelmezse ya da sürüm farklıysa → taze süreç (+ daemon başlat)
  ├─ {"argv", "cwd", "stdin"?} gönder
  └─ {"o"} / {"e"} çerçevelerini akıt → {"exit": N} → çıkış kodu
python src/cdpilot.py --_daemon-serve <soket>
  │ bir kez import; tek asyncio döngüsü; `asyncio.run` = o döngüde `run_until_complete` (havuz sıcak kalır)
  └─ istek başına: sys.argv / stdin / stdout / stderr / cwd takası · modül durumu sıfırlama · SystemExit → kod ·
     `atexit.register` çağrıları istek sonunda koşar (oturum günlüğü, kayıt adımı, boşta damgası)
```

Kararlar ve gerekçeleri:

- **Anahtar = import anında okunan her şey.** `src/cdpilot.py` 10 ortam değişkenini modül düzeyinde okur (`CDPILOT_HOME`
  133, `IS_MCP_SESSION` 137, `CDP_PORT/PROFILE_DIR/PROJECT_ID` 505, `CHROME_BIN` 507, …). Ortamı istek başına takas etmek
  yerine farklı ortam = farklı daemon: istek hiçbir zaman başka proje/port/tarayıcı için kurulmuş sürece düşmez.
  `bin/cdpilot.js` `CDPILOT_PROJECT_ID`'yi cwd'den türetip ortama koyduğu için proje kimliği cwd'den bağımsız kalır.
- **Sıralı yürütücü.** Tek iş parçacığı, tek istek. Meşgulken ikinci istemci hello alamaz, 150 ms'de taze sürece düşer;
  paralel kullanıcı bugünkü hızı görür, bir komut asla iki kez koşmaz (düşüş yalnız istek gönderilmeden önce).
- **`asyncio.run` kalkanı.** Dağıtıcı `asyncio.run(_wrapped())` çağırır; daemon bunu kalıcı döngüde bir görev olarak
  `run_until_complete` yapar (görev kopan istemcinin iptal edebilmesi için). **İnceleme sonrası (08.11 17:00):** havuz
  istekler arası YAŞAMAZ — `_daemon_request_teardown` istek sonunda havuzdaki WS'leri kapatır ve kalan görevleri iptal
  eder (asyncio.run gibi). Sebep: `Emulation.*`, `Network.enable`, `Page.enable`, `addScriptToEvaluateOnNewDocument`
  (glow/stealth) oturuma bağlıdır; taze süreçte çıkışla silinir, sıcak havuzda sonraki komuta taşınırdı. "Sıcak oturum"
  (D) ancak bu oturum-bağlı durumun envanteri ve yönetimiyle gelir; ölçüm: havuz kapatmanın bedeli ~10 ms/komut.
- **İstek sonu = eski süreç sonu.** `_slog_begin` (günlük + kayıt adımı), `_idle_touch_activity` ve zaman aşımı
  `atexit.register` kullanır; daemon kaydı istek listesine alır, sonunda LIFO koşar.
- **İstek ortamı.** İstemci `process.env`'i isteğe koyar; daemon istek süresince `os.environ`'ı onunla değiştirir, sonra
  geri yükler (`CDPILOT_MODE` yazımı, proxy/çözücü anahtarları, PATH, TZ istek anında okunur). Çalışma dizini de geri
  yüklenir. `umask` yalnız soket/bilgi dosyası yazılırken 077; komutların yazdığı dosyalar çağıranın kipinde.
- **Bayat yapılandırma.** `CDP_PORT/PROFILE_DIR/PROJECT_ID` import anında çözülür; her istekte `_resolve_project_config()`
  yeniden çözülür, farklıysa `{"fallback":"stale"}` ve daemon çıkar (istemci taze koşar, yenisini başlatır). Elle
  port+profil verilip proje kimliği cwd'den türeyen kurulumda cwd değişimi daemon'u yeniler — kabul edilen bedel.
- **Kopan istemci.** İstek başına bir izleyici iş parçacığı istemci soketini okur; istemci kapanınca koşan asyncio görevi
  iptal edilir ya da sonraki async adım reddedilir (çıkış 130). `interrupt_main` bilerek kullanılmaz (temizlik ortasında
  KeyboardInterrupt). Gönderimler 10 sn zaman aşımlı: durdurulmuş istemci daemon'u asmaz.
- **Sıfırlanan modül durumu** (`_daemon_reset_state`): `_FRAME_FLAG`, `DIALOG_MODE`, `INTERCEPT_RULES`, `_A11Y_REF_MAP`,
  `_SLOG`, `_AUTOLAUNCH`, `_CLICK_MISSES` (exit 3 sızmasın), `_PRESS_MS_WARNED`, `_SHADOW_NOTES_PRINTED`, `_IDLE_WARNED`.
  Kalanlar bilerek kalır: `_CDP_GET_CACHE` (0,5 s TTL), `_glow_script_id` (oturuma bağlı), `_WS_POOL/_WS_LOCKS`.
  `os.environ` istek öncesi kopyalanır, sonra geri yüklenir (`cmd_go` uyarlanabilir kipte `CDPILOT_MODE` yazar). Yürütücü
  testi (`daemon: the request executor…`) env/akış/sys kancası geri yükleme, çıkış kodları, stdin ve redleri süreç içinde denetler.
- **Taze sürece kalanlar** (`DAEMON_SPAWN_CMDS`, iki tarafta aynı liste, test eşitliği denetler): `launch stop stop-all
  project-stop connect disconnect serve mcp watch setup status daemon replay run agent blog bot-auth browser test trace
  heal health session sessions session-close projects proxy extensions tls-proxy help`. `--timeout`/`CDPILOT_TIMEOUT`:
  bekçi `os._exit` ile süreci bitirir (19933) → taze süreç. stdin okuyan `batch` (her zaman) ve `check` (argümansız):
  istemci stdin'i istekle gönderir, daemon `io.StringIO` verir.
- **Çıkış kodu.** `SystemExit` yakalanır (`sys.exit("mesaj")` → stderr + 1); yakalanmamış istisna → excepthook (günlük
  kaydı + izleme) → 1; KeyboardInterrupt → 130. İstemci Ctrl+C: v1'de komut daemon'da sonuna kadar koşar (çıktı düşer).
- **Yaşam.** İstemci ilk çağrıda daemon'u ayrık (`detached`, 5 sn'de en çok 1 deneme) başlatır, o çağrı taze koşar.
  Boşta `CDPILOT_DAEMON_IDLE` sn (varsayılan 1800) sonra kendi kapanır; `cdpilot daemon start|stop|status`.
  Sürüm el sıkışması: eski kurulumun daemon'una `shutdown` gönderilir, çağrı taze koşar, yenisi başlar.
- **Güvenlik.** Yalnız AF_UNIX (Windows şimdilik hep taze süreç); soket 0600, dizin 0700; dizin ya da soket başkasının
  ya da grup/diğer izinliyse İKİ taraf da reddeder (istemci `lstat` ile bağlanmadan önce; daemon bind'den önce). Uzun
  `CDPILOT_HOME` için yedek dizin `$XDG_RUNTIME_DIR/cdpilot-daemon`, yoksa `$TMPDIR/cdpilot-<uid>-daemon`. Başlatma
  damgası `O_EXCL` ile açılır (sembolik bağ izlenmez, ikinci başlatıcı yok). İstek tek satır JSON, 8 MB üst sınır;
  bozuk istek `{"fallback":"request"}`. `daemon stop` yalnız kimsenin dinlemediği soketi siler (meşgul daemon'a
  dokunmaz). T2 güvenlik denetimi bu yüzey için sırada (§6).

## 2. Ölçüm — tarayıcısız komut (08.11 16:00, M1 Max, yük ~10)

| Komut | Taze (A sonrası) | Sıcak (daemon) |
|---|---|---|
| `version` | 265–280 ms | 138 ms |
| `record status` | 265–280 ms | 149 ms |
| Python tarafı (soketten sokete) | — | 0–3 ms |

Kalan ~140 ms'nin ~110'u node açılışı: ince istemci de node. Daha aşağısı node'suz bir kabuk/ikili istemci ister (ayrı iş).

## 3. Riskler ve inceleme (08.11 17:00, Claude reviewer: 9 bulgu → hepsi işlendi)

| # | Bulgu | Karar |
|---|---|---|
| 1 | Import anında çözülen port/profil/proje bayatlar (`connect`/`launch` registry'yi değiştirir) | her istekte yeniden çözüm, farklıysa `stale` + çıkış |
| 2 | Havuz WS'i oturum-bağlı durumu (Emulation, Network.enable, glow betiği) sonraki isteğe taşır | havuz istek sonunda kapanır; `_glow_script_id` sıfırlanır |
| 3 | `os.environ` anlık görüntüsü yetmez; umask 077 komut dosyalarına bulaşır; `_CDP_GET_CACHE` bayat | istek ortamı istemciden; umask yalnız bind'de; önbellek temizlenir |
| 4 | Kopan istemci: komut sürer, yeni çağrı taze süreçte aynı sayfaya dokunur; sendall sonsuz bloklanabilir; `daemon stop` meşgulü siler | izleyici iş parçacığı + görev iptali; gönderim 10 sn; stop yalnız ölü soketi siler |
| 5 | Paylaşılan /tmp yedek dizini: istemci sahiplik denetlemez, damga sembolik bağı izler | istemci lstat (uid + kip + S_IFSOCK); XDG_RUNTIME_DIR; damga O_EXCL |
| 6 | Bozuk/çok büyük istek "bağlantı kayboldu" exit 1 olur; O(n²) tampon taraması | `{"fallback":"request"}`; `scanFrom` |
| 7 | Bekleyen görevler sonraki isteğe sarkar | istek sonunda `all_tasks` iptal + gather |
| 8 | `captcha-wait` terminalde Enter bekler, daemon'da stdin StringIO | `captcha-wait` taze sürece |
| 9 | Settle: yükleme sonrası 300 ms penceresindeki konsol olayları artık toplanıyor (önce düşüyordu); SPA'da 100 ms sonra çizilen içerik eksik kalabilir | CHANGELOG'a yazıldı; SPA kümesinde ölçüm D2 kapısı |

Açık kalanlar: `launch`'ın başlattığı tarayıcı daemon'un çocuğu olur (ayrık; doğrulanacak); Windows yok; istemci Ctrl+C
komutu iptal eder ama tarayıcıda yarım kalmış navigasyon kalabilir (taze süreçte de böyleydi).

## 4. Sürüm planı

| Adım | Ne | Kapı |
|---|---|---|
| v1 (bu) | opt-in `CDPILOT_DAEMON=1`, POSIX | 9 tarayıcısız test + tam paket; sıcak `go` ölçümü (§5) |
| v2 | 2 hafta ölçüm sonrası varsayılan açık; `CDPILOT_DAEMON=0` kapatır | ajan oturumlarında hata oranı taze ile aynı |
| v3 | Windows (127.0.0.1 + jeton dosyası), Ctrl+C iletimi | — |
| canlı tuval | `cdpilot canvas`: sıcak oturumda `Page.setDocumentContent` + DOM yaması, son token → ilk boyama ≤ 100 ms | ayrı plan |

## 5. Ölçüm — tarayıcılı komutlar (08.11 16:10, ortak başsız Chrome 152 `connect 9333`, yük ortalaması 20–34!)

Makine o anda ağır yüklüydü (taban ölçümünde yük ~10); mutlak sayılar şişkin, oranlar geçerli. 3 (taze) / 5 (sıcak) tekrar, ms.

| Komut | Taze | Sıcak (daemon) | Hedef |
|---|---|---|---|
| `status` (node tarafı, daemon'a gitmez) | 91–104 | — | — |
| `content` | 357–373 | 105–120 | ≤150 ✅ |
| `eval 1+1` | 369–383 | 112–137 | ≤150 ✅ |
| `go file://paint.html` | 714–1053 | 426–515 | ≤150 ❌ |
| `go https://example.com` | — | 523–600 (ilk 1528: DNS/ağ) | — |
| ilk çağrı (taze + daemon başlat) | — | 317 | — |

`content`/`eval` hedefi tutturdu: kalan ~110 ms node açılışıdır. `go` tutturamadı; sebebi daemon değil, `cmd_go`'nun kendisi:

- `navigate_collect` (5616) havuzu KULLANMAZ: her çağrıda kendi `websockets.connect` oturumunu açar, 4 alanı etkinleştirir
  (`Page/Network/Runtime/Log`), stealth betiğini ve UA geçersiz kılmayı o oturuma kaydeder, `Page.navigate` gönderir,
  `Page.loadEventFired`'a kadar olay okur, sonra oturumu kapatır. Bu yüzden stealth "go oturumuna bağlı" (CLAUDE.md
  bilinen sınır) ve her `go` oturum kurulumunu yeniden öder.
- Yüklemeden sonra 3 ayrı `Runtime.evaluate` turu: `_assert_host`, `_detect_friction`, `_detect_captcha` (iz: `CDPILOT_CDP_TRACE`).
- Komut sonrası `_update_session_timestamp`, `_enforce_tab_budget`, `_mark_owned_tab` dosya/`/json` işleri.

### 5.1 Settle düzeltmesi sonrası (08.11 16:35, yük ~17)

`navigate_collect` yükleme olayından sonra sabit `asyncio.sleep(0.3)` bekliyordu; şimdi olay okumaya devam eder, 100 ms olay
gelmeyince durur, tavan 300 ms (eski davranışın üst sınırı korunur).

| Komut | Taze | Sıcak (daemon) | Önceki sıcak |
|---|---|---|---|
| `go file://paint.html` | 502–826 | 227–298 | 426–515 |
| `go https://example.com` | — | 217–322 | 523–600 |
| `content` | 348–376 | 105–126 | 105–120 |
| `eval 1+1` | 365–373 | 95–114 | 112–137 |

Sıcak `go` ≈ node ~100 + WS açılışı/4 enable ~15 + navigasyon ~15 + sessizlik 100 + 3 evaluate ~10. Hedef ≤150 için
sessizlik penceresi ve havuzlu oturum (aşağıda) gerekir; node tabanı ayrı iş.

### 5.2 İnceleme turu gerilemesi ve düzeltmesi (08.11 17:00–17:10, yük 11–17)

İnceleme commit'i 2c2be74 sonrası düşük yükte ölçüm sıcak yolu geri gitmiş gösterdi: `content` 316–331, `eval` 310–320,
`go` 437–531 ms. Sebep tek satırdı: `_daemon_run_request`'in `finally` bloğundaki `watcher.join(0.2)`. İzleyici iş parçacığı
`conn.recv(1)`'de bekler; istemci bağlantıyı ancak `{"exit"}` çerçevesinden sonra kapatır, çerçeve ise `finally`'den sonra
gider → her istek 200 ms tavanı bekliyordu. `join` kaldırıldı (iş parçacığı bağlantı kapanınca kendi biter); kaynak testi
`daemon: the request end never waits on the client watcher thread` tripwire.

| Komut | Taze | Sıcak (2c2be74, gerileme) | Sıcak (düzeltme sonrası) |
|---|---|---|---|
| `go file://paint.html` | 483–882 | 437–531 | 230–370 (ilk 2 ısınma, sonra 230–242) |
| `go https://example.com` | — | — | 227–304 |
| `content` | 408–466 | 316–331 | 105–124 |
| `eval 1+1` | 383–400 | 310–320 | 108–137 |

Ders: istek başına eklenen her bekleme (join, sleep, zaman aşımı) sıcak yolda doğrudan gecikmedir; inceleme turu düzeltmeleri de
ölçümle kapanır (§5.1 ile aynı betik `olc.sh`, 3/5 tekrar).

### 5.3 Sıcak yolun bölünmesi: istemci mi, Python mı? (08.11 17:15–17:25, yük 10–21, şişkin)

Ham soket isteği (node açılışı yok; `ham-istek.js` bağlan → hello → istek → exit):

| İstek | bağlan+hello | ilk çerçeve | toplam |
|---|---|---|---|
| `version` (tarayıcısız) | 3 ms | 2 ms | 5–6 ms |
| `eval 1+1` | 3 ms | 7–21 ms | 12–26 ms |
| `content` | 3 ms | 12 ms | 17 ms |

Yani sıcak `eval`in ~110–145 ms'sinin yalnız 12–26 ms'si Python/CDP; kalan istemcidir. İstemci tabanı (dönüşümlü ölçüm, aynı dakika):

| İstemci | `-e 0` / boş | sıcak `eval 1+1` | not |
|---|---|---|---|
| node 26 arm64 (Homebrew, paylaşımlı openssl/icu dylib) | 123–134 | 142–152 | snapshot + code cache açık; dyld yükü |
| node 20 x86_64 (Rosetta, PATH'teki) | 80–89 | 109–124 | daha hızlı! |
| `sh` + `python3 -I -S` istemci (prototip, scratchpad) | 46–50 | 112–123 | json/socket import + env serileştirme ~50 ms |
| `sh -c :` | 14 | — | kabuk tabanı (yük altında; normalde ~2) |

Sonuç: istemci tabanı sıcak yolun %80–85'i. Hafif istemci (sh + python) node 26'ya karşı ~25 ms kazandırır, node 20'ye karşı
hiç — yeterli değil, bin hikâyesini (Windows, npm shim) karmaşıklaştırır → yapılmadı. Resmî node ikilisi statik bağlıdır
(~40 ms taban); Homebrew node'un dyld yükü kullanıcının ortamıdır. MCP kipinde (`cdpilot mcp`) istemci maliyeti zaten yoktur:
araç çağrısı yalnız CDP işidir. Kalan kazanç Python tarafında (`go` için havuzlu oturum, §6) ve `go`'nun sondalarında (§6 #4 ✅).

## 6. Sonraki adım (D2): `go`'yu havuzlu oturuma taşımak

| # | İş | Beklenen | Kapı |
|---|---|---|---|
| 0 | ✅ Sabit 300 ms uyku → 100 ms olay sessizliği (tavan 300) | −200 ms statik sayfada | ölçüldü §5.1 |
| 1 | ⏸ ERTELENDİ (08.11 18:00, ölçümle; gerekçe §6.1) — `navigate_collect` daemon'da `_WS_POOL` oturumunu kullansın (`_ws_lock` altında olay döngüsü); taze süreçte bugünkü yol | −(WS açılışı + 4 enable) ≈ 50–150 ms | aynı çıktı; e2e CI yeşil |
| 2 | Stealth/UA/blokaj kaydı havuzlu oturumda kalıcı → "stealth go oturumuna bağlı" sınırı kalkar | davranış iyileşmesi | sannysoft e2e |
| 3 | Olay hijyeni: navigasyon bitince `Network.disable`, `Log.disable`; `Page`/`Runtime` açık kalır | §3.1 riski kapanır | boşta 10 dk → sonraki `go` yeniden bağlanmıyor |
| 4 | ✅ Yük sonrası 4 evaluate (host, friction, friction içindeki captcha, captcha) tek `Runtime.evaluate` (`POST_NAV_PROBE_JS`, `_post_nav_probe`) | −3 tur; ölçüm (yük 11–17): sıcak `go` 229–236 ms, önce 230–242 → yerelde fark gürültü içinde (havuzlu WS'te tur 1–3 ms); kazanç uzak/yavaş CDP'de ve ağır sayfada (3 ayrı detector çalışması yerine 1) | sahte CDP testi: yükten sonra yalnız sayfa okuma + 1 sonda; süreç içi test: parçalar eksikse tekil sondaya düşüş |
| 5 | Düşük yükte yeniden ölçüm (yük <10), tabloyu güncelle | — | `go` ≤150 ya da sınırın adı konur (node 110 + navigasyon) |

node açılışının 110 ms'si ayrı iş: kabuk/C ince istemci (`cdpilot` ikilisi) ya da `node --snapshot-blob`; ölçülmeden söz verilmez.

### 6.1 D2 #1 kararı: havuzlu `go` oturumu ertelendi (08.11 18:00)

Oturum-bağlı durum envanteri (`navigate_collect`, kendi WS'inde): `Page/Network/Runtime/Log.enable` · stealth betiği
(`Page.addScriptToEvaluateOnNewDocument`, kademeye bağlı; dış tarayıcı ve bot-auth'ta yok) · başsız UA düzeltmesi
(`apply_headless_ua_override`, aynı oturum) · `Network.setBlockedURLs` (desenler). `cdp_send` havuzlu sokette istenmeyen
olayları zaten yok sayar (yalnız bekleyen id'leri eşler); yani havuzlu oturum teknik olarak kurulabilir: betik kimliği +
(kademe, desen) imzası tutulur, kademe değişince eski betik kaldırılır, navigasyon sonrası `Network/Log.disable`.

Ama kazanç yok denecek kadar az: sıcak `go` ≈ 230 ms = node ~125 (bu makinede) + sessizlik penceresi 100 + Python/CDP ≤ 15.
WS açılışı + 4 enable + betik kaydı yerelde ≤ 15 ms. Kalan kaldıraç **sessizlik penceresi**dir (100 ms): yüklemeden sonra
bekleyen istek yoksa (`Network.requestWillBeSent` − `loadingFinished/Failed` = 0) pencere 30 ms'ye inebilir (−70 ms);
SPA'da yük sonrası DOM değişimini kaçırma riski ölçülmeden karar verilmez (bekleyen iş: SPA settle ölçümü — 3 SPA
sayfasında `innerText` uzunluğunun yük sonrası zaman eğrisi). Nadir kararı: pencere sabit kalsın mı, "bekleyen istek yok"
kısayolu mu?

## 7. MCP araç çağrısı sıcak süreçte (10.11, şef kararı; Kovan K-0021) — UYGULANDI

Sorun: MCP sunucusu (`cdpilot mcp`) her araç çağrısında taze Python süreci açıyordu
(`subprocess.run([sys.executable, __file__] + args)`): yorumlayıcı açılışı + 23 bin satırın derlenmesi (bytecode önbelleği
bu yolda yoktu) → CDP işi başlamadan ~400 ms. Daemon kazancı (§2, §5) MCP yoluna hiç yansımıyordu; MCP, modellerin
cdpilot'a en çok kullandığı yoldur.

```
eski:  model → MCP sunucusu → taze Python (açılış + derleme ~400 ms) → CDP
yeni:  model → MCP sunucusu ──_daemon_execute (aynı süreç, ~10 ms)──▶ CDP
```

Tasarım: `_daemon_run_request` ikiye ayrıldı. Çekirdek `_daemon_execute(req, out, err, refuse, on_run)` bir çağrıyı bu
süreçte kendi süreciymiş gibi koşturur (argv / ortam / cwd / stdin takası, modül durumu sıfırlama, `atexit` kancaları
istek sonunda, CDP soketleri istek sonunda kapanır, çıkış kodu döner ya da `refuse(sebep)` ile reddeder). Soket
sarmalayıcı (`_daemon_run_request`) çerçeveleri ve istemci gözcüsünü ekler; `MCPServer._run_warm` aynı çekirdeği sunucu
sürecinde çağırır: soket yok, anahtar yok, node yok. Kurallar aynı: yaşam döngüsü komutları (`launch`, `connect`, …) ve
bayat proje ayarı taze süreçte koşar; 30 sn aşımı görevin ilk async adımında iptal eder (taze süreçte öldürme idi; tamamen
eşzamanlı takılma kesilmez — cdpilot komutlarının hepsi async CDP işi). `IS_MCP_SESSION` sunucu sürecinde True yapılır
(çocuk süreçlerin `CDPILOT_MCP_SESSION=1` ile gördüğü şey). POSIX; `CDPILOT_DAEMON=1` sunucunun ortamında.

Ölçüm (10.11, M1 Max, yük 30–50, ortak başsız Chrome 152 `connect 9333`, stdio oturumu, 4 araç × 3 tur; betik
`.claude/docs/olcum/olc-mcp.js`):

| Araç | Taze süreç (medyan, tur > 0) | Sıcak süreç (medyan) | Fark |
|---|---|---|---|
| `browser_eval` | 412 ms | 11 ms | −%97 |
| `browser_tabs` | 390 ms | 7 ms | −%98 |
| `browser_content` | 416 ms | 9 ms | −%98 |
| ilk çağrı (sekme açma dahil) | 773 ms | 382 ms | — |

Parite (aynı 7 çağrı taze ve sıcak, gerçek Chrome): `navigate`, `eval`, `content`, `a11y`, `click`, bilinmeyen araç birebir
aynı; `tabs` farkı yalnız paylaşılan tarayıcıda önceki koşunun açık sekmesi. Test: sahte tarayıcıya karşı süreç içi oturum,
`subprocess.run` çocuk süreci reddediyor (yalnız `launch` ona düşer), 1 sn aşımı iptal + sonraki çağrı sağlıklı, akışlar
geri yüklü, istek ortamı sunucuya sızmıyor. Sınır: Windows'ta taze süreç sürer; tutanak `TT-…` commit mesajında.
