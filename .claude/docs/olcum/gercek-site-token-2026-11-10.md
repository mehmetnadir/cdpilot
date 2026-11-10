# Gerçek Site Token Ölçümü (2026-11-10)

## Sistem Yükü ve Ölçüm Koşulları
- Ölçüm zamanı: 2026-11-10 12:00–12:06 UTC+3
- Sistem yükü (`uptime`): `up 6 days, 1:07, 2 users, load averages: 30.94 30.88 30.67`
- Donanım: Apple M1 Max (arm64), macOS
- Node: arm64, Python: /opt/homebrew/bin/python3.13
- Tarayıcı: Ortak başsız Chrome 127.0.0.1:9333 (`HeadlessChrome/152.0.7977.30`)
- Çalışma kipi: `CDPILOT_DAEMON=1 CDPILOT_LOG=0`
- Duvar saati ölçümü: `perl -MTime::HiRes`
- Ham veriler: scratchpad `serit/token-olcum/` (kalıcı değil; 27 JSON + ms dosyası; şef 10.11 spot denetimi: hn observe 5.836, hn run 90/11.718–11.868, httpbin click 482, httpbin run 119/1.116 birebir)

---

## 1. Senaryo: Hacker News (`https://news.ycombinator.com/`)

### Adım Tablosu

| Adım | Komut | token_estimate | ms (duvar) | Notlar |
|---|---|---|---|---|
| 1 | `agent act --url https://news.ycombinator.com/` | 5847 | 1378 | added actions: 349, text: 0 karakter, injection_suspect: yok |
| 2 | `agent observe` | 5836 | 139 | actions: 349, text: 0 karakter, injection_suspect: yok |
| 3 | `agent act --ref @100 --action click` | 6607 | 526 | added actions: 351, removed: 349, text: 0 karakter, injection_suspect: yok |
| 4 | `agent observe --diff` | 41 | 138 | added actions: 0, removed: 0, text: 0 karakter, injection_suspect: yok, saved_vs_full: 0.993 |
| 5 | `agent flow save hn-new` | — | 185 | kaydedilen adım: 2, host: news.ycombinator.com, vars: [] |
| 6 | `agent run hn-new (koşu 1)` | 90 | 928 | adımlar: 2, tokens_avoided: 11718, iç ms: 834, injection_suspect: yok |
| 7 | `agent run hn-new (koşu 2)` | 90 | 864 | adımlar: 2, tokens_avoided: 11868, iç ms: 772, injection_suspect: yok |
| 8 | `agent run hn-new (koşu 3)` | 90 | 918 | adımlar: 2, tokens_avoided: 11868, iç ms: 819, injection_suspect: yok |

---

## 2. Senaryo: Wikipedia (`https://en.wikipedia.org/wiki/Main_Page`)

### Adım Tablosu

| Adım | Komut | token_estimate | ms (duvar) | Notlar |
|---|---|---|---|---|
| 1 | `agent act --url https://en.wikipedia.org/wiki/Main_Page` | 8061 | 584 | added actions: 405, text: 0 karakter, injection_suspect: yok |
| 2 | `agent observe` | 7217 | 167 | actions: 405, text: 274 karakter, injection_suspect: yok |
| 3 | `agent act --ref @2587 --action fill --text "Browser automation"` | 57 | 168 | added actions: 1, value_changed: 1, text: 0 karakter, injection_suspect: yok, saved_vs_full: 0.992 |
| 4 | `agent act --ref @2558 --action click` | 94 | 325 | added actions: 3, removed: 3, text: 0 karakter, injection_suspect: yok, saved_vs_full: 0.987 |
| 5 | `agent observe --diff` | 45 | 171 | added actions: 0, removed: 0, text: 0 karakter, injection_suspect: yok, saved_vs_full: 0.994 |
| 6 | `agent flow save wiki-ara` | — | 95 | kaydedilen adım: 3, host: en.wikipedia.org, vars: [] |
| 7 | `agent run wiki-ara (koşu 1)` | 136 | 1282 | adımlar: 3, tokens_avoided: 21823, iç ms: 1183, injection_suspect: yok |
| 8 | `agent run wiki-ara (koşu 2)` | 136 | 1136 | adımlar: 3, tokens_avoided: 21823, iç ms: 1023, injection_suspect: yok |
| 9 | `agent run wiki-ara (koşu 3)` | 136 | 1215 | adımlar: 3, tokens_avoided: 21823, iç ms: 1118, injection_suspect: yok |

---

## 3. Senaryo: Httpbin Form (`https://httpbin.org/forms/post`)

### Adım Tablosu

