> **Conductor:** Bu projeye global orkestrasyon kuralları otomatik uygulanır.
> Routing · Agent seçimi · Review pipeline → `~/.claude/CLAUDE.md` üzerinden yüklenir.
> Bu dosya yalnızca projeye özgü bağlamı içerir — global kuralları tekrar yazmayın.

# cdpilot

> Zero-dependency browser automation CLI. Tek komut, tam kontrol.

## Kimlik
- **Stack:** Node.js (entry) + Python 3 (core) | Pure CDP over HTTP/WebSocket
- **Port:** CDP 9222 (varsayılan, `CDP_PORT` ile değiştirilebilir)
- **Paket Yöneticisi:** npm | **Bağımlılık:** Sıfır (npm + Python stdlib)

## Hızlı Başlangıç
- `npx cdpilot launch` — Tarayıcı başlat (CDP modunda)
- `npx cdpilot setup` — Otomatik tarayıcı algılama, profil oluşturma
- `npx cdpilot status` — Bağlantı kontrolü
- `node test/test.js` — Test çalıştır
- `npm publish` — npm'e yayınla

## Dosya Haritası
| Ne arıyorsun | Nereye bak |
|---|---|
| Mimari, CLI komutları, tüm fonksiyon listesi | `.claude/docs/architecture.md` |
| Rakip analizi | `.claude/docs/browserless-analysis.md` |
| Site kaynak kodu | `/Users/nadir/01dev/cdpilot-site/` |

## Dikkat Edilecekler
- **Tek dosya mimari:** Tüm Python kodu `src/cdpilot.py` (~2600 satır)
- **Sıfır bağımlılık:** Harici Python/npm paketi eklenmez — stdlib only
- **Port 9222:** Varsayılan CDP, `CDP_PORT` env ile değişir
- **Brave öncelikli:** Brave > Chrome > Chromium
- **İzole profil:** `~/.cdpilot/profile` — kullanıcı tarayıcısına dokunulmaz
- **Stealth session-bound:** `Page.addScriptToEvaluateOnNewDocument` WS kapanınca silinir
- **cdpilot-site:** Ayrı dizin `/Users/nadir/01dev/cdpilot-site/`, Server 21 port 3400

## Aktif Çalışma
| Durum | Alan | Açıklama |
|-------|------|----------|
| ✅ | v0.8.0 | Core CLI (50+ komut), MCP, DevExtension, Stealth, CAPTCHA, Adaptive, Context Pool, Proxy, TLS probe |
| ✅ | Site | cdpilot.ndr.ist canlı (63 komut docs) |
| ✅ | GitHub & npm | v0.5.0 hazırlandı; npm publish onay bekliyor |
| 🔄 | cdpilot Cloud | Hosted browser sessions API (roadmap) |
| ⏳ | v0.9 tls-proxy | Optional local TLS-MITM (curl-impersonate semantics) |

Son Güncelleme: 2026-05-21

<!-- gitnexus:start -->
## GitNexus — Code Intelligence

İndekslenmiş: **131 sembol** | **465 ilişki** | **13 küme** | **20 execution flow**

- Stale uyarısı gelirse: `npx gitnexus analyze`
- Detaylı kullanım: `~/.claude/skills/code-intelligence/SKILL.md`

| Araç | Kullanım |
|------|----------|
| `gitnexus_impact({target: "X"})` | Blast radius analizi (edit öncesi ZORUNLU) |
| `gitnexus_context({name: "X"})` | 360° sembol görünümü |
| `gitnexus_query({query: "..."})` | Concept bazlı arama |
| `gitnexus_detect_changes()` | Pre-commit etki kontrolü |
| `gitnexus_rename({symbol_name: "old", new_name: "new"})` | Güvenli rename |
<!-- gitnexus:end -->
