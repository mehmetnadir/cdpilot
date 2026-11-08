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
- **`asyncio.run` kalkanı.** Dağıtıcı `asyncio.run(_wrapped())` çağırır; daemon bunu kalıcı döngüde `run_until_complete`
  yapar. `_ws_lock` havuzu "döngü aynı mı" damgasıyla tutar (3691–3717); döngü aynı kaldığı için `_WS_POOL`
  istekler arası yaşar. Bekleyen görevler iptal edilmez: websockets'in aktarım/keepalive görevleri o döngüdedir.
- **İstek sonu = eski süreç sonu.** `_slog_begin` (günlük + kayıt adımı), `_idle_touch_activity` ve zaman aşımı
  `atexit.register` kullanır; daemon kaydı istek listesine alır, sonunda LIFO koşar. Import anında kaydedilen
  `_ws_pool_close_all` listeye girmez (havuz yaşar); gerçek süreç çıkışında koşar.
- **Sıfırlanan modül durumu** (`_daemon_reset_state`): `_FRAME_FLAG`, `DIALOG_MODE`, `INTERCEPT_RULES`, `_A11Y_REF_MAP`,
  `_SLOG`, `_AUTOLAUNCH`, `_CLICK_MISSES` (exit 3 sızmasın), `_PRESS_MS_WARNED`, `_SHADOW_NOTES_PRINTED`, `_IDLE_WARNED`.
  Kalanlar bilerek kalır: `_CDP_GET_CACHE` (0,5 s TTL), `_glow_script_id` (oturuma bağlı), `_WS_POOL/_WS_LOCKS`.
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
- **Güvenlik.** Yalnız AF_UNIX (Windows şimdilik hep taze süreç); `umask 077`, soket 0600, dizin 0700; dizin başkasının
  ya da grup/diğer izinliyse daemon çıkar (paylaşılan /tmp yarışı). İstek tek satır JSON, 8 MB üst sınır. T2 güvenlik
  denetimi bu yüzey için sırada (§6).

## 2. Ölçüm — tarayıcısız komut (08.11 16:00, M1 Max, yük ~10)

| Komut | Taze (A sonrası) | Sıcak (daemon) |
|---|---|---|
| `version` | 265–280 ms | 138 ms |
| `record status` | 265–280 ms | 149 ms |
| Python tarafı (soketten sokete) | — | 0–3 ms |

Kalan ~140 ms'nin ~110'u node açılışı: ince istemci de node. Daha aşağısı node'suz bir kabuk/ikili istemci ister (ayrı iş).

## 3. Riskler (uygulamada görülen / açık)

1. **Sıcak WS'de olay birikimi.** Havuzdaki oturumda `Page.enable`/`Network.enable` açık kalırsa tarayıcı istekler arasında
   olay basar; döngü boştayken okunmaz, çekirdek tamponu dolar, Chrome 1 MB'ta bağlantıyı kapatır → sonraki istek yeniden
   bağlanır (mevcut `_ws_is_open` yolu). Ölçülecek; gerekirse istek sonunda alanları kapatma.
2. **Bekleyen görevler.** Komutun bıraktığı görev bir sonraki istekte sürer (asyncio.run iptal ederdi). Havuz görevleri
   için zorunlu bırakıldı; sızıntı şüphesinde `asyncio.all_tasks` ölçümü.
3. **Süreç düzeyi işler.** `launch`'ın başlattığı tarayıcı daemon'un çocuğu olur (auto-launch sayfa komutundan gelirse);
   ayrık başlatıldığı için daemon kapanınca yaşar — doğrulanacak.
4. **İstemci kopması.** Komut sürerken istemci ölürse çıktı düşer, komut bitirilir; çift koşu yok ama "yarım iş" olabilir.

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

## 6. Sonraki adım (D2): `go`'yu havuzlu oturuma taşımak

| # | İş | Beklenen | Kapı |
|---|---|---|---|
| 0 | ✅ Sabit 300 ms uyku → 100 ms olay sessizliği (tavan 300) | −200 ms statik sayfada | ölçüldü §5.1 |
| 1 | `navigate_collect` daemon'da `_WS_POOL` oturumunu kullansın (`_ws_lock` altında olay döngüsü); taze süreçte bugünkü yol | −(WS açılışı + 4 enable) ≈ 50–150 ms | aynı çıktı; e2e CI yeşil |
| 2 | Stealth/UA/blokaj kaydı havuzlu oturumda kalıcı → "stealth go oturumuna bağlı" sınırı kalkar | davranış iyileşmesi | sannysoft e2e |
| 3 | Olay hijyeni: navigasyon bitince `Network.disable`, `Log.disable`; `Page`/`Runtime` açık kalır | §3.1 riski kapanır | boşta 10 dk → sonraki `go` yeniden bağlanmıyor |
| 4 | Yük sonrası 3 evaluate tek `Runtime.evaluate`'te (host + friction + captcha tek betik) | −2 tur ≈ 20–60 ms | aynı tespitler (fixture) |
| 5 | Düşük yükte yeniden ölçüm (yük <10), tabloyu güncelle | — | `go` ≤150 ya da sınırın adı konur (node 110 + navigasyon) |

node açılışının 110 ms'si ayrı iş: kabuk/C ince istemci (`cdpilot` ikilisi) ya da `node --snapshot-blob`; ölçülmeden söz verilmez.
