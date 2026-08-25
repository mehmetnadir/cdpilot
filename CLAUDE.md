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
| ✅ | v0.9.0 npm | Yayında (OIDC provenance); CI tüm platformlar yeşil (Windows dahil) |
| ✅ | Faz 5 yayın | Thread 9/9 canlı: x.com/cdpilot_dev/status/2091520585192845488 |
| ✅ | Twitter bot | twifork + guardrail'lı auto-post + follow-back + sentinel (30dk health watchdog, Telegram alarm + 09:00 özet) |
| ✅ | İçerik sistemi | Pillar'lar revize (%20 "Claude ile üretim hikâyeleri"); skill'ler: x-harvest, x-algorithm-truth, x-humanizer, x-hook-extractor, x-content-planner |
| ⏳ | v0.9.1 sprint | Bağlantı dayanıklılığı: auto-relaunch/attach + evrensel --timeout (#2) + open alias — friction analizi 292+171+14 hata |
| ⏳ | Sentinel takip | C6: daily_analytics gece yazmıyor (debug) · C8: 2 failed auto-like sebebi |
| ⏳ | v0.9 tls-proxy | Optional local TLS-MITM (curl-impersonate semantics) |

## Son Oturum
→ Detay: `.claude/session-journal/2026-08-25-1040-v090-twitter-revival.md` | Tüm geçmiş: `.claude/session-journal/INDEX.md`
→ Durum: v0.9.0 her yerde (npm/site/CI yeşil); Twitter operasyonu tam otonom + sentinel bekçide; 185'lik kuyruk çürümesi sınıfı kapatıldı.
→ İlk iş: sentinel C6 (analytics gece yazmıyor) debug → sonra v0.9.1 Bağlantı Dayanıklılığı Sprint'i.

Son Güncelleme: 2026-08-25

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
