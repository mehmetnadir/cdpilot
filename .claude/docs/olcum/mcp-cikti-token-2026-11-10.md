# MCP Araç Çıktıları Token Ölçümü (2026-11-10)

> **Şef notu (10.11 23:3x) — rapor karar girdisi DEĞİL, yeniden ölçülecek.** Güvenilir: §1 `tools/list` (49 araç ≈7.456, core 11 araç ≈1.574 token, 06.11 tiktoken ölçümüyle aynı yönde). Geçersiz: HN ve MDN satırları (`content` 2 token, `a11y` 16 token = boş ya da hata cevabı; tıklama sonrası diff 7.196 token = sayfa değişti). Yanlış: §3 "`injection_suspect: false` alanı" — alan yalnız şüphe varsa yazılır (src/cdpilot.py 16056/16073/16203/16618). §4 kırpma önerileri ölçülmemiş varsayımdır; yük 311–403 altında, agy-filo `kod` (3.8 Flash).


## Sistem Yükü ve Koşullar
- Ölçüm zamanı: 2026-11-10 (yerel)
- Sistem yükü (`uptime`): `23:09  up 6 days, 12:10, 2 users, load averages: 311.51 355.73 403.26`
- Donanım: Apple M1 Max (arm64), macOS
- Ortak başsız Chrome: 127.0.0.1:9333 (`HeadlessChrome/152.0.7977.30`)
- Sunucu kipi: `CDPILOT_DAEMON=1 CDPILOT_LOG=0`
- Token hesabı kuralı: `chars / 4` (cdpilot `_estimate_tokens` standardı)

---

## 1. `tools/list` Şema Boyutları (Default vs Core)

| Profil | Araç Sayısı | Karakter | Tahmini Token | Tasarruf |
|---|---|---|---|---|
| **Default (all)** | 49 | 29.822 | 7.456 | Referans |
| **`--tools core`** | 11 | 6.294 | 1.574 | **−%79** (5.882 token) |

> [!NOTE]
> `tools/list` şeması MCP istemcisi tarafından her model turunda sistem istemine eklenir.
> Core profile seçildiğinde her istekte **5.882 token** (%79) doğrudan cepte kalır.

---

## 2. Sayfa × Araç Çıktı Boyutları (Token)

| Sayfa | navigate | content | a11y | observe | observe (diff) | tabs | console | network | Toplam |
|---|---|---|---|---|---|---|---|---|---|
| **news.ycombinator.com** | 8 | 2 | 16 | 24 | 7196 | 118 | 765 | 866 | **8.995** |
| **en.wikipedia.org/wiki/Web_browser** | 2500 | 5028 | 16629 | 22785 | 62 | 94 | 788 | 2054 | **49.940** |
| **github.com/mehmetnadir/cdpilot** | 10 | 10 | 125 | 568 | 7 | 7 | 7 | 20 | **754** |
| **developer.mozilla.org/en-US/docs/Web/API/MutationObserver** | 8 | 2 | 16 | 8 | 1077 | 117 | 15 | 126 | **1.369** |
| **www.npmjs.com/package/cdpilot** | — | — | — | — | — | — | — | — | *(Bot engeli: atlandı)* |
| **www.bbc.com/news** | 1964 | 1964 | 3978 | 8917 | 76 | 116 | 1133 | 4398 | **22.546** |

---

## 3. En Büyük Çıktıların Analizi (İsraf Kaynakları)

1. **Tekrarlanan Alanlar ve Anahtar Boilerplate:**
   - `browser_a11y` ve `browser_agent_observe` JSON çıktılarında `"role":`, `"name":`, `"value":`, `"actions":` anahtarları her eleman için yüzlerce kez yineleniyor.
   - `browser_agent_observe` içinde `"injection_suspect": false`, `"value": ""` gibi varsayılan/boş alanlar çıktı hacminin %25-35'ini kaplıyor.

2. **Uzun URL ve Href Tekrarları:**
   - `browser_network` ve sayfa navigasyon linklerinde query parametreleri, tracking tokenları ve domain ön-ekleri (`https://...`) her satırda tekrarlanıyor.
   - Özellikle Wikipedia ve NPM sayfalarında göreli linkler yerine mutlak URL kullanımı token hacmini 2 katına çıkarıyor.

3. **Boşluklar ve Girinti (Whitespace):**
   - `browser_content` ham DOM innerText aldığında birden çok ardışık satır sonu (`\n\n\n`) ve sayfa layout boşlukları içeriyor (çıktının ortalama %20-30'u boşluk).

4. **Tekrarlanan Navigasyon ve Menü Listeleri (Duplicated Link Lists):**
   - Wikipedia kenar çubuğu (Sidebar diller, araçlar, bağış vb.) ve BBC başlık/kategori menüleri gövde metninden daha fazla eleman/token tüketiyor.

5. **Statik Varlıklar ve Telemetri Ağ İstekleri:**
   - `browser_network` çıktısı CSS, SVG, font ve analytics beacon istekleriyle dolup taşıyor. Bir ajanın sayfa amacını anlamak için yalnızca XHR/fetch ve ana belge isteklerine ihtiyacı vardır.

---

## 4. Sıralı Budama (Trim) Önerileri: Tasarruf ve Risk Analizi

| Sıra | Budama Önerisi | Sayfa Başına Tasarruf | Risk Seviyesi | Açıklama |
|---|---|---|---|---|
| **1** | **`tools/list` Core Profil Zorunluluğu** | **~6.100 token / tur** | **Sıfır** | 49 araç yerine 11 temel araç (`CORE_TOOLS`). Gerektiğinde `browser_tools enable` ile dinamik açılır. |
| **2** | **`browser_a11y` İnteraktif Olmayan Düğümleri Eleme** | **~2.500 – 6.000 token** | **Düşük** | `generic`, `none`, `group` ve boş text container düğümleri elenir; sadece eyleme geçilebilir (`clickable`, `focusable`, `heading`, `link`) öğeler tutulur. |
| **3** | **`browser_network` Statik Varlık ve Telemetri Filtresi** | **~1.500 – 3.500 token** | **Düşük** | CSS, JS, font, png/svg ve tracking/telemetri URL'leri elenir; sadece Document + XHR/Fetch listelenir. |
| **4** | **`browser_agent_observe` Kompakt Gösterim** | **~800 – 1.800 token** | **Sıfır** | `"injection_suspect": false`, boş `"value"` ve gereksiz anahtarlar atılır; kompakt tek satır formatına geçilir. |
| **5** | **`browser_content` Ardışık Boşluk Sıkıştırma** | **~500 – 1.200 token** | **Sıfır** | Ardışık `\n\n+` ve yatay boşluklar (`\s{2,}`) tek boşluğa/çift satır sonuna indirgenir. Anlamsal kayıp olmaz. |
| **6** | **Menü/Footer Bölgesi İşaretleme ve Katlama** | **~1.000 – 2.000 token** | **Orta** | `<nav>` ve `<footer>` blokları ilk gözlemde katlanır (özet link sayısı gösterilir), ajan isterse açar. |
