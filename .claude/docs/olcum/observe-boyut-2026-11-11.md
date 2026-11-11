> Şef notu 11.11: ölçüm agy-filo (gemini-3.8-flash) şeridinde koştu; ham veri depo dışında `~/01dev/cdpilot-olcum-ham/observe-boyut-2026-11-11/` (sonuc.jsonl). Şef sayıları ham veriden yeniden saydı.

# cdpilot 0.9.9 Planı Girdisi: `agent observe` Boyut ve Tüketim Ölçüm Raporu

Tarih: 11.11.2026. Makine: arm64. Tarayıcı: HeadlessChrome/152 (port 9333). Tokenizer: tiktoken `o200k_base`.

## 1. Sayfa Ölçüm Tablosu

| Sayfa | Durum | Varsayılan Token | Varsayılan Eylem | Varsayılan Bayt | --rows Token | --rows Eylem | --full Token | --full Eylem | --rows Tasarrufu |
|---|---|---|---|---|---|---|---|---|---|
| Wikipedia: Population (UN) | Ölçüldü | 17,629 | 1,108 | 61,015 B | 10,976 | 1,108 | 36,272 | 2,151 | %37.7 |
| Wikipedia: World War II | Ölçüldü | 69,931 | 4,043 | 223,893 B | 45,605 | 4,043 | 145,924 | 7,448 | %34.8 |
| MDN: HTML Element | Ölçüldü | 6,042 | 351 | 20,012 B | 3,961 | 354 | 21,563 | 869 | %34.4 |
| Python Docs: Functions | Ölçüldü | 9,849 | 589 | 33,115 B | 6,308 | 589 | 47,522 | 2,259 | %36.0 |
| GitHub: vscode | Ölçüldü | 6,092 | 316 | 21,323 B | 4,144 | 316 | 11,371 | 575 | %32.0 |
| GitHub: node/issues | Ölçüldü | 3,421 | 146 | 12,445 B | 2,542 | 146 | 6,952 | 299 | %25.7 |
| Hacker News: Front | Ölçüldü | 4,504 | 230 | 14,347 B | 3,090 | 230 | 7,170 | 346 | %31.4 |
| Hacker News: Item 50445401 | Ölçüldü | 21,139 | 1,326 | 65,933 B | 12,924 | 1,326 | 64,682 | 2,051 | %38.9 |
| BBC News | Ölçüldü | 3,626 | 136 | 14,714 B | 2,812 | 136 | 7,122 | 211 | %22.4 |
| npm: react | Atlandı (Cloudflare Turnstile/challenge bot koruması) | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi |
| StackOverflow: 11227809 | Ölçüldü | 19,978 | 1,147 | 67,252 B | 13,093 | 1,147 | 61,625 | 2,684 | %34.5 |
| Books to Scrape | Ölçüldü | 2,487 | 115 | 8,821 B | 1,796 | 115 | 3,367 | 163 | %27.8 |
| GNU Bash Manual | Atlandı (Sunucu yanıt vermiyor / zaman aşımı (gnu.org timeout >25s)) | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi |
| WHATWG: HTML Parsing | Ölçüldü | 84,923 | 5,111 | 300,755 B | 54,222 | 5,111 | 170,229 | 8,684 | %36.2 |
| The Guardian: Intl | Ölçüldü | 11,115 | 445 | 44,113 B | 8,441 | 445 | 18,437 | 721 | %24.1 |

## 2. En Büyük 3 Sayfanın Tüketim Dökümü

En yüksek `--full` token tüketen 3 sayfa listelenmiştir. Her sayfa için en çok token tüketen 5 rol ve metin özeti payı dökülmüştür.

### 2.1. WHATWG: HTML Parsing (`--full` toplam: 170,229 token)

URL: https://html.spec.whatwg.org/multipage/parsing.html

- Metin özeti (text alanı): 696 token (%0.41)

