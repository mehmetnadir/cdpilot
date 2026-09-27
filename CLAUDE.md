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
- **Tek dosya mimari:** Tüm Python kodu `src/cdpilot.py` (büyüyor — güncel satır sayısı için `wc -l src/cdpilot.py`, 2026-09-27'de 13.129 satır)
- **Sıfır bağımlılık:** Harici Python/npm paketi eklenmez — stdlib only
- **Port 9222:** Varsayılan CDP, `CDP_PORT` env ile değişir
- **Brave öncelikli:** Brave > Chrome > Chromium
- **İzole profil:** `~/.cdpilot/profile` — kullanıcı tarayıcısına dokunulmaz
- **Stealth session-bound:** `Page.addScriptToEvaluateOnNewDocument` WS kapanınca silinir
- **cdpilot-site:** Ayrı dizin `/Users/nadir/01dev/cdpilot-site/`, Server 21 port 3400

## Aktif Çalışma
| Durum | Alan | Açıklama |
|-------|------|----------|
| ✅ | v0.9.1 npm + MCP Registry | 27.09 yayında: port kaydı temizliği, Windows pid/port güvenliği, düzeltilmiş iddialar; resmi MCP Registry'de `io.github.mehmetnadir/cdpilot` aktif |
| ✅ | İddia kapıları | Site `npm test` + repo `test/test.js`: 500x / 50KB / "40+ commands" geri gelirse kırılır. a11y-snapshot token tasarrufu diye SATILMAZ (ölçüm: `.claude/docs/token-olcumu-2026-09-27.md`) |
| ✅ | Twitter bot | Alarm ntfy `bekci` kanalında; motor yalnız nemotron-3-ultra (düşünme kapalı); `pain_hunter` 13:00 + akşam slotunda canlı (günde ≤3 yanıt) |
| ⏳ | Glama sahiplenme | Nadir claim edecek → sonra punkpeye/awesome-mcp-servers'a 3. PR |
| ✅ | v0.9.2 npm + registry | 27.09: auto-launch, --timeout (#2), `open`; `stop` artık takılmıyor ve Windows'ta kullanıcı tarayıcısını öldürmüyor; headless stealth/undetected sannysoft 31/31 |
| ⏳ | v0.9.3 adayı | iframe (#1) önerildi, Nadir onayı bekliyor; CSS seçicide shadow DOM (#3) sonra; UA override `go` bağlantısıyla sınırlı (sonraki komutlar) |
| ⏳ | Sentinel takip | C6: daily_analytics gece yazmıyor (debug) · C8: 2 failed auto-like sebebi |
| ⏳ | v0.9 tls-proxy | Optional local TLS-MITM (curl-impersonate semantics) |

## Son Oturum
→ 2026-09-27: sahte kriz donması (11 gün) çözüldü, pain_hunter eklendi, "500x" benchmark geri çekildi, v0.9.1 npm + MCP Registry.
→ İlk iş: pain_hunter'ın ilk canlı kayıtlarını oku (`/opt/cdpilot-twitter-bot/pains/2026-09.jsonl`) → sonra v0.9.2.

Son Güncelleme: 2026-09-27

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
