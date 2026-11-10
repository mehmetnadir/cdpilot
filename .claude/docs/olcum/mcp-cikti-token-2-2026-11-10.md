# MCP Araç Çıktıları Token Ölçümü (v2 — 2026-11-10)

> **Şef notu (11.11 00:4x):** Ölçüm tabloları (§1, §2) kullanılabilir; token sayısı karakter÷4 tahminidir, o200k değil.
> §3–§4 yorumu geçersiz: (1) a11y "yinelenen satırlar %94–99" yapı satırlarını (`[generic]`, `[LayoutTableRow]`) sayar;
> bu satırlar ağacın kendisidir, silinemez — "düşük risk, 3.015 token/sayfa" iddiası düşer. (2) observe JSON boşluk payı
> (%25–28) gerçek bir kaldıraçtır ama karakter÷4 girinti boşluğunu abartır (o200k çoğu girinti dizisini tek token sayar);
> karar öncesi o200k ile yeniden ölçülür. Bulunan kaldıraç: `agent observe/act/run` çıktısı `indent=2` ve observe
> `ensure_ascii=True` (Türkçe/Japonca sayfada her harf `\uXXXX`). (3) GitHub ve BBC satırları yük altında 30 sn zaman
> aşımıyla INVALID; `--tools core` "zorunlu" yapmak varsayılan değişikliğidir (jüri konusu), ölçüm değil.

## Sistem Yükü ve Koşullar
- Ölçüm zamanı: 2026-11-10 (yerel)
- Sistem yükü (`uptime`): `0:06  up 6 days, 13:07, 2 users, load averages: 86.29 97.03 115.50`
- Donanım: Apple M1 Max (arm64), macOS
- Ortak başsız Chrome: 127.0.0.1:9333 (`HeadlessChrome/152.0.7977.30`)
- Sunucu kipi: `CDPILOT_DAEMON=1 CDPILOT_LOG=0`
- Token hesap kuralı: cdpilot _estimate_tokens (chars / 4); çevrimdışı o200k kütüphanesi ortamda yüklü değil

---

## 1. `tools/list` Şema Boyutları (Default vs Core)

| Profil | Araç Sayısı | Karakter | Tahmini Token | Tasarruf |
|---|---|---|---|---|
| **Default (all)** | 49 | 29.793 | 7.448 | Referans |
| **`--tools core`** | 11 | 6.294 | 1.574 | **−%79** (5.874 token) |

> [!NOTE]
> `tools/list` şeması MCP istemcisi tarafından her model turunda sistem istemine eklenir.
> Core profil seçildiğinde her istekte **5.874 token** (%79) tasarruf edilir.

---

## 2. Sayfa × Araç Çıktı Boyutları (Token)

| Sayfa | navigate | content | a11y | observe | observe (diff) | tabs | console | network | Toplam |
|---|---|---|---|---|---|---|---|---|---|
| **news.ycombinator.com** | 956 | 956 | 5.597 | 8.191 | 56 | 263 | 766 | 33 | **16.818** |
| **en.wikipedia.org/wiki/Web_browser** | 2.500 | 5.056 | 16.899 | 23.425 | 62 | 252 | 15 | 1.607 | **49.816** |
| **github.com/mehmetnadir/cdpilot** | INVALID (isError=true (Error: Command timed out (30s))) | INVALID (<20 karakter (15c: "Skip to content")) | 30 | 118 | INVALID (Gezinmeyen (non-navigating) etkileşimli öğe bulunamadı) | 293 | 19 | 1.735 | **2.195** |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | 731 | 731 | 2.045 | 3.747 | 71 | 228 | 42 | 3.002 | **10.597** |
| **www.npmjs.com/package/cdpilot** | — | — | — | — | — | — | — | — | *(Bot engeli: atlandı)* |
| **www.bbc.com/news** | INVALID (isError=true (Error: Command timed out (30s))) | INVALID (Boş yanıt) | 13 | 30 | INVALID (Gezinmeyen (non-navigating) etkileşimli öğe bulunamadı) | 188 | 770 | 887 | **1.888** |

> [!IMPORTANT]
> Gereksinim gereğince: Hata, boş ya da 20 karakterden küçük sonuçlar veya gezinmeye sebep olan diff sonuçları **INVALID** olarak işaretlenmiş ve sayfa toplamına **asla dahil edilmemiştir**.

### Sayfa Yükleme ve Son URL Durumları
- **news.ycombinator.com**: Son URL = `https://news.ycombinator.com/`, readyState = `interactive`
- **en.wikipedia.org/wiki/Web_browser**: Son URL = `https://en.wikipedia.org/wiki/Web_browser`, readyState = `interactive`
- **github.com/mehmetnadir/cdpilot**: Son URL = `https://github.com/mehmetnadir/cdpilot`, readyState = `loading`
- **developer.mozilla.org/en-US/docs/Web/API/MutationObserver**: Son URL = `https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver`, readyState = `interactive`
- **www.npmjs.com/package/cdpilot**: Bot engeli tespit edildi (Navigate çıktısında bot/turnstile/captcha tespit edildi.).
- **www.bbc.com/news**: Son URL = `Timeout after 5000ms`, readyState = `Timeout after 5000ms`

