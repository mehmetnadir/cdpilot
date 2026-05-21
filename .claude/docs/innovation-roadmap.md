# cdpilot Innovation Roadmap (post-v0.5.0)

> Test/e2e ekosistemindeki 2025-26 trendlerine göre hangi feature'ları
> hangi sırayla ekleyeceğimizin yol haritası. Kaynak: rakip analiz
> (browser-use, Playwright Trace Viewer, Vitest Browser Mode, Patchright,
> Camoufox, mabl, QA Wolf, Vercel agent-browser, Stagehand, Browserbase).

## Konum Özeti

| Tema | Konumumuz | Aksiyon |
|---|---|---|
| CDP-direct, zero-dep | 🟢 Lider | Korunacak diferansiyatör |
| A11y token-efficient agent IF | 🟡 Yarım | Faz 3'te tamamla |
| Stealth (binary-level / behavioral) | 🔴 Geride | Faz 2: behavioral entropy |
| Self-healing / agentic QA | 🔴 Eksik | Faz 1: selector ladder |
| Test runner birleşimi | 🔴 Eksik | Faz 4: cdpilot test |
| Cloud-API uyumlu lokal | 🔴 Eksik | Faz 5: serve --api |

## Faz Sırası

### Faz 1 — Selector Ladder + Heal Log (smallest, highest ROI)

**Ne:** `click`, `fill`, `type`, `hover`, `submit` komutları artık tek
selector almıyor — bir locator stratejisi listesi sırayla denenir,
ilk hit kullanılır. Her hit/miss `~/.cdpilot/projects/<id>/heal.jsonl`
satırına yazılır.

**Locator ladder (sırasıyla):**
1. Exact CSS/XPath (kullanıcı verdiği)
2. ARIA role + accessible name (a11y'den)
3. Visible text exact match
4. Visible text fuzzy match (Levenshtein < 3)
5. Stable attributes (data-testid, data-cy, name, id)
6. Position-based fallback (nth-of-type within container)

**API:** Mevcut `cdpilot click <sel>` yüzeyi DEĞİŞMEZ. Yeni opsiyonel
`--ladder <strategy1,strategy2,...>` flag. Default: tüm ladder.

**Output:** Stdout sade (eski davranış). Heal event'i sadece dosyaya.
`cdpilot heal log` ile incelenir, `cdpilot heal stats` ile özetlenir.

**Etki:** Test stabilitesi büyük artar. mabl / QA Wolf'un sattığı
self-healing'in açık kaynak versiyonu, sıfır LLM ile.

**Effort:** ~150-200 LOC, tek modül (`heal.py` yerine inline cdpilot.py).
**Test:** 5 e2e senaryo — selector kaymış, text değişmiş, role aynı.

### Faz 2 — Behavioral Entropy

**Ne:** Mouse hareket, scroll, key dwell, click timing'e insan davranış
modeli. Bezier curves, GMM dwell, scroll easing.

**Modül:** `entropy.py` (~120 LOC). Hooks: mevcut click/scroll/type/keys
fonksiyonları opsiyonel `entropy=True` parametresi alır. Adaptive
escalation tarafından otomatik enable edilir (CAPTCHA tespit edilince).

**Etki:** DataDome/Akamai/PerimeterX davranışsal skorlamasını düşürür.
Patchright/nodriver'da olan, bizde olmayan tek büyük stealth kartı.

**Effort:** ~150 LOC + entropi sabitleri için araştırma.
**Test:** PerimeterX + DataDome kategorilerindeki Stealth Bench skoru.

### Faz 3 — `cdpilot agent` Token-Budget Mode

**Ne:** AI agent'lara optimize edilmiş "thin client" mode. A11y tree'yi
numbered `@ref` map olarak emit eder, adımlar arası **diff-only** update.
Hedef: 10-step task < 30k token.

**Komut:** `cdpilot agent observe` → `{state, actions[]}` JSON döner.
`cdpilot agent act --ref @42 click` → action yapar, **sadece diff**
döner. Tree diff cache (`~/.cdpilot/projects/<id>/a11y-tree.cache`).

**Etki:** browser-use / Stagehand kullananlar için cdpilot %4 maliyet,
%93 token tasarrufu (agent-browser Vercel claim'inden esinli).

**Effort:** ~300 LOC. A11y mevcut kısımı genişletme + cache layer.
**Test:** 10-step navigation, token count assertion.

### Faz 4 — `cdpilot test` Zero-Config Runner

**Ne:** `*.cdpt.js` veya `*.cdpt.py` dosyalarını çalıştırır. Watch mode,
Context Pool ile paralel. Her step için **trace bundle**
(a11y+screenshot+console+network) → `cdpilot trace open` ile time-travel.

**API:**
```bash
cdpilot test                    # Tüm *.cdpt.* dosyaları
cdpilot test --watch            # Vitest tarzı
cdpilot test login.cdpt.js      # Tek dosya
cdpilot trace open run-42       # Trace viewer (local web UI)
```

**Etki:** Playwright Trace Viewer'ın killer feature'ını çal, zero-config.
Vitest Browser Mode'a alternatif (CDP üzerinden, daha az soyutlama).

**Effort:** ~600 LOC + viewer için minimal local HTTP server + static HTML.
**Test:** Kendi test suite'imizi cdpilot test ile yaz.

### Faz 5 — Browserbase-Compatible Local API

**Ne:** `cdpilot serve --api` REST sunucu. Browserbase API shape:
- `POST /v1/sessions` → CDP URL döner (context pool'dan)
- `DELETE /v1/sessions/<id>` → release
- `GET /v1/sessions/<id>/debug` → DevTools URL

**Etki:** Stagehand, browser-use, ChatBrowserUse kodu `BROWSERBASE_URL=
http://localhost:9333` ile değişiklik yapmadan localhost'a bağlanır.
$0/saat lokal + aynı SDK. Bizim için en güçlü "rakipleri bedavaya
indir" hamlesi.

**Effort:** ~200 LOC (stdlib http.server yeter, sıfır bağımlılık korunur).
**Test:** Stagehand örnek script'ini yeniden yönlendir, çalışmasını
doğrula.

### Faz 6 — Doküman + Site

**Ne:** README.md, cdpilot.ndr.ist landing + docs, CHANGELOG.md, CLAUDE.md
"Aktif Çalışma" tablosu, blog post (feature başına 1 madde).

**Site bölümleri eklenecek:**
- "Test Runner" bölümü (Faz 4)
- "Agent Mode" bölümü (Faz 3)
- "Self-Healing" bölümü (Faz 1)
- "Local Browserbase" bölümü (Faz 5)
- Stealth Bench benchmark sonuçları (zaten ayrı projede)

## Risk / Önlem

- **Sıfır bağımlılık politikası:** Hepsi stdlib'de yapılabilir. Faz 4
  trace viewer için minimal HTML+JS (vanilla, build step yok).
- **API yüzey büyümesi:** Mevcut komutlar değişmez, hepsi additive. Yeni
  komutlar `agent`, `test`, `trace`, `heal`, `serve` namespace'lerinde.
- **Tek dosya cdpilot.py 2600 → ~3800 satıra çıkar.** Sınır 5000.
  Geçilirse modüler refactor ayrı bir faz olarak gelecek.

## Çıkış Kriterleri (her faz için)

1. Yeni komut(lar) `--help` çıktısında listeli
2. Mevcut testler kırılmadı (test/test.js geçiyor)
3. README "Komutlar" bölümünde 1 satır
4. CHANGELOG'da satır
5. v0.5.x veya v0.6.0 release etiketinde