| Adım | Komut | token_estimate | ms (duvar) | Notlar |
|---|---|---|---|---|
| 1 | `agent act --url https://httpbin.org/forms/post` | 1340 | 783 | added actions: 23, text: 0 karakter, injection_suspect: yok |
| 2 | `agent observe` | 385 | 101 | actions: 23, text: 0 karakter, injection_suspect: yok |
| 3 | `agent act --ref @4227 --action fill --text "Test"` | 48 | 116 | added actions: 1, value_changed: 1, text: 0 karakter, injection_suspect: yok, saved_vs_full: 0.875 |
| 4 | `agent act --ref @4225 --action click` | 482 | 388 | added actions: 3, removed: 24, text: 0 karakter, injection_suspect: yok |
| 5 | `agent observe --diff` | 37 | 98 | added actions: 0, removed: 0, text: 0 karakter, injection_suspect: yok, saved_vs_full: 0.909 |
| 6 | `agent flow save httpbin-form` | — | 90 | kaydedilen adım: 3, host: httpbin.org, vars: [] |
| 7 | `agent run httpbin-form (koşu 1)` | 119 | 667 | adımlar: 3, tokens_avoided: 1116, iç ms: 566, injection_suspect: yok |
| 8 | `agent run httpbin-form (koşu 2)` | 119 | 639 | adımlar: 3, tokens_avoided: 1116, iç ms: 549, injection_suspect: yok |
| 9 | `agent run httpbin-form (koşu 3)` | 119 | 661 | adımlar: 3, tokens_avoided: 1116, iç ms: 564, injection_suspect: yok |

---

## Karşılaştırma: Model Döngüsü vs `agent run`

| Senaryo | Model döngüsünde toplam token | `agent run` sonuç token | Token değişimi | `tokens_avoided` | 3 koşunun ms süreleri (duvar / iç) | Sapma (çıkış 4) ve neden |
|---|---|---|---|---|---|---|
| Hacker News (`hn-new`) | 18.331 (tüm adımlar)<br>12.484 (observe + act diff'leri) | 90 | −%99,5<br>(−%99,3) | 11.718 – 11.868 | 928 / 834 ms<br>864 / 772 ms<br>918 / 819 ms | Sapma yok (çıkış 0, status: ok) |
| Wikipedia (`wiki-ara`) | 15.474 (tüm adımlar)<br>7.413 (observe + act diff'leri) | 136 | −%99,1<br>(−%98,2) | 21.823 | 1.282 / 1.183 ms<br>1.136 / 1.023 ms<br>1.215 / 1.118 ms | Sapma yok (çıkış 0, status: ok) |
| Httpbin (`httpbin-form`) | 2.292 (tüm adımlar)<br>952 (observe + act diff'leri) | 119 | −%94,8<br>(−%87,5) | 1.116 | 667 / 566 ms<br>639 / 549 ms<br>661 / 564 ms | Sapma yok (çıkış 0, status: ok) |

### Gözlemler
- Model döngüsünde toplam token:
  - HN: 5.847 (`act --url`) + 5.836 (`observe`) + 6.607 (`act click`) + 41 (`observe --diff`) = 18.331 token (yalnızca `observe` + diff adımları: 12.484 token).
  - Wikipedia: 8.061 (`act --url`) + 7.217 (`observe`) + 57 (`act fill`) + 94 (`act click`) + 45 (`observe --diff`) = 15.474 token (yalnızca `observe` + diff adımları: 7.413 token).
  - Httpbin: 1.340 (`act --url`) + 385 (`observe`) + 48 (`act fill`) + 482 (`act click`) + 37 (`observe --diff`) = 2.292 token (yalnızca `observe` + diff adımları: 952 token).
- `agent run` sonuç token'ı: HN için 90, Wikipedia için 136, Httpbin için 119 token.
- Token tasarrufu: gerçek sitelerde %87,5 ile %99,5 arasındadır.
- `tokens_avoided`: HN'de ~11.800, Wikipedia'da 21.823, Httpbin'de 1.116 token.
- Sapma (drift): 3 senaryonun toplam 9 koşusunda da 0 sapma gözlendi; tüm adımlar tam çapa (exact anchor) eşleşmesiyle tamamlandı.

## Şef notu (10.11)

- Ölçüm agy-filo şeridi (gemini-3.8-flash-high, 894 sn, girdi 9,3 M token — israf tavanı aşıldı: ham JSON'ları bağlama okudu).
  Sayılar şef tarafından ham dosyalarla denetlendi (yukarıda).
- `tokens_avoided` adım başına tam gözlem tahminidir (üst sınır): Wikipedia'da 21.823 > model döngüsü 15.474; diff kullanan
  bir ajan daha az okur. Doğru karşılaştırma "model döngüsü toplamı → `agent run` sonuç JSON'u" sütunudur: HN 18.331 → 90,
  Wikipedia 15.474 → 136, httpbin 2.292 → 119.
- Sapma 9 koşuda 0: üç sitenin çapaları (rol + ad + sıra) koşular arasında sabit kaldı. Yük 31 altında süreler şişkin;
  oranlar geçerli. Wikipedia araması 800 px'te gizli kutu yüzünden 1280 px görünümle ölçüldü (şerit notu).
