# Performans tabanı — 08.11.2026 (Nadir sorusu: "sekmeyi açıp ilk boyama, siteye girmemle aynı hız olabilir mi?")

Koşullar: Apple M1 Max, yük ortalaması ~10 (ölçüm anı), ortak başsız tarayıcı `HeadlessChrome/152` (`cdpilot connect 9333`,
yalıtılmış `CDPILOT_HOME`), `node bin/cdpilot.js` 26.13 + `/opt/homebrew/bin/python3`, `CDPILOT_LOG=0`. 3 tekrar, ham değerler.

## 1. Uçtan uca komut süresi (kabuktan dönüşe, ms)

| Komut | 1 | 2 | 3 | Sayfanın kendi ölçümü |
|---|---|---|---|---|
| `status` | 104 | 104 | 144 | — |
| `go file://paint.html` (statik, 2 satır) | 1307 | 991 | 956 | first-paint **20 ms**, load 9 ms |
| `go https://example.com` | 1149 | 946 | — | first-paint **16 ms** |
| `content` | 711 | 663 | — | — |

Tarayıcı sayfayı 16–20 ms'de boyuyor; cdpilot'un `go` komutu uçtan uca ~1 s. Fark cdpilot'un sabit maliyetidir.

## 2. Sabit maliyetin ayrışımı (s)

| Parça | Ölçüm | Not |
|---|---|---|
| boş `python3 -c pass` | 0,02–0,03 | yorumlayıcı |
| `src/cdpilot.py` derlemesi (22.289 satır, önbelleksiz) | 0,15–0,16 | betik olarak çalışınca HER çağrıda yeniden derlenir (ana betik için .pyc yazılmaz) |
| modül olarak içe aktarma (.pyc önbellekli) | 0,16–0,20 | derleme düşer, modül düzeyi başlatma (import'lar, regex derlemeleri) kalır |
| `python3 src/cdpilot.py --version` | 0,26–0,33 | derleme + başlatma |
| `node bin/cdpilot.js --version` (yalnız node) | 0,17–0,28 | node açılışı + sarmalayıcı |
| CDP oturumu (`/json`, WS, hedef, stealth betiği, bekleme) | ≈0,5 | `go` − (node + python) kalanı |

Sabit maliyet ≈ 0,4 s (node 0,1 + derleme 0,15 + başlatma 0,13) + CDP oturum kurulumu ≈ 0,5 s.

## 3. Cevap

Evet, mümkün: boyamayı yapan tarayıcıdır ve 20 ms'de yapıyor; cdpilot'un üstüne koyduğu ~1 s'nin hepsi
süreç başlatma ve oturum kurulumudur, ikisi de kalıcı süreçle sıfıra yakın iner.

| Adım | Beklenen kazanç | Nasıl |
|---|---|---|
| A. Bytecode önbelleği | −0,15 s | ana betiği modül olarak yükleyen 3 satırlık yükleyici ya da pakete .pyc; test: `--version` < 0,15 s |
| B. Tembel import | −0,05…0,10 s | ağır modüller (ssl, hmac, ipaddress, …) ilk kullanımda |
| C. Kalıcı süreç (daemon) | −0,35 s | `cdpilot serve` zaten var (`cmd_serve`); CLI önce yerel sokete bakar, varsa komutu ona verir, yoksa bugünkü yol |
| D. Sıcak oturum | −0,4 s | daemon sayfa WS'sini açık tutar; `go` = navigasyon + ~10 ms |

Hedef (ölçülebilir): yerel statik sayfada `go` p50 ≤ 150 ms uçtan uca; `status` ≤ 30 ms. Bu tabloya karşı ölçülür.

## 4. Yöntem (tekrar için)

```
CDPILOT_HOME=$(mktemp -d) CDPILOT_LOG=0 node bin/cdpilot.js connect 9333
# her komut: python time.time() farkı (kabuk + python açılışı ~60 ms düşüldü)
node bin/cdpilot.js eval "JSON.stringify(performance.getEntriesByType('paint').map(e=>[e.name, Math.round(e.startTime)]))"
```
Açılan sekme `curl http://127.0.0.1:9333/json/close/<id>` ile kapatıldı; tarayıcı kapatılmadı.
