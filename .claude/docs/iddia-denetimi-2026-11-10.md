# cdpilot iddia denetimi — 0.9.6 sonrası (10.11.2026)

Yöntem: 06.11 denetimiyle aynı (`iddia-denetimi-2026-11-06.md`). Sayı ya da üstünlük taşıyan her iddia alıntılandı,
kanıtı (ölçüm belgesi, test adı, kod) yazıldı, hüküm verildi. Kapsam: README.md, `--help` (bin/cdpilot.js yardım bloğu,
src/cdpilot.py baş docstring'i), CHANGELOG.md [0.9.6], package.json açıklama/anahtar sözcük, server.json ve manifest.json
açıklamaları, cdpilot-site/src (hero, compare, pricing, commands.ts agent/daemon girdileri). Salt okunur; yalnız bu dosya yazıldı.

Hükümler: **DOĞRU** · **ABARTILI** · **DESTEKSİZ** · **ESKİ** (0.9.6 öncesi doğru, şimdi yanlış) · **ÇELİŞKİLİ** (iki yer uyuşmuyor).

## 0. Bu denetimde yapılan ölçümler

| Ölçüm | Sonuç | Koşul |
|---|---|---|
| `record status` dönüşümlü A/B, 6 çift (taze `CDPILOT_DAEMON=0` / sıcak `=1`), python `perf_counter` sarmalı | taze 339–447 ms · sıcak 97–139 ms | 10.11 22:40, `uptime` yük 359–376, agir.sh slot, geçici `CDPILOT_HOME`, `daemon stop` ile kapatıldı |
| MCP `tools/list` (stdio, tarayıcısız) | 49 araç, kompakt JSON 29.822 karakter; 4 `browser_agent_*` aracı 2.937 karakter | 10.11 22:38, yük ~315 |
| ↳ 0.9.4 oranıyla token (5.769 token / 26.809 karakter) | ≈ 6.417 token; ajan araçları 0.9.4 şemasının %11,0'ı | tiktoken bu makinede yok; oran ölçeklemesi |
| `npm pack --dry-run` (çalışma ağacı) / `npm view cdpilot` (yayında 0.9.6) | unpacked 1.163.239 bayt (ikisi aynı), packed 332.254, 5 dosya | — |
| `wc -c` | src/cdpilot.py 1.024.764 bayt (23.632 satır) · bin/cdpilot.js 50.678 bayt | — |
| `grep -c '^(async )?def cmd_' src/cdpilot.py` | 165 komut fonksiyonu | — |

Yük 360 altında taze süre tabanın (yük ~10'da ~270 ms) üstünde; sıcak süre iddianın (~140 ms) altında kaldı. Oran (3–4×) iddiayı destekler.

## 1. İddia tablosu

### A. Sıcak süreç (daemon, MCP)

| # | İddia (≤20 sözcük) | Yer | Kanıt | Hüküm | Düzeltilmiş ifade |
|---|---|---|---|---|---|
| 1 | "a browser-free command goes from ~270 ms to ~140–150 ms end to end" | CHANGELOG.md:15 | plan-daemon-insan-hizi.md §2 (`version` 138, `record status` 149 ms; yük ~10); §0 ölçüm | DOĞRU | — |
| 2 | "`content` from ~360 to ~110 ms" | CHANGELOG.md:15 | §5 357–373 → 105–120 (yük 20–34); §5.1 348–376 → 105–126 | DOĞRU | — |
| 3 | "~110 ms of that is the node launcher" | CHANGELOG.md:15 | §2; §5.3 node 26 arm64 boş açılış 123–134 ms | DOĞRU | — |
| 4 | "browser-free command ~270 -> ~140 ms, content/eval ~360 -> ~110 ms, M1 Max" | bin/cdpilot.js:763-764 | §2, §5, §5.1 (`eval` 365–373 → 95–114) | DOĞRU | — |
| 5 | "drops to ~140 ms … `content` to ~110 ms, … warm `go` … ~230 ms of which ~125 ms is the node launcher" | cdpilot-site/src/app/compare/page.tsx:165 | §2, §5.2 (`go` ısınma sonrası 230–242), §5.3 | DOĞRU | — |
| 6 | "so the second and later calls skip the start-up cost" | README.md:1040-1041 | §0 tablo, §5.3: node açılışı (~110 ms) sıcak yolda da kalır, sıcak yolun %80–85'i | ABARTILI | "…skip the Python start-up and CDP session set-up; node's ~0.1 s launcher remains: a browser-free command ~270 → ~140 ms, `content`/`eval` ~360 → ~110 ms (M1 Max)." |
| 7 | "a browser paints a page in 20 ms, `cdpilot go` took about a second" | README.md:1036 | perf-taban-2026-11-08.md §1 (956–1307 ms, 0.9.6 öncesi); CHANGELOG.md:20 taze 502–826, sıcak 227–298 ms | ESKİ | "…`cdpilot go` took about a second before 0.9.6; now 0.5–0.8 s fresh and ~0.23–0.30 s with `CDPILOT_DAEMON=1`." |
| 8 | "~10 ms before the CDP work instead of ~400 ms (… medians 11 / 7 / 9 ms against 412 / 390 / 416 ms" | README.md:163-164; aynısı README.md:1072, CHANGELOG.md:10, compare/page.tsx:165 | §7 (yük 30–50, 4 araç × 3 tur, `olc-mcp.js`); test `mcp warm: CDPILOT_DAEMON=1 runs tool calls in the server process …` | DOĞRU | İsteğe bağlı netlik: medyanlar CDP işini de içerir → "~10 ms a call, CDP work included, for `eval`/`tabs`/`content`". |
| 9 | "tool calls run in the server process instead of a fresh one (~400 -> ~10 ms a call)" | src/cdpilot.py:48-49 | §7 | DOĞRU | — |
| 10 | "Nothing is ever executed twice." | README.md:1062 | test `daemon: two simultaneous calls both succeed (warm or fresh, never twice)` | DOĞRU | — |
| 11 | "they also leave after 30 min idle" / "default 1800" | README.md:1048, :1066; bin/cdpilot.js:767 | `CDPILOT_DAEMON_IDLE` varsayılanı 1800; test `daemon: start, stop and idle exit` | DOĞRU | — |
| 12 | "fresh `go file://` 714–1053 → 502–826 ms, warm … 426–515 → 227–298 ms" | CHANGELOG.md:20 | §5, §5.1 | DOĞRU | — |
| 13 | "a browser-free command (`record status`) goes from ~500 ms to ~270 ms" | CHANGELOG.md:21 | perf-taban §5: 480–523 → 265–279 | DOĞRU | — |

### B. Öğrenen akış token sayıları

| # | İddia | Yer | Kanıt | Hüküm | Düzeltilmiş ifade |
|---|---|---|---|---|---|
| 14 | "`tokens_avoided` (an upper bound: a full observation before each step, more than a diff-reading agent reads)" | CHANGELOG.md:11 | olcum/gercek-site-token-2026-11-10.md şef notu: Wikipedia `tokens_avoided` 21.823 > model döngüsü 15.474 | DOĞRU | — |
| 15 | "The result's `tokens_avoided` is what a model would have read observing the page before each step." | README.md:509-510 (benzeri commands.ts:2017, :2030) | aynı belge: üst sınırdır; doğru kıyas "model döngüsü → sonuç JSON": HN 18.331 → 90, Wikipedia 15.474 → 136, httpbin 2.292 → 119 | ABARTILI | "…is an upper bound — a full observation before each step; an agent that reads diffs reads less. On three real sites the model loop read 2,292–18,331 tokens, the `agent run` result 90–136." |
| 16 | "replays a learned flow with no page read at all" | README.md:158 | gercek-site-token: başarılı koşuda yalnız sonuç JSON'u (90–136 token), 9 koşuda 0 sapma; sapmada sayfa döner (README.md:513) | DOĞRU | — |

### C. Enjeksiyon sayıları

| # | İddia | Yer | Kanıt | Hüküm | Düzeltilmiş ifade |
|---|---|---|---|---|---|
| 17 | "this is a fit rate, not a held-out one: 19/20 caught …, 0 false alarms" | CHANGELOG.md:13 | test `injection-aware observe (unit): … 20 + 20 corpus: >= 19 caught, 0 false alarms`; plan-ogrenen-akis.md §7 tablo | DOĞRU | — |
| 18 | "Unit test with 11 flagged / 10 clean phrases" | CHANGELOG.md:13 | test/test.js:1294-1318 (11 `flagged`, 10 `clean`) | DOĞRU | — |
| 19 | "a page *about* AI agents or system prompts is not flagged" | README.md:536-537 | 0/20 sert negatif, desenlerin ayarlandığı aynı korpus; desen yalnız İngilizce (plan-ogrenen-akis.md §7 "Sınır") | ABARTILI | "The patterns are narrow on purpose and English-only: on the corpus they were tuned on (`test/fixtures/injection-korpus.json`) 0 of 20 pages about AI were flagged and 19 of 20 injections caught (the German one is missed)." |

### D. MCP araç sayıları

| # | İddia | Yer | Kanıt | Hüküm | Düzeltilmiş ifade |
|---|---|---|---|---|---|
| 20 | "tools/list grows from 45 to 49 (51 with WebMCP); the `core` profile is unchanged" | CHANGELOG.md:12, :18 | test `webmcp: MCP tools/list is 49 tools with WebMCP off …, 51 with it on`; `mcp profile: default stays all 49 tools …`; `mcp profile: CDPILOT_MCP_TOOLS=core lists the 10 core tools plus browser_tools`; §0 ölçüm 49 | DOĞRU | — |
| 21 | "49 MCP tools (51 with WebMCP; an 11-tool core profile)" | compare/page.tsx:83 | aynı testler | DOĞRU | — |
| 22 | "It ships a built-in MCP server (42 tools)" | compare/page.tsx:142 | :83 ile çelişir; 06.11 denetimi #7'de de işaretliydi | ÇELİŞKİLİ | "…built-in MCP server (49 tools, 51 with WebMCP; an 11-tool core profile)…" |
| 23 | "45 tools = 5,769 tokens, `core` = 11 tools = 1,342 tokens; … 49 tools ≈ 6,400 tokens, scaled" | README.md:151-152 | token-taban-2026-10-24.md (26.809 karakter = 5.769 o200k); §0: 49 araç 29.822 karakter → ≈6.417, ajan araçları %11,0 | DOĞRU | — (ölçekleme olarak etiketli; tiktoken ile ölçülürse "scaled" kalkar) |
| 24 | "its 70+ commands (navigation, …) are available as MCP tools" | manifest.json:7 | MCP 49 araç sunar (51 WebMCP ile); 70+ CLI komutudur | ABARTILI | "This bundle installs cdpilot's MCP server: 49 tools (51 with WebMCP) for navigation, interaction, …" |
| 25 | "70+ commands" / "70+ CLI commands" | README.md:32, :1478; package.json:5; manifest.json:6; pricing.tsx:29 | §0: 165 `cmd_` fonksiyonu | DOĞRU | — |

### E. "Sıfır bağımlılık" ifadesi

| # | İddia | Yer | Kanıt | Hüküm | Düzeltilmiş ifade |
|---|---|---|---|---|---|
| 26 | "Zero npm dependencies — … the Python side needs one package, `websockets`" | README.md:31 (aynı çizgi :1423, :1445; compare:51; faq.tsx:31) | package.json'da `dependencies` yok; CHANGELOG [0.9.5] Changed | DOĞRU | — |
| 27 | "Zero-dependency browser automation from your terminal." | README.md:3 | README.md:31 ve CHANGELOG [0.9.1] "Corrected", [0.9.5] Changed ile çelişir | ÇELİŞKİLİ | "Zero-npm-dependency browser automation from your terminal." |
| 28 | "cdpilot v${VERSION} — Zero-dependency browser automation" | bin/cdpilot.js:748 (yorum :4) | aynı | ÇELİŞKİLİ | "— browser automation, zero npm dependencies" |
| 29 | "cdpilot — Zero-dependency browser automation from your terminal." | src/cdpilot.py:3 | aynı | ÇELİŞKİLİ | "cdpilot — Zero-npm-dependency browser automation from your terminal." |
| 30 | "Zero-dependency browser automation CLI. Raw CDP, 70+ commands…" | package.json:5; manifest.json:6 | aynı | ÇELİŞKİLİ | "Browser automation CLI with zero npm dependencies (Python: websockets). Raw CDP, 70+ commands…" |
| 31 | "Zero-dependency browser automation over raw CDP — no Puppeteer, Playwright, or Selenium." | server.json:4 | aynı | ÇELİŞKİLİ | "Zero-npm-dependency browser automation over raw CDP — no Puppeteer, Playwright, or Selenium." (92 karakter) |
| 32 | anahtar sözcük `"zero-dependency"` | package.json:23 | aynı | ÇELİŞKİLİ | `"zero-npm-dependencies"` (npm aramasında eski sözcük kalsın mı: şef kararı) |
| 33 | "Zero dependencies. Raw CDP. Smart interactions" | cdpilot-site/src/components/hero.tsx:53 | compare/page.tsx:51 ve faq.tsx:31 "0 npm, Python 1 paket" der | ÇELİŞKİLİ | "Zero npm dependencies. Raw CDP. Smart interactions…" |

### F. Güvenlik cümleleri (yer tutucu, CDPILOT_VAR_HOSTS)

| # | İddia | Yer | Kanıt | Hüküm | Düzeltilmiş ifade |
|---|---|---|---|---|---|
| 34 | "a secret typed into a field named otherwise is stored in clear — review a flow before sharing it" | CHANGELOG.md:11; README.md:516-520 | `_agent_mask_text` (src/cdpilot.py:16393), `_AGENT_SECRET_FIELD_RE` (:15819); test `learned flows (fake browser): … placeholders …` | DOĞRU | — |
| 35 | "flow files and `agent-state.json` are written 0600" | CHANGELOG.md:11; README.md:520 | src/cdpilot.py:16313, :15858 (`0o600`) | DOĞRU | — |
| 36 | "a step that types one runs only on the host it was recorded on" | README.md:521-522 | CHANGELOG.md:11 "origin" der; kod köken (şema+host+port) bağlar, kökensiz eski akışta host (src/cdpilot.py:16641-16652) | ÇELİŞKİLİ | "…runs only on the origin (scheme, host, port) it was recorded on; another origin or an opaque page is a drift." |
| 37 | "`CDPILOT_VAR_<NAME>` is used only by a step recorded on a host named in `CDPILOT_VAR_HOSTS` … never inside a URL" | README.md:524-527; CHANGELOG.md:11; src/cdpilot.py:42 | src/cdpilot.py:16540-16577; test/test.js:7524-7544 (`refused`, `does not name evil.test`) | DOĞRU | — |
| 38 | "Typed secrets are supplied via --var k=v or CDPILOT_VAR_<NAME>." | cdpilot-site/src/data/commands.ts:2017 | tek başına `CDPILOT_VAR_<NAME>` exit 2 `refused` verir (src/cdpilot.py:16562-16577) | ÇELİŞKİLİ | "…via --var k=v, or CDPILOT_VAR_<NAME> when CDPILOT_VAR_HOSTS names the host the value was recorded on (never in a URL)." |
| 39 | "Typed values are masked in agent state." | cdpilot-site/src/data/commands.ts:1955 | yalnız sır adlı alan ya da jeton biçimli değer maskelenir (#34) | ABARTILI | "Values typed into secret-named fields (password, one-time code, API key, PIN, card number…) or token-shaped values are masked; other values are stored as typed." |
| 40 | "`--dry-run` never prints values" | CHANGELOG.md:11; README.md:516 | src/cdpilot.py:16582-16586 (diskteki adımlar, değişken değeri yok) | DOĞRU | — |
| 41 | "Exit codes: 0 ok, 1 error …, 124 --timeout; exit 3 from click" | src/cdpilot.py:96-101 | 0.9.6: `agent run` sapma 4 (`AGENT_RUN_DRIFT_EXIT`, :16259), eksik/reddedilen değişken ve `agent act` yer tutucu reddi 2 | ESKİ | "…; 2 agent: unknown flow, missing or refused variable, {{placeholder}} in --text/--url; 4 agent run: drift (page observation on stdout)." |

### G. Diğer sayı ve üstünlük iddiaları

| # | İddia | Yer | Kanıt | Hüküm | Düzeltilmiş ifade |
|---|---|---|---|---|---|
| 42 | "The only browser MCP with built-in test assertions." | README.md:1474 | @playwright/mcp `--caps=testing`: `browser_verify_element_visible`, `_text_visible`, `_list_visible`, `_value` (github.com/microsoft/playwright-mcp, playwright.dev/mcp) | DESTEKSİZ | "A browser MCP with 10 built-in test assertions." |
| 43 | Karşılaştırma: Puppeteer/Playwright/Selenium "400MB+ / 200MB+ / 100MB+", bağımlılık "50+ / 30+", MCP "no / no", kurulum "instant" | README.md:1422-1428 | compare/page.tsx:44-54, :84-85 (kaynaklı, 27.09): puppeteer 6, playwright 1 doğrudan bağımlılık; resmî @playwright/mcp var | ÇELİŞKİLİ | Tabloyu compare sayfasının değerleriyle eşitle: bağımlılık "6 / 1 / 4 (direct npm)", MCP "deprecated official / official @playwright/mcp / none official"; "instant" yerine "one `npx`, Python 3.10+". |
| 44 | "Run N JS expressions in 1 roundtrip (5-30x faster)" | README.md:343, :1488; commands.ts:1795 | ölçüm belgesi yok; çarpan N'ye eşittir (çağrı başı sabit maliyet baskınsa); 0.9.5 aynı türden "13x", "3-10x" çarpanlarını kaldırdı | DESTEKSİZ | "Run N JS expressions in one process and one CDP roundtrip instead of N" |
| 45 | "1 Python file (~542KB) + small Node launcher (~23KB); npm package ~0.6MB unpacked" | compare/page.tsx:43 (ayrıca :146 "~0.6MB npm package") | §0: 1.024.764 / 50.678 bayt; yayındaki 0.9.6 unpacked 1.163.239 | ESKİ | "1 Python file (~1.0MB) + small Node launcher (~50KB); npm package ~1.2MB unpacked (~0.33MB packed), no node_modules" |
| 46 | "a browser you started with --remote-debugging-port works too (undocumented path)" | compare/page.tsx:115 | :123, :154 ve README `cdpilot connect` bölümü belgeli (v0.9.4) | ÇELİŞKİLİ | "…works too: `cdpilot connect <port>` (v0.9.4) attaches to it." |
| 47 | "cdpilot describes itself as \"an avoidance engine, not a CAPTCHA solver\"" | compare/page.tsx:169 | README.md:1406 (0.9.5'ten beri): "an avoidance engine first; the solver plugins … are a fallback" | ESKİ | "cdpilot describes itself as \"an avoidance engine first\"; its BYOK solver plugins are opt-in fallbacks…" |
| 48 | Pro: "Stealth Mode", "Anti-fingerprint (proxy rotation…)", "CAPTCHA solving (2Captcha/hCaptcha integration)" | pricing.tsx:52-54 | bunlar MIT CLI'da ücretsiz (`mode`, `proxy add/use`, `captcha-solve`); README.md:1432 "free and open source" | ÇELİŞKİLİ | Pro listesinden çıkar; Free'ye "3-tier stealth, proxy pools, BYOK CAPTCHA solvers" ekle (06.11 #33'ten açık). |
| 49 | "Parallel orchestration (10+ concurrent sessions)" | pricing.tsx:55 | havuz 0.9.1'de geri çekildi (CHANGELOG [0.9.1]); 10+ oturum ölçümü yok | DESTEKSİZ | Kaldır ya da "Planned". |
| 50 | rozet "Most Popular" ("Coming Soon" planda) | pricing.tsx:62 | satılmamış plan için kullanım verisi olamaz | DESTEKSİZ | Rozeti kaldır ya da "Planned". |
| 51 | "99.9% uptime SLA" | pricing.tsx:77 | barındırılan hizmet yok | DESTEKSİZ | Kaldır ya da "(planned)". |
| 52 | "10 built-in test assertions" | pricing.tsx:30; compare/page.tsx:107 | 06.11 #14 (src assert komutları) | DOĞRU | — |
| 53 | "1.4–42× smaller than the page's raw HTML on the four pages we measured" | README.md:1482; compare/page.tsx:91 | token-olcumu-2026-09-27.md | DOĞRU | — |

## 2. Yapılacak düzeltmeler (öncelik sırasıyla)

1. **Bağımlılık dili (7 yer):** README.md:3, bin/cdpilot.js:748 (+:4 yorum), src/cdpilot.py:3, package.json:5, package.json:23,
   manifest.json:6, server.json:4, cdpilot-site/src/components/hero.tsx:53 → "zero npm dependencies" (#27–33).
2. **Güvenlik cümleleri:** commands.ts:2017 `CDPILOT_VAR_HOSTS` koşulunu ekle (#38); commands.ts:1955 "Typed values are masked"
   cümlesini daralt (#39); README.md:522 "host" → "origin" (#36).
3. **Çıkış kodları:** src/cdpilot.py:96-101 docstring'ine 2 ve 4'ü ekle (#41).
4. **Token üst sınırı:** README.md:509-510 `tokens_avoided` için "upper bound" ve gerçek site sayıları (#15).
5. **Enjeksiyon:** README.md:536-537 mutlak cümleyi korpus sayısı ve "English-only" ile değiştir (#19).
6. **Sıcak süreç:** README.md:1036 ve :1040-1041 (#6, #7) — node açılışı kalır; sayıları ekle.
7. **MCP sayıları:** compare/page.tsx:142 "42 tools" → 49/51/11 (#22); manifest.json:7 "70+ commands … as MCP tools" → 49 araç (#24).
8. **Üstünlük ve tablo:** README.md:1474 "The only browser MCP…" (#42); README.md:1422-1428 tablo (#43).
9. **Çarpan:** README.md:343, :1488, commands.ts:1795 "5-30x" (#44).
10. **Site bayatları:** compare/page.tsx:43, :146 boyutlar (#45); :115 "undocumented path" (#46); :169 alıntı (#47).
11. **Fiyat sayfası (06.11'den açık):** pricing.tsx:52-55, :62, :77 (#48–51).

Not (iddia değil, eksik): `cdpilot --help` (bin/cdpilot.js:915-917) AI AGENT bölümünde yalnız `mcp` var; `agent observe|act|flow|run`
ve MCP için `CDPILOT_DAEMON=1` yok. 0.9.6'nın iki ana özelliği yardımda görünmüyor.

## 3. Doğrulanamayanlar

- MCP sıcak yol (§7: 11/7/9 ms) yeniden ölçülmedi; tarayıcılı ölçüm yük 300+ altında anlamsız şişerdi. Belge sayısı kabul edildi.
- Gerçek site token sayıları yeniden koşulmadı; şefin 10.11 ham denetimine dayanıldı (gercek-site-token-2026-11-10.md:11).
- `≈6.417 token` tiktoken değil, 0.9.4 karakter/token oranıyla ölçeklendi.
- compare/page.tsx:150 "browser-use (~116k GitHub stars)" ve rakip paket boyutları 27.09 tarihli; ağdan yeniden denetlenmedi.
- Playwright MCP test araçları web aramasıyla doğrulandı (playwright.dev/mcp, github.com/microsoft/playwright-mcp); sürüm belirtilmedi.