| Sıra | Rol | Eylem Adedi | Toplam Token | Pay (%) |
|---|---|---|---|---|
| 1 | `link` | 4,670 | 79,958 | %46.97 |
| 2 | `StaticText` | 2,976 | 70,785 | %41.58 |
| 3 | `cell` | 439 | 11,159 | %6.56 |
| 4 | `term` | 410 | 9,952 | %5.85 |
| 5 | `heading` | 140 | 3,872 | %2.27 |

### 2.2. Wikipedia: World War II (`--full` toplam: 145,924 token)

URL: https://en.wikipedia.org/wiki/World_War_II

- Metin özeti (text alanı): 495 token (%0.34)

| Sıra | Rol | Eylem Adedi | Toplam Token | Pay (%) |
|---|---|---|---|---|
| 1 | `link` | 3,980 | 72,238 | %49.50 |
| 2 | `StaticText` | 2,916 | 68,989 | %47.28 |
| 3 | `ListMarker` | 463 | 7,871 | %5.39 |
| 4 | `region` | 38 | 752 | %0.52 |
| 5 | `cell` | 7 | 297 | %0.20 |

### 2.3. Hacker News: Item 50445401 (`--full` toplam: 64,682 token)

URL: https://news.ycombinator.com/item?id=50445401

- Metin özeti (text alanı): 434 token (%0.67)

| Sıra | Rol | Eylem Adedi | Toplam Token | Pay (%) |
|---|---|---|---|---|
| 1 | `cell` | 254 | 22,329 | %34.52 |
| 2 | `link` | 1,323 | 21,932 | %33.91 |
| 3 | `StaticText` | 464 | 21,653 | %33.48 |
| 4 | `LayoutTableCell` | 7 | 244 | %0.38 |
| 5 | `textbox` | 2 | 30 | %0.05 |

## 3. İlk K Eylem Eğrisi Tablosu (Varsayılan Kip)

Varsayılan observe çıktısında eylemler sıra ile tutulmuştur. K=25, 50, 100, 200 için payload token değerleri hesaplanmıştır.

| Sayfa | Toplam Eylem | K=25 Token | K=50 Token | K=100 Token | K=200 Token | Tam Varsayılan Token | K=50 Tasarrufu |
|---|---|---|---|---|---|---|---|
| Wikipedia: Population (UN) | 1,108 | 838 | 1,227 | 2,107 | 3,592 | 17,629 | %93.0 |
| Wikipedia: World War II | 4,043 | 878 | 1,281 | 2,222 | 3,922 | 69,931 | %98.2 |
| MDN: HTML Element | 351 | 779 | 1,160 | 1,972 | 3,584 | 6,042 | %80.8 |
| Python Docs: Functions | 589 | 889 | 1,291 | 2,122 | 3,711 | 9,849 | %86.9 |
| GitHub: vscode | 316 | 793 | 1,207 | 2,039 | 3,857 | 6,092 | %80.2 |
| GitHub: node/issues | 146 | 933 | 1,334 | 2,371 | 3,392 | 3,421 | %61.0 |
| Hacker News: Front | 230 | 1,125 | 1,549 | 2,394 | 4,029 | 4,504 | %65.6 |
| Hacker News: Item 50445401 | 1,326 | 814 | 1,267 | 2,090 | 3,621 | 21,139 | %94.0 |
| BBC News | 136 | 870 | 1,607 | 2,664 | 3,585 | 3,626 | %55.7 |
| npm: react | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi |
| StackOverflow: 11227809 | 1,147 | 936 | 1,351 | 2,295 | 3,812 | 19,978 | %93.2 |
| Books to Scrape | 115 | 906 | 1,277 | 2,216 | 2,456 | 2,487 | %48.7 |
| GNU Bash Manual | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi | ölçülmedi |
| WHATWG: HTML Parsing | 5,111 | 1,309 | 1,978 | 3,301 | 5,415 | 84,923 | %97.7 |
| The Guardian: Intl | 445 | 744 | 1,141 | 1,879 | 4,645 | 11,115 | %89.7 |

## 4. Sistem Yükü

`sysctl -n vm.loadavg` çıktısı:

```text
{ 56.68 36.18 32.15 }
```
