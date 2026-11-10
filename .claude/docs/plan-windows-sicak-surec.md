# Windows'ta sıcak süreç (daemon + MCP içi yürütme) — tasarım notu

Durum: TASLAK, 10.11.2026. Kaynak: `plan-daemon-insan-hizi.md` §1, §3, §4 (v3 satırı), §7. Mac'te yazıldı;
Windows'ta HİÇBİR şey koşturulmadı. Kod iddiaları grep sonucuna dayanır (`dosya:satır`). Doğrulanmayanlar **[DV]** ile işaretli.

## 1. Bugünkü durum (grep)

| Parça | Windows'ta ne olur | Kanıt |
|---|---|---|
| İstemci kapısı | `daemonEnabled()` Windows'ta hep `false` → her çağrı taze | `bin/cdpilot.js:96` |
| `daemon start` | "not available on Windows yet", çıkış 1 | `bin/cdpilot.js:272-275` |
| Sahiplik denetimi | `process.getuid` yok → `daemonPathSafe` hep `true` (denetim yok) | `bin/cdpilot.js:147` |
| Daemon girişi | `hasattr(socket,"AF_UNIX")` yoksa `sys.exit(2)` | `src/cdpilot.py:23096` |
| MCP içi yürütme | `sys.platform == "win32"` → `None` → taze süreç | `src/cdpilot.py:18745` |
| Testler | daemon ve `mcp warm` testleri Windows'ta atlanır | `test/test.js:98`, `:7642` |
| CI | `windows-latest` (node 20, py 3.11) taze kipte koşar; daemon girişi yalnız ubuntu | `ci.yml:48-50`, `:56-60` |

## 2. Taşıma seçenekleri

İstemci Node (`net`), sunucu Python (yalnız stdlib; pywin32 yok). Karşılaştırma:

| Ölçüt | A. AF_UNIX | B. Adlandırılmış boru `\\.\pipe\…` | C. `127.0.0.1` TCP + jeton |
|---|---|---|---|
| Python stdlib | Windows'ta `socket.AF_UNIX` açılmıyor; CPython sorunu açık (gh-77589). İşletim sistemi 1803+ (build 17063) destekler **[DV]** | Zaman aşımsız, bloklayan `multiprocessing.connection.Listener(family="AF_PIPE")`; asyncio `start_serving_pipe` yalnız Proactor'da ve döngü istek arasında koşmuyor (`run_until_complete`, `:22853`) **[DV]** | `socket.socket(AF_INET)`; bugünkü `accept()` döngüsü aynen çalışır (`:23155`) |
| Node çekirdeği | `net` Windows'ta `path`'i boru adı sayar (libuv); AF_UNIX dosyasına bağlanamaz (libuv#2537 açık) **[DV]** | `net.createConnection('\\\\.\\pipe\\ad')` belgelenmiş | `net.createConnection({host, port})` |
| Kim bağlanabilir | — (Node bağlanamadığı için elenir) | Varsayılan DACL: SYSTEM, Yöneticiler, sahip tam; **Everyone okuma** (MS belgesi) **[DV]**. Başka kullanıcı yazamaz ama hello'yu okuyabilir | Makinedeki HER süreç, HER kullanıcı (loopback makine geneli) |
| Sahiplik denetimi | — | Python `_winapi`/`multiprocessing` DACL vermiyor (NULL) **[DV]**; DACL için `ctypes` gerekir. Ad tahmin edilebilir (anahtar = sha1) → sahte sunucu açabilir | `fs.lstat().uid` Windows'ta hep 0 (Node belgesi) **[DV]** → mod/uid denetimi çalışmaz. Jeton + dosya ACL'i + karşılıklı doğrulama |
| Bayat kalıntı | yok (dosya ya da yok) | yok: son tutamakla boru kaybolur (iyi) | bilgi dosyası kalır; bugünkü `daemon stop` temizliği aynı |
| Güvenlik duvarı / antivirüs | sormaz **[DV]** | sormaz **[DV]** | `127.0.0.1`'e bağlanan dinleyici genelde istem çıkarmaz; `0.0.0.0` çıkarır. Kurumsal EDR sezgisi bilinmiyor **[DV]** |
| POSIX CI'da sınanır mı | evet | hayır (yalnız Windows) | **evet**: aynı kod Mac/Linux'ta `CDPILOT_DAEMON_TRANSPORT=tcp` ile koşar |
| Meşgul daemon | — | tek örnekli boruda ikinci istemci `ERROR_PIPE_BUSY`; libuv bekleme süresi 150 ms hello zamanlayıcısını aşabilir **[DV]** | ikinci bağlantı kuyruğa girer; 150 ms hello düşüşü (`:82`, `:173-175`) aynen çalışır |

Sonuç: A elenir (Node bağlanamaz). B güvenlikte cazip görünür ama Python tarafı özel API ister ve
jeton yine gerekir (ad tahmin edilebilir). **C önerilir**: tek kod yolu, iki ucu stdlib/çekirdek, POSIX'te sınanır.

## 3. Önerilen: C + karşılıklı jeton doğrulaması

```
daemon başlar → 127.0.0.1:0 (işletim sistemi port seçer) → <anahtar>.json yazar: {port, token, pid, version}
istemci: .json'u okur (yoksa bağlanmaz) → bağlanır → {"auth": nonce_c}
daemon : {"hello", version, "proof": HMAC(token, "d"+nonce_c), "nonce": nonce_s}
istemci: proof'u doğrular (tutmuyorsa İSTEK GİTMEZ) → {argv, cwd, env, stdin, "auth": HMAC(token, "c"+nonce_s)}
```

| Karar | Gerekçe |
|---|---|
| Jeton 32 bayt `secrets.token_hex`; dosya `%LOCALAPPDATA%\cdpilot\daemon\` (yoksa `CDPILOT_HOME\daemon`) | Dizin ACL'i kullanıcıya özel miras alır (standart profil: kullanıcı, SYSTEM, Yöneticiler) **[DV]**. Dizin oluşturunca `icacls <dizin> /inheritance:r /grant:r %USERNAME%:(OI)(CI)F` bir kez çalışır **[DV]** |
| Karşılıklı doğrulama | Port kapılırsa (daemon ölür, başkası aynı portu alır) istemci `env`'i (proxy/çözücü anahtarları) sahte sunucuya vermez. Bugünkü hello tek yönlü (`bin/cdpilot.js:190-199`) |
| `SO_EXCLUSIVEADDRUSE` (Windows), `SO_REUSEADDR` yok | Windows'ta `SO_REUSEADDR` başkasının portunu kapmaya izin verir **[DV]** |
| Sabit adres `127.0.0.1` (`localhost` değil) | IPv6 `::1` çözümlemesi ve geç ret süresi |
| Bilgi dosyası yoksa bağlanma | Windows'ta kapalı porta bağlanma ~1–2 sn sürebilir (bilinen davranış) **[DV]**; hello zamanlayıcısı kurtarır ama gereksiz bekletir |
| POSIX'te AF_UNIX kalır | Yalnız `win32` ya da `CDPILOT_DAEMON_TRANSPORT=tcp` TCP kullanır |

## 4. MCP içi yol: iptal ve Ctrl+C

| Konu | Ne olur | Kanıt / not |
|---|---|---|
| Zaman aşımı | `threading.Timer(30 s)` → `_expire` → `call_soon_threadsafe(task.cancel)`. İş parçacığı + döngü API'si platformdan bağımsız | `src/cdpilot.py:18762`, `:18755-18760` |
| Olay döngüsü | `asyncio.new_event_loop()` Windows'ta Proactor (3.8+ varsayılan). `call_soon_threadsafe` Proactor'da kendi-boru ile uyandırır. Taze yol bugün Proactor + websockets ile CI'da koşar | `:18748`; `ci.yml:48` **[DV]: CI sonucunu görmedim** |
| İptal sınırı | İlk async adımda kesilir; tamamen eşzamanlı takılma kesilmez (Mac'tekiyle aynı) | `:18742-18744` |
| MCP süreci Ctrl+C | MCP sunucusu stdin EOF ile biter; `KeyboardInterrupt` döngüyü kırar. Konsolda bloklayan `readline` Windows'ta Ctrl+C ile kesilir mi: bilinmiyor | `:19087-19110` **[DV]** |
| CLI istemcisi Ctrl+C | `bin/cdpilot.js` SIGINT dinlemez (grep: yok). Node düşer → TCP kapanır (FIN ya da RST) → `_daemon_watch_client` `recv` boş döner ya da `OSError` (WSAECONNRESET de `OSError`) → `task.cancel`, çıkış 130 | `:22906-22928` |
| Daemon konsol olayı almaz | Daemon ayrık; `CTRL_C_EVENT` yalnız istemcinin konsolundaki süreçlere gider. Bu yüzden Ctrl+C iletimi **bağlantı kaybıyla** yapılır, sinyalle değil | `:2021-2022` aynı bayraklar idle izleyicide **[DV]** |
| Taze yol | `spawnPython` `stdio:'inherit'`: Ctrl+C her ikisine gider | `bin/cdpilot.js:1168-1171` |

## 5. `_daemon_execute` ve çevresinde POSIX'e özgü olanlar

`_daemon_execute` (`:22931-23032`) kendisi taşınabilir: `io.StringIO`, `os.environ`, `os.chdir`, `asyncio`, `atexit`. Takılan yerler giriş ve sunucu çevresinde:

| Satır | Kod | Windows'ta | Düzeltme |
|---|---|---|---|
| `:23096` | `hasattr(socket,"AF_UNIX")` | `exit(2)` | taşıma seçimi |
| `:23107` | `os.getuid()` | `AttributeError` (yok) | Windows dalı: `st_uid` denetimi yok; ACL dizinde |
| `:23105` | `os.makedirs(mode=0o700)` | `mode` yok sayılır (Python belgesi) **[DV]** | `icacls` adımı |
| `:23103`, `:23149` | `os.umask(0o077)` | yalnız salt-okunur bitini etkiler **[DV]** | Windows'ta atla |
| `:23121` | `os.chmod(sock,0o600)` | yalnız salt-okunur bayrağı **[DV]**; soket dosyası yok | atla |
| `:23136` | `for sig in (signal.SIGTERM, signal.SIGHUP)` | `signal.SIGHUP` yok → `AttributeError` **`try`'ın DIŞINDA** (`:23137-23140` yakalar ama demet satırı önce değerlenir) | `getattr(signal,"SIGHUP",None)` ile süz |
| `:23136` | SIGTERM | Windows'ta kayıt olur, teslim edilmez (`TerminateProcess`) | `shutdown` işlemi zaten soketten (`:23174`); isteğe bağlı `SIGBREAK` |
| `:23071`, `:23109` | `AF_UNIX` soketi | yok | `_daemon_ping` ve sunucu taşıma yardımcısından |
| `:23116` | `os.unlink(sock_path)` kalıntı | TCP'de bilgi dosyası | aynı mantık `.json` için |
| `:22788` | `fileno()` → `UnsupportedOperation` | platformdan bağımsız | yok |
| `:23214-23220` | `os.name=="nt"` ise `sys.stdout.reconfigure` | `_DaemonStream`'de `reconfigure` yok → `AttributeError` yakalanır | sorun değil; UTF-8 çerçeveleri zaten (`:22776`) |
| `bin/cdpilot.js:239-240` | `spawn(..., {detached:true, stdio:'ignore'})` | `windowsHide` yok (grep: hiç yok) → konsol penceresi çıkabilir **[DV]** | `windowsHide:true` |
| `bin/cdpilot.js:130-133` | `process.getuid` → 0 | `os.tmpdir()` Windows'ta kullanıcıya özel `%TEMP%` | yedek dizin gerekmez |

Dosya tutamağı: dinleme soketi PEP 446'ya göre devralınmaz (`socket` varsayılanı) **[DV]**; çocuk süreç `launch` zaten taze süreçte (`DAEMON_SPAWN_CMDS`).

## 6. En küçük değişiklik listesi (fonksiyon düzeyinde)

| # | Dosya | Fonksiyon | İş | Aşama |
|---|---|---|---|---|
| 1 | `src/cdpilot.py` | `MCPServer._run_warm` (`:18745`) | `or sys.platform == "win32"` kalkar | **A** |
| 2 | `test/test.js` | `mcp warm` testi (`:7642`) | Windows atlaması kalkar (POSIX'e özgü kalan: yol/kip varsayımları) | **A** |
| 3 | `src/cdpilot.py` | yeni `_daemon_listen(path)` / `_daemon_connect(path)` | AF_UNIX ya da TCP+bilgi dosyası; tek yer | B |
| 4 | `src/cdpilot.py` | `_daemon_serve_entry`, `_daemon_ping` | taşıma yardımcısı, `getuid/SIGHUP/umask/chmod` Windows dalı, jeton + `SO_EXCLUSIVEADDRUSE` | B |
| 5 | `src/cdpilot.py` | hello üretimi (`:23167`) | `proof` + `nonce` | B |
| 6 | `bin/cdpilot.js` | `daemonEnabled` (`:96`), `daemonCommand` (`:272`) | Windows kapısı kalkar | B |
| 7 | `bin/cdpilot.js` | `daemonDirs`, `daemonSockPath`, `listDaemonSockets` | uç nokta nesnesi `{kind, path, port?}`; `.json` listele | B |
| 8 | `bin/cdpilot.js` | `daemonPathSafe` | Windows: bilgi dosyası var + dizin yolu beklenen kökte | B |
| 9 | `bin/cdpilot.js` | `daemonRequest` | `{host,port}` bağlantısı + karşılıklı doğrulama; sürüm düşüşü korunur | B |
| 10 | `bin/cdpilot.js` | `startDaemon` | `windowsHide:true`, `icacls` | B |
| 11 | `test/test.js` | daemon blokları (`:98`) | yardımcılar `.sock` yerine uç nokta; `.sock` geçen 23 satır uyarlanır (grep) | B |

Aşama A (MCP) ağ yüzeyi açmaz: yalnız bir koşul kalkar. Önce o gider; ölçüm `olc-mcp.js` ile Windows'ta tekrarlanır.
Aşama B yalnız A yeşil ve C seçimi onaylandıktan sonra.

## 7. CI planı

| Adım | Ne | Kapı |
|---|---|---|
| 1 | `matrix` girişi: `windows-latest`, node 20, py 3.12, `daemon: '1'`, `daemon_idle: '30'`; `continue-on-error` mevcut `matrix.daemon == '1'` ifadesiyle zaten açık (`ci.yml:14`) | bilgi amaçlı |
| 2 | Başta tam paket yerine `CDPILOT_TEST_ONLY='daemon'` + `CDPILOT_TEST_ONLY='mcp warm'` (iki ayrı adım; `test.js:17-19` alt dizge süzer) | ikisi yeşil |
| 3 | `CDPILOT_DAEMON_TRANSPORT=tcp` ile ubuntu/macos girişi: Windows kodu yolu POSIX'te sınanır | her koşuda yeşil |
| 4 | Tam paket (Windows, daemon) | ubuntu daemon girişinin ölçütü (§4 v2) |

Uyarı: ubuntu daemon girişi ilk koşuda 3,6× yavaştı, +10 sn takılmalar vardı (`ci.yml:53-55`); Windows runner'ı daha yavaş olabilir — süre sınırı koyulur.

## 8. Riskler

| # | Risk | Etki | Önlem |
|---|---|---|---|
| 1 | Yerel başka kullanıcı bağlanır | istek yürütme | jeton (256 bit) + dosya ACL'i; jeton yoksa `hello` sonrası kapanır |
| 2 | Port kapma, sahte daemon | `env` sızıntısı (proxy/çözücü anahtarları) | karşılıklı HMAC; `SO_EXCLUSIVEADDRUSE`; kanıtsız istek gitmez |
| 3 | `icacls` yok ya da başarısız (kurumsal politika) | ACL belirsiz | başarısızsa daemon başlamaz, taze süreç sürer (güvenli düşüş) |
| 4 | Kurumsal güvenlik duvarı / EDR loopback dinleyiciyi sorar ya da engeller | daemon hiç başlamaz | düşüş taze süreç; `daemon status`'ta sebebi yaz |
| 5 | Windows'ta kapalı porta bağlantı yavaş | boşa 1–2 sn | bilgi dosyası yoksa bağlanma; ölü pid ise dosyayı sil (`_pid_alive`, `:355`) |
| 6 | Konsol penceresi parlaması (`detached` + `python.exe`) | kötü deneyim | `windowsHide:true`; olmazsa `pythonw.exe` **[DV]** |
| 7 | Defender gerçek zamanlı tarama bytecode önbelleğini/ilk açılışı yavaşlatır | kazanç düşer | Windows'ta ölçmeden "varsayılan açık" denmez |
| 8 | `SIGHUP` hatası (§5): bugün Windows'ta daemon girişi `AttributeError` verir | yalnız koşturulursa | 4 numaralı iş; sınama testi `getattr` |
| 9 | MCP içi yol Windows'ta konsol Ctrl+C davranışı | MCP nadiren konsolda koşar | `[DV]`; EOF yolu asıl çıkış |

## 9. Doğrulanamayanlar (bu Mac'te koşturulamaz)

| Madde | Neden | Nasıl doğrulanır |
|---|---|---|
| `socket.AF_UNIX` / Node `net` + AF_UNIX Windows durumu | yalnız web özeti (gh-77589, libuv#2537 açık); Windows yok | `windows-latest`'te `python -c "import socket;print(hasattr(socket,'AF_UNIX'))"` |
| Boru varsayılan DACL, `_winapi` güvenlik parametresi, libuv `PIPE_BUSY` bekleme süresi | belge bilgisi; sınanmadı | Windows'ta küçük deneme betiği |
| `fs.lstat().uid == 0`, `os.chmod/umask/makedirs` etkisizliği | belge bilgisi | CI'da `node -p` / `python -c` |
| `%LOCALAPPDATA%` miras ACL'i, `icacls` komutu, güvenlik duvarı istemi, EDR | Windows + kurumsal ortam | Windows sanal makinesi, `icacls` çıktısı |
| Kapalı porta bağlanma 1–2 sn, `windowsHide` sonucu | ölçülmedi | `daemon status` + süre ölçümü |
| Proactor altında bu paketin tamamı | CI sonucu görülmedi | `ci.yml` windows-latest koşusu |
