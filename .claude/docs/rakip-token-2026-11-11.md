# Rakip token tekniği taraması — 11.11.2026

Amaç: cdpilot 0.9.9 planı için rakiplerin bugünkü teknikleri ve yayımlanmış sayıları.
Yöntem: web araması + resmi README/CHANGELOG/doküman okuma. Erişim tarihi hepsi 11.11.2026.
Not: Ben kaynakları okudum; hiçbir ölçümü yeniden üretmedim. "Satıcı" = aracın kendi sahibinin sayısı.

## 1. Özet tablo

| Araç | Sayfa temsili | Token tekniği | Yayımlanmış sayı | Son sürüm / tarih |
|---|---|---|---|---|
| Playwright MCP + `playwright-cli` (Microsoft) | a11y snapshot (YAML), ref'li; `ariaSnapshotJSON` (1.63) | `depth`, tek eleman `target`, `filename` ile dosyaya yaz, `browser_find`, `--snapshot-mode none`, `--image-responses omit`, CLI+SKILLS | Satıcı/ikincil: tipik görev MCP ~114.000, CLI ~27.000 token (TinyFish aktarımı; README'de sayı YOK, yalnız "daha verimli"). Doğrulanamadı. | Playwright 1.65 (en son); WebMCP varsayılan 1.64. Tarih: sayfada yok |
| Chrome DevTools MCP (Google) | metin a11y snapshot, uid'li | `--slim` (3 araç: navigate, evaluate, screenshot), metin snapshot'tan gürültü atma (1.11), `data:` URL kesme (1.12), snapshot bekleme sınırı | Slim ~368 token (üçüncü taraf proxy README'si); tam set 4.475–18.000 token (kaynaklar çelişiyor); tek `take_snapshot` uzun makalede ~10.220 token (üçüncü taraf, sürüm 1.6.0) | 1.12.0, 22.10.2026 |
| Vercel agent-browser | kompakt metin + `@eN` ref; `snapshot -i` | `snapshot --delta` (0.38.0), `diff snapshot --baseline`, `batch --omit-command` (0.40.0), oturum başına daemon | Satıcı: metin çıktısı ~200–400 token, tam DOM ~3.000–5.000 (agent-browser.dev). Bağımsız: web-agent-bench, ince API döngüsünde ~2,7k token/adım, Claude Code kabuğunda ~35k/adım (Sonnet 4.6, ~300 görev) | CHANGELOG'da 0.42.0 görünüyor; tarih yok |
| browser-use | 1.0.0'da DOM serileştirici kaldırıldı; ajan CDP'ye Python yazar | bağlam penceresi aşınca tek sıkıştırma, `max_steps` 500 → 100, `cost_usd` takibi | Bağımsız (WindTunnel 18.10.2026): eski DOM+ekran görüntüsü kurulumu Stagehand a11y'ye göre ~13× token, ~11× maliyet. Tek koşu, doğrulanamadı | 1.0.1, 10.11.2026 |
| Stagehand / Browserbase | a11y ağacı + LLM `act/observe/extract` | Eylem önbelleği: çözülmüş seçici saklanır; anahtar = yöntem + URL + DOM özeti + proje. Sayfa kayarsa kaçırma, LLM çalışır, yeni kayıt yazılır | Satıcı: ilk koşudan ikinciye en çok ~%80 hız artışı; kayıt 48 saat; token/maliyet sayısı yok (browserbase.com/blog, 24.02.2026) | v3 (otomatik önbellek); v4 önbellek 21.08.2026 (ikincil kaynak, doğrulanamadı) |
| Anthropic browser tool (API) | `read_page` ağaç (ref'li), `find`, `get_page_text`, `screenshot`, `zoom` | Önce ağaç, sonra ekran görüntüsü; `filter:"interactive"`, `ref` ile alt ağaç, `depth` varsayılan 15, 50.000 karakterde kes; çağrıları toplu ver, sonda tek gözlem; sekme bağlamı tekilleştirilir; `defer_loading` | Resmi doküman: bir ekran görüntüsü ~1.000–1.800 token (computer use dokümanı). Araç seti şeması ~6.600 token/istek (üçüncü taraf özet, resmî sayfada bu sayı okunamadı) | `browser_toolset_20260801`, kararlı; sürüm kimliği 01.08.2026, GA 19.08.2026 (ikincil) |
| OpenAI Atlas ajan modu | ARIA etiketleri + sayfa (kamuya açık bilgi sınırlı) | Resmî teknik belge bulunamadı | Yok | Doğrulanamadı |
| Steel | Tarayıcı altyapısı + CLI (`open/snapshot/fill/click`) | Kendi ajan döngüsü yok; token tekniği belgelenmemiş | Yok | CLI v0.2.0, 03.2026 (ikincil) |
| Skyvern | HTML ile LLM çağrısı | JSON yerine HTML: %11 az token, %3,9 başarı artışı; RAG'ı silme: süre 593 → 262 sn, maliyet $0,039 → $0,0302, önbellekli token %70 indirimli | Satıcı blogu, tarih görünmüyor | Haziran 2026 changelog |
| Opera Browser CLI (yeni) | AXI tabanlı "Compact" snapshot | Ref yeniden yazımı (nokta, alt çizgi yok), rol kısaltma, örtük ARIA niteliklerini atma, boş düğüm atma, başlıkları Markdown yapma, aynı kökenli URL'yi yola indirme, URL arama tablosu, tekrar eden kalıbı tekilleştirme | Satıcı: eski ham çıktıya göre ~%66, ham MCP tabanına göre ~%80 az girdi token'ı. Koşul: yalnız doküman sayfaları; uygulama arayüzünde farklı olabilir | 01.07.2026 |
| WebMCP (W3C taslak, Chrome) | Site araç sunar, sayfa okuma gerekmez | `navigator.modelContext` ile site tool kaydeder | WindTunnel 18.10.2026 (49 görev, 8 site, 2.793 koşu, ~$173): WebMCP medyan ~2.500–9.800 token; kod yürütme ~10.500–11.000; sayfa yapısı ~13.900 (tek model, başarı %52); bilgisayar kullanımı ~20.600–47.100. Başarı: WebMCP %96–100, bilgisayar kullanımı %84–95 | Chrome'da bayrak/önizleme; ikincil kaynaklar: Mayıs 2026'da ana ajanların çoğu çağırmıyor |

Pazarlama ve bağımsız ayrımı: web-agent-bench (topluluk) ve WindTunnel (nekuda, Hugging Face sayfası) bağımsız sayılır, ama ikisi de tek koşu ve ayrıntısı eksik. Ötekiler satıcı sayısıdır.

Çelişki: Playwright MCP için üçüncü taraf bir Mintlify sayfası "incremental mod varsayılan" diyor. Resmî README yalnız `full`/`none` modunu gösteriyor. Resmî kaynak doğru kabul edildi; incremental iddiası doğrulanamadı.

## 2. cdpilot'ta yok, uygulanabilir (en çok 6)

| # | Madde | Beklenen etki | Kanıt | Zorluk | Risk |
|---|---|---|---|---|---|
| 1 | WebMCP köprüsü: sayfanın kaydettiği araçları listele/çağır (`webmcp-list`, `webmcp-call` benzeri) | Site araç sunarsa sayfa okumadan iş biter. WindTunnel'da medyan token ~2.500–9.800 (sayfa yapısı kolunda ~13.900). Kendi ölçümümüz: yok | Playwright 1.64 (`webmcp_<tool>`, `--no-webmcp`); Chrome DevTools MCP 1.11 (`execute_webmcp_tool`); WindTunnel sayfası | M | Benimseme düşük (çok az site). API adı çelişkili (`navigator` / `document.modelContext`). Siteden gelen araç açıklaması = enjeksiyon yüzeyi; `injection_suspect` ile süzülmeli |
| 2 | Snapshot sıkıştırma turu (Opera kalıbı): örtük ARIA niteliği atma, boş düğüm atma, aynı kökenli URL'yi yola indirme, URL tablosu, tekrar eden kalıbı tekilleştirme | Opera: ince çıktıdan sonra bile ek ~%66 az girdi token'ı (satıcı, yalnız doküman sayfaları). Bizde: ölçülmedi | operaneon.com 01.07.2026; Chrome DevTools MCP 1.11/1.12 aynı yönde (StaticText gürültüsü, `data:` URL kesme) | S–M | Rol/ad kısaltması ref çözümünü bozabilir; `agent flow` çapaları (rol+ad+sıra) etkilenir, önce çapa testi |
| 3 | Derinlik ve alt ağaç sınırı + "kesildi" notu: `observe --depth N`, `--ref @eN` kapsamı, sert üst sınır | Dev sayfada tek gözlem patlamasını keser. Bizde: ölçülmedi | Anthropic: `depth` varsayılan 15, 50.000 karakter sınırı, kesinti metinde belirtilir; Playwright: `depth`, `target`; `ariaSnapshotJSON` `depth` alır | S | Sınır önemli öğeyi keser; modele "kesildi, daralt" ipucu şart |
| 4 | Sorgu aracı: `agent find "<metin/rol>"`, en çok 20 eşleşme, tam snapshot almadan ref döner | Eylemden önce tam ağaç okumayı önler. Ölçülmedi | Playwright `browser_find` ("tam snapshot'tan ucuz"); Anthropic `find` (en çok 20) | S | Bizde `click --text` gibi akıllı komutlar var; çakışma olabilir, önce örtüşmeyi kontrol et |
| 5 | Toplu komut + tek gözlem: `batch` (ara çıktısız, `--omit-command`) ve MCP batch aracı | Tur sayısını düşürür; her tur bağlamı yeniden yükler. Ölçülmedi | agent-browser 0.40.0 `batch --omit-command`; Anthropic: "çağrıları toplu ver, sonda tek gözlem" | M | Ara adım hata verirse kalan adımları durdurma kuralı gerekir; kısmi başarı bildirimi |
| 6 | Görüntü bütçesi: ekran görüntüsünü yeniden boyutla, WebP, `zoom`/kırpma ve "görüntü yanıtını at" seçeneği | Görüntü başına ~1.000–1.800 token (resmî); küçültme doğrudan düşürür. Ölçülmedi | Anthropic: API görüntüyü küçültmez, istemci boyutlar; Playwright 1.62 WebP, `--image-responses omit`; Chrome DevTools MCP 1.12 slim ekran görüntüsü dosya yolu | S | Küçük metin okunmaz hale gelir; `zoom` yedeği şart. Bizde element kırpma var (`browser-automation` skill'ine göre); mevcut kapsam doğrulanmalı |

Elenenler: `snapshot --delta` / diff (bizde var), araç şeması küçültme (bizde var), dosyaya yazıp yol dönme (Playwright CLI). Sonuncusu bağlamdan çıkarır ama model dosyayı okuyunca token yine gider; net etki ölçülmedi, madde yapılmadı.

## 3. Bizde var, onlarda yok

| Özellik | Durum | Kanıt |
|---|---|---|
| `injection_suspect` işareti | Taranan README, changelog ve dokümanlarda benzer bir işaret görmedim. Yokluğu kanıtlanmış değil; Atlas için yalnız "hassas sayfada duraklar" bilgisi var | Atlas: Simon Willison, Adrian Roselli aktarımı (ikincil) |
| Çok adımlı akışı kaydetme + modelsiz tekrar, sapmada çıkış kodu 4 | Stagehand de eylem düzeyinde önbellek yapıyor (tek eylem seçici). Fark: bizde akış bütün, sapmada kendiliğinden LLM'e düşmek yok. "Onlarda yok" demiyorum; Stagehand'in tek-eylem önbelleği var | browserbase.com/blog/stagehand-caching |
| Sayı: HN 18.331 → 90, Wikipedia 15.474 → 136 token | Kendi gerçek-site ölçümümüz; rakiplerde karşılaştırılabilir yayımlanmış akış sayısı bulamadım (yalnız Stagehand %80 hız) | `/Users/nadir/01dev/cdpilot/CHANGELOG.md` |

Bizde olup rakipte de olanlar (yenilik değil): diff/delta (agent-browser 0.38.0), araç alt kümesi (Chrome slim, Anthropic `defer_loading`), sıcak süreç (agent-browser oturum daemon'u, Playwright MCP kalıcı durum).

## 4. Kaynaklar (erişim 11.11.2026)

- Playwright MCP README: https://github.com/microsoft/playwright-mcp
- Playwright sürüm notları (1.59–1.65): https://raw.githubusercontent.com/microsoft/playwright/main/docs/src/release-notes-js.md
- Playwright CLI vs MCP, 114k/27k aktarımı (ikincil): https://current.tinyfish.ai/tinyfish/issue/latest/foundations/article/24492
- Chrome DevTools MCP CHANGELOG: https://raw.githubusercontent.com/ChromeDevTools/chrome-devtools-mcp/main/CHANGELOG.md
- Chrome DevTools MCP 0.18.0 (`--slim`, 24.02.2026): https://newreleases.io/project/github/ChromeDevTools/chrome-devtools-mcp/release/chrome-devtools-mcp-v0.18.0
- agent-browser README: https://github.com/vercel-labs/agent-browser
- agent-browser CHANGELOG: https://raw.githubusercontent.com/vercel-labs/agent-browser/main/CHANGELOG.md
- agent-browser sitesi (200–400 token iddiası): https://agent-browser.dev/
- web-agent-bench (bağımsız): https://github.com/nsosio/web-agent-bench
- WindTunnel sonuçları (18.10.2026): https://nekuda-windtunnel-results-explorer.static.hf.space/index.html
- browser-use sürümleri: https://github.com/browser-use/browser-use/releases
- Stagehand önbellek blogu (24.02.2026): https://browserbase.com/blog/stagehand-caching
- Stagehand v3 önbellek dokümanı: https://docs.stagehand.dev/v3/best-practices/caching
- Anthropic browser tool dokümanı: https://platform.claude.com/docs/en/agents-and-tools/tool-use/browser-tool
- Anthropic araç seti token yükü (üçüncü taraf özet): https://ecorpit.com/claude-browser-use-toolset-token-overhead-docs-conflict-2026/
- Opera Browser CLI Compact snapshot (01.07.2026): https://operaneon.com/news/token-efficient-browser-snapshots-for-opera-browser-cli
- Opera, ">100k token snapshot" yazısı (28.07.2026): https://www.opera.com/ai/articles/how-many-tokens-is-your-browser-agent-burning
- WebMCP durum özeti: https://web-platform-dx.github.io/web-features-explorer/features/navigator-modelcontext
- Atlas ve ARIA: https://simonwillison.net/2025/Oct/21/introducing-chatgpt-atlas/ , https://adrianroselli.com/2025/10/openai-aria-and-seo-making-the-web-worse.html
- Skyvern: https://www.skyvern.com/blog/deleting-rag-from-our-web-agent-made-it-2-3x-faster/
- Steel CLI: https://steel.dev/blog/steel-cli-and-agent-skill

## Doğrulanamayanlar

- Playwright 114k → 27k token: yalnız ikincil kaynak, README'de sayı yok.
- Playwright MCP "incremental mod": resmî README ile çelişiyor.
- Anthropic araç seti ~6.600 token yükü: resmî sayfanın okunan kısmında yok.
- Stagehand v4 önbellek (21.08.2026): yalnız ikincil kaynak.
- Atlas sayfa okuma hattı: resmî teknik belge bulunamadı.
- Chrome DevTools MCP tam set token yükü: kaynaklar 4.475 ile ~18.000 arasında çelişiyor.
- agent-browser, Playwright, Anthropic sürüm tarihleri: bazı sayfalarda tarih yok; yalnız yazılanlar aktarıldı.

## Şef düzeltmesi (11.11 05:52)

Araştırma ajanı cdpilot'un var olan üç özelliğini görmedi. Öneri listesi aşağıdaki gibi düzeltilir.

| # | Öneri | Bizdeki durum | Kalan iş |
|---|---|---|---|
| 1 | WebMCP köprüsü | VAR, 0.9.4'ten beri: `cdpilot tools list / call`, `launch --webmcp` (README "WebMCP tools (opt-in)") | Araç açıklamaları `injection_suspect` taramasından geçiyor mu ölç; MCP tarafında araç adlandırması rakiplerle kıyasla |
| 4 | Sorgu aracı (`find`) | KISMEN: `a11y find <role>` yalnız role göre | Ajan kipinde metin + rol sorgusu, ≤ 20 eşleşme, @ref döner |
| 5 | Toplu komut | KISMEN: `cdpilot batch` (stdin JSON dizisi) | MCP batch aracı yok; ajan kipinde "N eylem, tek gözlem" yok |

Gerçekten yeni olanlar: 2 (snapshot sıkıştırma), 3 (derinlik/alt ağaç sınırı + "kesildi" notu), 6 (görüntü bütçesi).
0.9.9 aday sırası (şef): 3 → 4 → 2. Her biri önce ölçüm (gerçek site o200k, çapa kaybı 0), sonra jüri §8.
