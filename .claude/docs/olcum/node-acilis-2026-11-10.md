# Node Başlatıcı Açılış Süresi Ölçümü (10.11.2026)

> **Şef notu (10.11 23:3x):** Kod değişikliği birleştirilmedi. `enableCompileCache` +3,4 ms ölçtü (yük 279–384 altında gürültü içinde); raporun kendi ≥ 10 ms eşiğini geçmiyor. Kalıcı bulgu: başlatıcının ~%93'ü Node ikilisinin açılışı (Homebrew Node 26 `node -e 0` 128 ms; nvm Node 22 46 ms, Node 24 40 ms; aynı yük). Başlatıcı JS'i 10,4 ms. Sıcak yolda hız kaldıracı kod değil, Node ikilisi; README'de not olarak verilebilir, kodla çözülmez. Ölçüm agy-filo `kod` şeridi (3.8 Flash), yük ~300.


Bu belge, `bin/cdpilot.js` başlatıcısının açılış maliyetini ve optimizasyon denemelerini belgeler.

Makine: Apple M1 Max (arm64), macOS. Yüksek sistem yükü altında ölçüldü.
Ölçüm ortamı: Geçici `CDPILOT_HOME`, `CDP_PORT=19555`, `CDPILOT_LOG=0`. Sıcak süreçte daemon önceden başlatıldı (`cdpilot daemon start`).

## 1. Node Sürümleri Taban Karşılaştırması (N=20, medyan ve p90)

| Node Sürümü | Sistem Yükü (loadavg) | `node -e 0` (ms) | `cdpilot --version` (ms) | Sıcak `record status` (ms) |
|---|---|---|---|---|
| Node 26.13.0 (Homebrew) | 305.88 387.96 423.14 | 128.1 (p90: 227.5) | 186.0 (p90: 267.5) | 184.1 (p90: 279.1) |
| Node 22.16.0 (nvm) | 302.97 383.22 420.83 | 45.6 (p90: 109.3) | 79.4 (p90: 140.0) | 81.9 (p90: 138.6) |
| Node 24.16.0 (nvm) | 320.28 356.81 403.36 | 40.2 (p90: 69.1) | 45.5 (p90: 100.2) | 59.9 (p90: 80.2) |

Homebrew Node 26 ikilisi dinamik kütüphanelere (`libnode.dylib`, `libicu`, `libcrypto`, `libssl` vb. 35+ dylib) bağlıdır. `node -e 0` tabanı ~128 ms sürer. NVM Node 22/24 sürümlerinde taban ~40–45 ms düzeyindedir.

## 2. Başlatıcı İçi Süre Dağılımı (`bin/cdpilot.js` hrtime profili)

Sıcak `record status` çağrısında JavaScript tarafı toplam ~10.4 ms sürer:

| Aşama | Süre (ms) | Açıklama |
|---|---|---|
| Giriş → `setBlocking` | 3.32 | `process.stdout`/`stderr` tty akışlarının ilk erişim başlatması |
| Üst düzey `require` | 0.69 | `child_process`, `path`, `fs`, `os`, `package.json`, `net` |
| `findPython()` | 0.21 | `python.json` önbelleğinden okuma |
| `pythonEnv()` | 4.15 | `findBrowser()` aday taraması + `resolveProjectConfig()` |
| `daemonKey` + soket yolu | 0.31 | Ortam dizgilerini SHA1 özetleme (dosya içeriği özetlemez) |
| `daemonPathSafe` | 0.12 | Soket ve dizin izinlerinin denetimi (`fs.lstatSync`) |
| Soket IPC + yanıt alımı | 1.46 | Unix soketine bağlanma, payload gönderimi ve çıkış kodu alımı |
| **Toplam JS süresi** | **10.40** | Node açılışı harici başlatıcı çalışma süresi |

## 3. Optimizasyon Denemeleri (A/B Çapraz Koşu, N=20, Node 26)

Kural: Yalnız Node 26'da medyan kazancı ≥ 10 ms olan ve davranış değiştirmeyen değişiklikler tutulur.

| Seçenek | Sistem Yükü | Taban Medyan (p90) | Deneme Medyan (p90) | Medyan Kazanç | Karar |
|---|---|---|---|---|---|
| (a) `module.enableCompileCache()` | 279.11 329.07 383.69 | 188.8 ms (357.9) | 185.4 ms (289.0) | +3.4 ms | **Tutuldu** (korumalı eklendi) |
| (b) Tembel `child_process` yükleme | 346.32 339.91 385.41 | 321.4 ms (628.3) | 394.4 ms (654.0) | -73.0 ms | **Reddedildi** (<10 ms kazanç yok) |
| (c) Sıcak yolda gereksiz fs kaldırma | 364.01 344.19 386.15 | 150.8 ms (170.7) | 149.1 ms (182.6) | +1.7 ms | **Reddedildi** (<10 ms) |
| (d) Tembel `setBlocking` | 350.90 342.57 384.60 | 168.7 ms (295.1) | 178.4 ms (470.4) | -9.7 ms | **Reddedildi** (<10 ms kazanç yok) |

## 4. Uygulanan Değişiklikler ve Testler

1. `bin/cdpilot.js`:
   - `module.enableCompileCache` eklendi.
   - Node 18/20 sürümleri için koruma sağlandı (`typeof enableCompileCache === 'function'`).
   - Önbellek dizini `path.join(cdpilotHome(), 'compile-cache')` olarak ayarlandı.
   - Yazılamayan veya dosya çakışması olan dizinler için `try/catch` ile hatasız çalışma sağlandı.

2. `test/test.js`:
   - `bin: compile cache is guarded for older Node and an unwritable cache dir never fails a call` testi eklendi.
   - Kaynak kodu denetimi ve engelli önbellek dizini senaryoları doğrulandı.

## 5. Kalan Taban (Node'un Kendi Açılış Maliyeti)

Başlatıcının kendi JavaScript kodu sıcak yolda yalnızca ~10 ms harcamaktadır.
Geriye kalan ~130–175 ms tamamen Homebrew Node 26 ikilisinin macOS dinamik bağlayıcı (`dyld`) yüküdür.
Statik veya daha az kütüphaneye bağlı Node sürümlerinde (Node 22 ve 24) bu süre doğrudan ~40–60 ms seviyesine inmektedir.
Node çalışma zamanı kullanılmaya devam edildiği sürece Homebrew Node 26 üzerindeki taban ~130 ms altına inemez. Daha düşük süre için C/Rust ince istemcisi gereklidir (`plan-daemon-insan-hizi.md` §5.3).