### Araç Sonuçları Durumu ve İlk 160 Karakter Denetimi

| Sayfa | Araç | Durum | isError | Karakter | İlk 160 Karakter Özeti |
|---|---|---|---|---|---|
| **news.ycombinator.com** | `browser_navigate` | GEÇERLİ | `false` | 3825 | `Hacker Newsnew \| past \| comments \| ask \| show \| jobs \| submit	login 1.	 	.name Grandfathered (` |
| **news.ycombinator.com** | `browser_content` | GEÇERLİ | `false` | 3825 | `Hacker Newsnew \| past \| comments \| ask \| show \| jobs \| submit	login 1.	 	.name Grandfathered (` |
| **news.ycombinator.com** | `browser_a11y` | GEÇERLİ | `false` | 22388 | `Accessibility tree (1616 visible nodes):   [RootWebArea]   [LayoutTable]   [LayoutTableRow]   [Layou` |
| **news.ycombinator.com** | `browser_agent_observe` | GEÇERLİ | `false` | 32765 | `{   "url": "https://news.ycombinator.com/",   "title": "Hacker News",   "actions": [     {       "re` |
| **news.ycombinator.com** | `browser_agent_observe_diff` | GEÇERLİ | `false` | 225 | `{   "url": "https://news.ycombinator.com/",   "title": "Hacker News",   "changed": {     "added": []` |
| **news.ycombinator.com** | `browser_tabs` | GEÇERLİ | `false` | 1050 | `🟢 [0] about:blank        http://127.0.0.1:3550/blog/f/destination-weddings-in-zanzibar   🟢 [1] Hac` |
| **news.ycombinator.com** | `browser_console` | GEÇERLİ | `false` | 3062 | `=== Console ===   (empty) === Content (first 3000 chars) === 	Hacker Newsnew \| past \| comments \| ` |
| **news.ycombinator.com** | `browser_network` | GEÇERLİ | `false` | 130 | `=== Network Requests ===   ✓ [200]   Document https://news.ycombinator.com/ Total: 1 requests === Co` |
| **en.wikipedia.org/wiki/Web_browser** | `browser_navigate` | GEÇERLİ | `false` | 10000 | `Jump to content Main menu Search Donate Create account Log in Toggle the table of contents Web brows` |
| **en.wikipedia.org/wiki/Web_browser** | `browser_content` | GEÇERLİ | `false` | 20222 | `Jump to content Main menu Search Donate Create account Log in Toggle the table of contents Web brows` |
| **en.wikipedia.org/wiki/Web_browser** | `browser_a11y` | GEÇERLİ | `false` | 67597 | `Accessibility tree (4544 visible nodes):   [RootWebArea]   [generic]   [link]   [banner]   [generic]` |
| **en.wikipedia.org/wiki/Web_browser** | `browser_agent_observe` | GEÇERLİ | `false` | 93699 | `{   "url": "https://en.wikipedia.org/wiki/Web_browser",   "title": "Web browser - Wikipedia",   "act` |
| **en.wikipedia.org/wiki/Web_browser** | `browser_agent_observe_diff` | GEÇERLİ | `false` | 249 | `{   "url": "https://en.wikipedia.org/wiki/Web_browser",   "title": "Web browser - Wikipedia",   "cha` |
| **en.wikipedia.org/wiki/Web_browser** | `browser_tabs` | GEÇERLİ | `false` | 1009 | `🟢 [0] Destination weddings in Zanzibar        http://127.0.0.1:3550/blog/f/destination-weddings-in-` |
| **en.wikipedia.org/wiki/Web_browser** | `browser_console` | GEÇERLİ | `false` | 61 | `=== Console ===   (empty) === Content (first 3000 chars) ===` |
| **en.wikipedia.org/wiki/Web_browser** | `browser_network` | GEÇERLİ | `false` | 6429 | `=== Network Requests ===   ✓ [200]      Image https://en.wikipedia.org/static/images/icons/enwiki-25` |
| **github.com/mehmetnadir/cdpilot** | `browser_navigate` | INVALID (isError=true (Error: Command timed out (30s))) | `true` | 0 | `Error: Command timed out (30s)` |
| **github.com/mehmetnadir/cdpilot** | `browser_content` | INVALID (<20 karakter (15c: "Skip to content")) | `false` | 0 | `Skip to content` |
| **github.com/mehmetnadir/cdpilot** | `browser_a11y` | GEÇERLİ | `false` | 119 | `Accessibility tree (6 visible nodes):   [RootWebArea]   [generic]   [generic]   [link]   [StaticText` |
| **github.com/mehmetnadir/cdpilot** | `browser_agent_observe` | GEÇERLİ | `false` | 471 | `{   "url": "https://github.com/mehmetnadir/cdpilot",   "title": "GitHub - mehmetnadir/cdpilot: Brows` |
| **github.com/mehmetnadir/cdpilot** | `browser_agent_observe_diff` | INVALID (Gezinmeyen (non-navigating) etkileşimli öğe bulunamadı) | `false` | 0 | `` |
| **github.com/mehmetnadir/cdpilot** | `browser_tabs` | GEÇERLİ | `false` | 1173 | `🟢 [0] After Party Venues in Turkey \| Wedding Venues Guide Turkey        http://127.0.0.1:3488/cate` |
| **github.com/mehmetnadir/cdpilot** | `browser_console` | GEÇERLİ | `false` | 77 | `=== Console ===   (empty) === Content (first 3000 chars) === Skip to content` |
| **github.com/mehmetnadir/cdpilot** | `browser_network` | GEÇERLİ | `false` | 6938 | `=== Network Requests ===   ✓ [200] Stylesheet https://github.githubassets.com/assets/light_high_cont` |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_navigate` | GEÇERLİ | `false` | 2925 | `Skip to main content Skip to search Web Web APIs MutationObserver MutationObserver Baseline WIDELY A` |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_content` | GEÇERLİ | `false` | 2925 | `Skip to main content Skip to search Web Web APIs MutationObserver MutationObserver Baseline WIDELY A` |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_a11y` | GEÇERLİ | `false` | 8180 | `Accessibility tree (566 visible nodes):   [RootWebArea]   [list]   [generic]   [banner]   [main]   [` |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_agent_observe` | GEÇERLİ | `false` | 14988 | `{   "url": "https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver",   "title": "Mutation` |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_agent_observe_diff` | GEÇERLİ | `false` | 283 | `{   "url": "https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver",   "title": "Mutation` |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_tabs` | GEÇERLİ | `false` | 912 | `🟢 [0] Destination weddings in Zanzibar        http://127.0.0.1:3551/blog/f/destination-weddings-in-` |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_console` | GEÇERLİ | `false` | 166 | `=== Console ===   ℹ️ [INFO] (Glean.core.Upload.PingUploadManager) Ping e8ff096e-4820-4709-964f-febc1` |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_network` | GEÇERLİ | `false` | 12009 | `=== Network Requests ===   ✓ [200]       Font https://developer.mozilla.org/static/client/jetbrains-` |
| **www.npmjs.com/package/cdpilot** | *(Tümü)* | BOT ENGELİ | — | — | Navigate çıktısında bot/turnstile/captcha tespit edildi. |
| **www.bbc.com/news** | `browser_navigate` | INVALID (isError=true (Error: Command timed out (30s))) | `true` | 0 | `Error: Command timed out (30s)` |
| **www.bbc.com/news** | `browser_content` | INVALID (Boş yanıt) | `false` | 0 | `(empty)` |
| **www.bbc.com/news** | `browser_a11y` | GEÇERLİ | `false` | 53 | `Accessibility tree (1 visible nodes):   [RootWebArea]` |
| **www.bbc.com/news** | `browser_agent_observe` | GEÇERLİ | `false` | 121 | `{   "url": "https://www.bbc.com/news",   "title": "bbc.com/news",   "actions": [],   "text": "",   "` |
| **www.bbc.com/news** | `browser_agent_observe_diff` | INVALID (Gezinmeyen (non-navigating) etkileşimli öğe bulunamadı) | `false` | 0 | `` |
| **www.bbc.com/news** | `browser_tabs` | GEÇERLİ | `false` | 751 | `🟢 [0] bbc.com/news        https://www.bbc.com/news   🟢 [1] MutationObserver - Web APIs \| MDN     ` |
| **www.bbc.com/news** | `browser_console` | GEÇERLİ | `false` | 3081 | `=== Console ===   ❌ [ERROR] NGAS load timeout === Content (first 3000 chars) === Skip to content US ` |
| **www.bbc.com/news** | `browser_network` | GEÇERLİ | `false` | 3548 | `=== Network Requests ===   ✓ [200]       Font https://static.files.bbci.co.uk/fonts/reith/2.512/BBCR` |

---

## 3. Geçerli Çıktıların Dönüştürülerek Ölçülen İsraf Payları

Yalnızca GEÇERLİ `browser_content`, `browser_a11y` ve `browser_agent_observe` çıktıları için metin bizzat dönüştürülüp hesaplanan kesin paylar:

| Sayfa | Araç | Boyut (Token) | (a) Boşluk Dizileri | (b) Yinelenen JSON Anahtarları | (c) URL'ler | (d) Yinelenen Satırlar |
|---|---|---|---|---|---|---|
| **news.ycombinator.com** | `browser_content` | 956 | 3.4% (33 t) | 0.0% (0 t) | 0.0% (0 t) | 0.0% (0 t) |
| **news.ycombinator.com** | `browser_a11y` | 5.597 | 14.4% (808 t) | 0.0% (0 t) | 0.0% (0 t) | 98.9% (5.538 t) |
| **news.ycombinator.com** | `browser_agent_observe` | 8.191 | 27.7% (2.272 t) | 21.2% (1.740 t) | 0.1% (7 t) | 43.4% (3.555 t) |
| **en.wikipedia.org/wiki/Web_browser** | `browser_content` | 5.056 | 0.5% (27 t) | 0.0% (0 t) | 0.1% (6 t) | 0.1% (7 t) |
| **en.wikipedia.org/wiki/Web_browser** | `browser_a11y` | 16.899 | 13.4% (2.272 t) | 0.0% (0 t) | 0.0% (0 t) | 99.3% (16.788 t) |
| **en.wikipedia.org/wiki/Web_browser** | `browser_agent_observe` | 23.425 | 26.8% (6.271 t) | 20.5% (4.810 t) | 0.1% (17 t) | 42.4% (9.944 t) |
| **github.com/mehmetnadir/cdpilot** | `browser_a11y` | 30 | 10.1% (3 t) | 0.0% (0 t) | 0.0% (0 t) | 10.1% (3 t) |
| **github.com/mehmetnadir/cdpilot** | `browser_agent_observe` | 118 | 8.1% (10 t) | 0.0% (0 t) | 8.1% (10 t) | 1.7% (2 t) |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_content` | 731 | 1.7% (13 t) | 0.0% (0 t) | 0.0% (0 t) | 3.6% (26 t) |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_a11y` | 2.045 | 13.8% (283 t) | 0.0% (0 t) | 0.0% (0 t) | 94.3% (1.929 t) |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | `browser_agent_observe` | 3.747 | 24.9% (931 t) | 18.8% (705 t) | 0.4% (16 t) | 37.5% (1.405 t) |
| **www.bbc.com/news** | `browser_a11y` | 13 | 3.8% (1 t) | 0.0% (0 t) | 0.0% (0 t) | 0.0% (0 t) |
| **www.bbc.com/news** | `browser_agent_observe` | 30 | 8.3% (3 t) | 0.0% (0 t) | 19.8% (6 t) | 0.0% (0 t) |

---

## 4. Ölçülen Tasarruflara Göre Sıralı Budama (Trim) Listesi

Aşağıdaki tasarruflar varsayım DEĞİL, yukarıdaki gerçek çıktılar üzerinde uygulanan dönüştürmelerin sayfa başına ortalama ve toplam ölçümüdür:

| Sıra | Budama Önerisi | Ölçülen Tasarruf | Risk Seviyesi | Doğrulama & Uygulama Notu |
|---|---|---|---|---|
| **1** | **`tools/list` Core Profil Zorunluluğu** | **5.874 token / tur (%79)** | **Sıfır** | Her model turunda sistem istemine giren 49 araçlık şema 11 araca indirilir. İstem boyutu anında küçülür. |
| **2** | **Yinelenen Satırların (Duplicated Lines) Temizlenmesi** | **Ortalama 3.015 token / sayfa (Toplam: 39.197 token)** | **Düşük** | Menü, telif, navigasyon ve liste tekrarlarından kaynaklanan özdeş satırlar filtrelenir. |
| **3** | **Ardışık Boşluk Dizilerinin (Whitespace Runs) Sıkıştırılması** | **Ortalama 994 token / sayfa (Toplam: 12.927 token)** | **Sıfır** | `browser_content` metin katmanındaki ve girintili JSON çıktılarındaki `\s{2,}` dizileri tek boşluğa indirgendiğinde anlamsal hiçbir kayıp olmadan ölçülen tasarruf sağlanır. |
| **4** | **Yinelenen JSON Anahtarlarının Sıkıştırılması / Tabüler Şema (`a11y` ve `observe`)** | **Ortalama 558 token / sayfa (Toplam: 7.255 token)** | **Düşük** | `browser_a11y` ve `browser_agent_observe` çıktılarındaki tekrarlanan `"role":`, `"name":`, `"ref":`, `"actions":` anahtarları tabüler dizi veya kompakt formata geçirilerek doğrudan bertaraf edilir. |
| **5** | **URL'lerin Göreliye Çevrilmesi veya İndekslenmesi** | **Ortalama 5 token / sayfa (Toplam: 62 token)** | **Düşük** | Sayfa içindeki mutlak URL (`https://...`) tekrarları göreli yola ya da referans indeksine çevrilir. |
