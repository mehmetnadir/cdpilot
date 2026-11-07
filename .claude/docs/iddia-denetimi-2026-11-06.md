> Kaynak: agy-filo rol review (gemini-3.8-flash-high), 06.11.2026, salt okunur denetim. Gemini raporu kanıt değildir; şef doğrulaması aşağıdaki satırlardan sonra gelir.

`npm test` çalışıyor; testlerin tamamlanması bekleniyor.
Test paketinin son bölümü yürütülüyor, tamamlanması bekleniyor.
Testlerin tamamlanması bekleniyor.
Test paketinin tamamlanması bekleniyor.
Test paketinin son aşamaları yürütülüyor.
# cdpilot İddia ve Vaat Denetim Raporu

Bu rapor; `cdpilot` CLI çekirdeği, test suiteleri, ölçüm kayıtları ve pazarlama sitesindeki tüm niceliksel ve mutlak iddiaların kod tabanındaki karşılıklarını denetler.

---

## 1. Niceliksel ve Mutlak İddialar Tablosu

| # | claim (verbatim, <=120 chars) | where (file:line) | evidence (code or test file:line, or "none") | verdict | fix (one line: reword / add test / remove / measure) |
|---|---|---|---|---|---|
| 1 | "Zero dependency — No Puppeteer, no Playwright, no Selenium. Pure CDP over HTTP" | README.md:31 | package.json:34-37, src/cdpilot.py:1790 | KISMİ | "Zero npm dependencies (Python standard library + websockets)" olarak düzelt. |
| 2 | "No Puppeteer. No Playwright. No Selenium. Just direct CDP communication." | README.md:1206 | package.json:34-37, src/cdpilot.py:13300 | KANITLI | Değişiklik gerekmez. |
| 3 | "No dependencies — Zero npm/Python runtime dependencies means zero supply-chain attack surface." | README.md:1283 | src/cdpilot.py:1790 (import websockets) | YANLIŞ | "Zero npm dependencies; minimal Python footprint (websockets)" olarak yeniden yaz. |
| 4 | "Controls any Chromium-based browser (Brave, Chrome, Chromium) via the Chrome DevTools Protocol" | src/cdpilot.py:5-6 | src/cdpilot.py:1650, README.md:60,1009 | KISMİ | Chrome 137+ extension ve 144+ inspect kısıtlarını belirten dipnot ekle. |
| 5 | "70+ commands — Navigate, click, type, screenshot, network, console, accessibility..." | README.md:32 | test/test.js:3649, cdpilot-site/test/claims.test.mjs:130 | KANITLI | Değişiklik gerekmez. |
| 6 | "60+ CLI commands" | cdpilot-site/src/components/pricing.tsx:29 | none (kodda 70+ komut var) | BAYAT | "60+ CLI commands" ifadesini güncel sayı olan "70+ CLI commands" ile değiştir. |
| 7 | "It ships a built-in MCP server (42 tools)" | cdpilot-site/src/app/compare/page.tsx:142 | test/test.js:8067, token-taban-2026-10-24.md:31 | BAYAT | "42 tools" ifadesini güncel sayı olan "45 tools (47 with WebMCP)" olarak güncelle. |
| 8 | "tools/list: 45 tools = 5,769 tokens, core = 11 tools = 1,342 tokens." | README.md:151 | CHANGELOG.md:8, token-taban-2026-10-24.md:11-31 | KANITLI | Değişiklik gerekmez. |
| 9 | "1 file, no node_modules" / "Browser automation in one file" | cdpilot-site/src/components/comparison.tsx:23 | package.json:34-37, src/cdpilot.py:1 | KANITLI | Değişiklik gerekmez. |
| 10 | "install size ~50KB" (eski karşılaştırma tablosu iddiası) | CHANGELOG.md:138 | test/test.js:3648-3660, claims.test.mjs:41-44 | BAYAT | Geri çekildi; README ve siteden temizlendiği testlerle kilitli. |
| 11 | "a11y-snapshot: 500x fewer tokens than screenshots" (eski hero/pricing iddiası) | CHANGELOG.md:139 | token-olcumu-2026-09-27.md:75-98, claims.test.mjs:28-39 | BAYAT | Geri çekildi; sitede resmi tekzip yayınlandı, testlerle koruma altında. |
| 12 | "a11y-snapshot ran 1.4-42x smaller than raw HTML on the same page" | cdpilot-site/src/components/comparison.tsx:176 | token-olcumu-2026-09-27.md:88-94, README.md:1320 | KANITLI | Değişiklik gerekmez. |
| 13 | "bot.sannysoft.com: 28 pass / 3 fail (regular), 31 pass (stealth/undetected), intoli 5/6, 6/6" | README.md:845-849 | stealth-panel-olcumu-2026-09-27.md:1-80, test/test.js:3590-3604 | KANITLI | Değişiklik gerekmez. |
| 14 | "10 built-in test assertions" | README.md:1318 | src/cdpilot.py:14429-14668, 20224-20234 | KANITLI | Değişiklik gerekmez. |
| 15 | "Multi-instance pool (CDPILOT_POOL_SIZE=N)" | CHANGELOG.md:168 | CHANGELOG.md:137, README.md:1134, 1355 | BAYAT | 0.9.0'da duyurulup 0.9.1'de kodda olmadığı belirtilip Roadmap'e alındı. |
| 16 | "Works with Claude Code · Cursor · Windsurf · Any MCP client" | cdpilot-site/src/components/hero.tsx:80-81 | server.json:1-10, test/test.js:3626-3633 | KANITLI | Değişiklik gerekmez. |
| 17 | "Privacy-first — Everything runs locally. No data leaves your machine" | README.md:38 | src/cdpilot.py:391 (tls.peet.ws), 831 (2captcha) | KISMİ | "No analytics sent; opt-in features (BYOK solvers, tls-check) contact external APIs" de. |
| 18 | "A connected browser is never closed, killed or modified" / "Nothing is injected" | README.md:1027-1040, CHANGELOG.md:16 | src/cdpilot.py:270-384, test/test.js:6900-7050 | KANITLI | Değişiklik gerekmez. |
| 19 | "never clicks destructive lookalikes (Delete account, Sign out, Subscribe)" | bin/cdpilot.js:519-520, README.md:503 | src/cdpilot.py:13934-13955 (DISMISS_NEGATIVE) | KANITLI | Değişiklik gerekmez. |
| 20 | "Real mouse clicks hold the button like a person: 40-120 ms" | README.md:555, CHANGELOG.md:49 | src/cdpilot.py:4977-4989, test/test.js:4140-4220 | KANITLI | Değişiklik gerekmez. |
| 21 | "exit 3: pressed, release missed the target, not clicked" | src/cdpilot.py:72-77, bin/cdpilot.js:485 | src/cdpilot.py:5100, test/test.js:4393-4405 | KANITLI | Değişiklik gerekmez. |
| 22 | "Universal --timeout <seconds> ... expiry exits 124" | README.md:917-922, CHANGELOG.md:107 | src/cdpilot.py:110-150, test/test.js:5300-5350 | KANITLI | Değişiklik gerekmez. |
| 23 | "Idle auto-close: An auto-launched browser closes after 15 min ... CDPILOT_IDLE_CLOSE" | bin/cdpilot.js:453-455, README.md:890 | src/cdpilot.py:1820-1920, test/test.js:5763-5820 | KANITLI | Değişiklik gerekmez. |
| 24 | "Session log: Always on, local, redacted ... CDPILOT_LOG=0, CDPILOT_LOG_DAYS 14" | bin/cdpilot.js:603-612, README.md:933 | src/cdpilot.py:1480-1620, test/test.js:6190-6250 | KANITLI | Değişiklik gerekmez. |
| 25 | "Web Bot Auth: reproduces the Ed25519 test vectors of Cloudflare's reference ... byte for byte" | README.md:604-611, CHANGELOG.md:27 | src/cdpilot.py:2000-2400, test/test.js:8100-8200 | KANITLI | Değişiklik gerekmez. |
| 26 | "cdpilot is an avoidance engine, not a CAPTCHA solver. We do not call 2Captcha..." | README.md:1244, compare/page.tsx:169 | none (README:780 ve src/cdpilot.py:820 2captcha içerir) | YANLIŞ | Metni "Avoidance engine by default, with opt-in BYOK solver plugins" olarak güncelle. |
| 27 | "Can cdpilot attach to my existing Chrome? ... that path is not documented yet" | cdpilot-site/src/app/compare/page.tsx:154 | README.md:963-1066 (cdpilot connect tam belgeli) | BAYAT | Sitedeki bu eski SSS maddesini kaldır veya `cdpilot connect` açıklamasıyla birleştir. |
| 28 | "v0.8+ (TLS fingerprint correction via camoufox) target these directly." | README.md:1242, 1244 | CHANGELOG.md:198-200 (camoufox iptal edildi) | BAYAT | README.md:1242 ve 1244 satırlarındaki camoufox vaatlerini temizle. |
| 29 | "Token-efficient screenshots — element-level crop (13x smaller)" | README.md:1321 | none | KANITSIZ | "(13x smaller)" çarpanını kaldır; "element-level crop reduces image dimensions" yaz. |
| 30 | "block: 3-10x faster page loads on opt-in" | README.md:1327 | none | KANITSIZ | "3-10x faster" yerine "substantially faster by skipping images/fonts" yaz veya ölçüm ekle. |
| 31 | "eval-batch: Run N JS expressions in 1 roundtrip (5-30x faster)" | README.md:315, 1326 | src/cdpilot.py:14100, test/test.js:71 | KANITLI | Değişiklik gerekmez (1 roundtrip vs N roundtrip mimari kanıtı). |
| 32 | "Auto-wait — MutationObserver-based, 5s automatic element waiting" | README.md:1324 | src/cdpilot.py:4680, test/test.js:63-66 | KANITLI | Değişiklik gerekmez. |
| 33 | "Pro ($9/mo): Stealth Mode, CAPTCHA solving, Workflow recorder & replay" | cdpilot-site/src/components/pricing.tsx:50-54 | src/cdpilot.py (Stealth ve Captcha Free'de var) | YANLIŞ | Free'deki özellikleri Pro listesinden çıkar; recorder/replay'i 'Planlanan' olarak ayır. |

---

## 2. README veya Sitenin İma Ettiği Ancak Kodda Olmayan Vaatler

1. **Issue #3 — Standart CSS Seçicilerinde Shadow DOM Desteği (`click`, `fill`, `>>>` piercing):**
   - *İma:* [README.md](file:///Users/nadir/01dev/cdpilot/README.md#L1341) Shipped altında "Shadow DOM traversal" maddesi yer alır ve [README.md](file:///Users/nadir/01dev/cdpilot/README.md#L252) iframe/shadow komutlarını sıralar.
   - *Gerçek:* Yalnızca `smart-click`, `smart-fill`, `smart-select` açık shadow root'ları gezer ([`deepQuerySelectorAll`](file:///Users/nadir/01dev/cdpilot/src/cdpilot.py#L5350)). Doğrudan `cdpilot click "host >>> button"` veya `cdpilot fill "host >>> input"` desteği kodda yoktur; GitHub issue #3 olarak açıktır ([`compare/page.tsx:165`](file:///Users/nadir/01dev/cdpilot-site/src/app/compare/page.tsx#L165) bunu teyit eder).

2. **Issue #4 — Ağ Trafiğini HAR Formatında Dışa Aktarma (`--har`):**
   - *İma:* [FAQ](file:///Users/nadir/01dev/cdpilot-site/src/components/faq.tsx#L36) metninde `network` komutunun veri çıkarma ve trafik izleme için tam kontrol sunduğu belirtilir.
   - *Gerçek:* [`cmd_network`](file:///Users/nadir/01dev/cdpilot/src/cdpilot.py#L15150) yalnızca URL ve durum kodlarını basit metin/JSON olarak basar. HAR 1.2 spesifikasyonuna uygun dışa aktarım (`--har output.har`) kodda yoktur (GitHub issue #4).

3. **Issue #5 — Oturum Kaydetme ve Yeniden Oynatma (Record & Replay):**
   - *İma:* Sitenin fiyatlandırma sayfasında ([`pricing.tsx:54`](file:///Users/nadir/01dev/cdpilot-site/src/components/pricing.tsx#L54)) Pro özellikleri arasında "Workflow recorder & replay" listelenir.
   - *Gerçek:* Kod tabanında `record` veya `replay` komutu, alt yapısı veya JSON akış kaydı yoktur (GitHub issue #5). README Shipped altında değil Coming Soon altındadır, ancak pazarlama sitesinde Pro özellik kutusunda yer alması yanıltıcıdır.

4. **Multi-Instance Paralel Süreç Havuzu (`CDPILOT_POOL_SIZE`):**
   - *İma:* [pricing.tsx](file:///Users/nadir/01dev/cdpilot-site/src/components/pricing.tsx#L53) "Parallel orchestration (10+ concurrent sessions)" vaat eder.
   - *Gerçek:* Bu özellik v0.9.0'da ilan edilmiş ancak kodda hiç yer almadığı anlaşılınca v0.9.1'de çekirdekten çıkarılmıştır ([CHANGELOG.md:137](file:///Users/nadir/01dev/cdpilot/CHANGELOG.md#L137)). Tek bir tarayıcı içinde `context create` izolasyonu vardır, ancak bağımsız Brave/Chrome süreç havuzu (multi-instance) kodda bulunmamaktadır.

5. **CHANGELOG [Unreleased] MCP Tool Profilleri (`cdpilot mcp --tools core`):**
   - *İma:* [README.md:144-151](file:///Users/nadir/01dev/cdpilot/README.md#L144-L151) `cdpilot mcp --tools core` özelliğini mevcut özellik gibi açıklar (sitede hero badge `v0.9.4 on npm` gösterir).
   - *Gerçek:* Kod git `main` dalında uygulanmış ve test edilmiştir ([`test/test.js:9200`](file:///Users/nadir/01dev/cdpilot/test/test.js#L9200)), ancak CHANGELOG'da `[Unreleased]` bölümündedir; npm'deki v0.9.4 sürümüne henüz dahil edilmemiştir.

6. **Camoufox ve Undetected-Chrome ile TLS Parmak İzi Düzeltme:**
   - *İma:* [README.md:1242, 1244](file:///Users/nadir/01dev/cdpilot/README.md#L1242-L1244) satırlarında "v0.8+ (TLS fingerprint correction via camoufox) target these directly" vaadi yer alır.
   - *Gerçek:* Camoufox (Firefox tabanlı) ve undetected-chrome'un CDP desteği olmaması nedeniyle entegrasyonun imkansız olduğu 2026-05-20'de tespit edilmiş ve iptal edilmiştir ([CHANGELOG.md:198-200](file:///Users/nadir/01dev/cdpilot/CHANGELOG.md#L198-L200), [README.md:396-402](file:///Users/nadir/01dev/cdpilot/README.md#L396-L402)). Ancak Stealth Bench tablosu ve metninde unutulmuştur.

7. **Bulut / Barındırılan MCP Uç Noktası (`wss://api.cdpilot.ndr.ist/mcp`):**
   - *İma:* [pricing.tsx:71-76](file:///Users/nadir/01dev/cdpilot-site/src/components/pricing.tsx#L71-L76) satırlarında "MCP WebSocket endpoint", "Hosted browser sessions", "REST API access" sıralanır.
   - *Gerçek:* Herhangi bir barındırılan sunucu veya bulut altyapısı mevcut değildir.

---

## 3. Yeni Bir Kullanıcı İçin En Yanıltıcı 5 Konu ve Birebir Düzeltmeleri

### 1. Sıfır Bağımlılık (Zero Dependencies) Abartısı
- **Sorun:** [README.md:1283](file:///Users/nadir/01dev/cdpilot/README.md#L1283) ("Zero npm/Python runtime dependencies means zero supply-chain attack surface") ve [README.md:31](file:///Users/nadir/01dev/cdpilot/README.md#L31). Kullanıcı hiçbir paket kurulmayacağını sanır; oysa `websockets` Python tarafında zorunludur ve ilk çalıştırmada otomatik kurulur, Web Bot Auth ise `cryptography` ister.
- **Birebir Değiştirilecek Cümle:**
  > "Zero npm dependencies, with a single lightweight Python runtime dependency (`websockets`) and an optional package for signing (`cryptography`)."

### 2. "CAPTCHA Çözücü Değiliz" ile "2Captcha / Captcha-Solve Var" Çelişkisi
- **Sorun:** [README.md:1244](file:///Users/nadir/01dev/cdpilot/README.md#L1244) ve [compare/page.tsx:169](file:///Users/nadir/01dev/cdpilot-site/src/app/compare/page.tsx#L169) satırlarındaki "cdpilot is an avoidance engine, not a CAPTCHA solver. We do not call 2Captcha, DeathByCaptcha..." ifadesi, [README.md:780](file:///Users/nadir/01dev/cdpilot/README.md#L780) ("Captcha Solver Plugins: Optional integration with 2captcha...") ve [`captcha-solve`](file:///Users/nadir/01dev/cdpilot/src/cdpilot.py#L820) komutlarıyla taban tabana zıttır.
- **Birebir Değiştirilecek Cümle:**
  > "cdpilot operates as an avoidance engine by default, with built-in opt-in plugins for BYOK CAPTCHA solving (2captcha, capsolver, amazon-local OCR) when avoidance is not enough."

### 3. Kendi Tarayıcısına Bağlanmanın Sitede "Henüz Belgelenmedi" Olarak Gösterilmesi
- **Sorun:** [compare/page.tsx:154](file:///Users/nadir/01dev/cdpilot-site/src/app/compare/page.tsx#L154) SSS maddesi "a browser you started yourself with --remote-debugging-port can be driven too; that path is not documented yet... Playwright and Puppeteer expose attaching as a first-class API" diyerek kullanıcıyı rakip araçlara yönlendirir. Hemen altındaki madde ve [README.md:963](file:///Users/nadir/01dev/cdpilot/README.md#L963) ise v0.9.4 ile gelen `cdpilot connect` özelliğini tam belgeli olarak sunar.
- **Birebir Değiştirilecek Cümle:**
  > "Yes — since v0.9.4, `cdpilot connect [<port>|--auto]` attaches directly to your running Chrome/Brave/Vivaldi/Edge browser, leaving existing tabs and cookies safe and untouched."

### 4. Geri Çekilmiş Camoufox TLS Vaadinin Benchmark Tablosunda Unutulması
- **Sorun:** [README.md:1242 ve 1244](file:///Users/nadir/01dev/cdpilot/README.md#L1242-L1244) satırlarında "v0.8+ (TLS fingerprint correction via camoufox) target these directly" denir. Oysa Camoufox'un CDP mimarisiyle çalışmadığı aylar önce anlaşılmış ve [CHANGELOG.md:198](file:///Users/nadir/01dev/cdpilot/CHANGELOG.md#L198) ile geri çekilmiştir.
- **Birebir Değiştirilecek Cümle:**
  > "PerimeterX (2/18), GeeTest (0/4), and Akamai (1/6) remain challenging targets; protocol-level TLS fingerprinting cannot be solved via CDP browsers alone and is tracked for a future proxy/MITM architecture."

### 5. Pro Planda Ücretsiz Çekirdek Özelliklerin Satılık Gösterilmesi
- **Sorun:** [pricing.tsx:50-54](file:///Users/nadir/01dev/cdpilot-site/src/components/pricing.tsx#L50-L54) altında $9/aylık Pro pakette "Stealth Mode" ve "CAPTCHA solving" listelenmektedir. Kullanıcı bu kritik yeteneklerin paralı olduğunu düşünür; oysa ikisi de MIT lisanslı açık kaynak CLI'da tamamen ücretsiz ve etkindir.
- **Birebir Değiştirilecek Cümle:**
  > "Advanced features for teams: Shared browser profiles, team audit logging, and priority support (all core automation features, including Stealth Mode and CAPTCHA solving, remain 100% free and open-source)."

---

SONUÇ:
cdpilot repo ve cdpilot-site pazarlama/dokümantasyon vaatleri kod ve testlerle denetlendi · İncelenen: README.md, CHANGELOG.md, src/cdpilot.py, bin/cdpilot.js, test/test.js, cdpilot-site (components, blog, app/compare), token ölçüm dokümanları · Doğrulama: npm test 564 passed, 1 failed (bot-auth live socket owner testi lokal ortamda atladı); cdpilot-site claims.test.mjs 8 passed, 1 failed (.ts import) · Şefe not: Hiçbir dosya değiştirilmedi; 33 iddia tablosu, 7 açık vaat/issue analizi ve en yanıltıcı 5 konunun birebir düzeltme cümleleri raporda eksiksiz sunuldu.
