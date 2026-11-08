> **Conductor:** Bu projeye global orkestrasyon kuralları otomatik uygulanır.
> Routing · Agent seçimi · Review pipeline → `~/.claude/CLAUDE.md` üzerinden yüklenir.
> Bu dosya yalnızca projeye özgü bağlamı içerir — global kuralları tekrar yazmayın.

# cdpilot

> Zero-dependency browser automation CLI. Tek komut, tam kontrol.

## Kimlik
- **Stack:** Node.js (entry) + Python 3 (core) | Pure CDP over HTTP/WebSocket
- **Port:** CDP 9222 (varsayılan, `CDP_PORT` ile değiştirilebilir)
- **Paket Yöneticisi:** npm | **Bağımlılık:** 0 npm; Python `websockets` (sihirbaz kurar), isteğe bağlı `cryptography` (Web Bot Auth)

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
- **Bağımlılık eklenmez:** npm 0; Python yalnız `websockets` (+ isteğe bağlı `cryptography`). README "zero dependency" demez, "zero npm dependencies" der (06.11 vaat denetimi)
- **Port 9222:** Varsayılan CDP, `CDP_PORT` env ile değişir
- **Tarayıcı seçimi `auto` (varsayılan):** eklenti yoksa Chrome; `ext-install` ile eklenti kayıtlıysa Brave/Vivaldi (Chrome 137+ paketlenmemiş eklentiyi yüklemiyor); macOS 26'da Brave geri sırada — sebebi `cdpilot browser status` söyler
- **İzole profil:** `~/.cdpilot/profile` — kullanıcı tarayıcısına dokunulmaz
- **Stealth session-bound:** `Page.addScriptToEvaluateOnNewDocument` WS kapanınca silinir
- **cdpilot-site:** Ayrı dizin `/Users/nadir/01dev/cdpilot-site/`, Server 21 port 3400

## Aktif Çalışma
| Durum | Alan | Açıklama |
|-------|------|----------|
| ✅ | v0.9.1 npm + MCP Registry | 27.09 yayında: port kaydı temizliği, Windows pid/port güvenliği, düzeltilmiş iddialar; resmi MCP Registry'de `io.github.mehmetnadir/cdpilot` aktif |
| ✅ | İddia kapıları | Site `npm test` + repo `test/test.js`: 500x / 50KB / "40+ commands" geri gelirse kırılır. a11y-snapshot token tasarrufu diye SATILMAZ (ölçüm: `.claude/docs/token-olcumu-2026-09-27.md`) |
| ✅ | Twitter bot | Alarm ntfy `bekci` kanalında; motor yalnız nemotron-3-ultra (düşünme kapalı); `pain_hunter` 13:00 + akşam slotunda canlı (günde ≤3 yanıt) |
| ⏳ | Glama sahiplenme | Claim edildi; Dockerfile formu + Make Release bekliyor (Nadir erteledi) → sonra punkpeye/awesome-mcp-servers'a 3. PR |
| ✅ | v0.9.2 npm + registry | 27.09: auto-launch, --timeout (#2), `open`; `stop` artık takılmıyor ve Windows'ta kullanıcı tarayıcısını öldürmüyor; headless stealth/undetected sannysoft 31/31 |
| ✅ | v0.9.3 | 28.09: iframe (#1, `>>>` / `--frame`, cross-origin dahil; 3 tur review), boşta kendiliğinden kapanma (`CDPILOT_IDLE_CLOSE`), oturum günlüğü (`cdpilot log`, maskeli), Windows boruda UTF-8; CI'da gerçek tarayıcı e2e işi |
| ✅ | v0.9.4 | 29.09: connect (kendi tarayıcın, sahiplik kanıtı), WebMCP köprüsü, Web Bot Auth (Cloudflare canlı doğruladı), insan gibi basılı tutma + exit 3, OOPIF fare yönlendirme düzeltmesi, Chrome for Testing, Claude Code eklenti mağazası + .mcpb, `examples/` (gerçek çıktılı) |
| ⏳ | Eklenti API + cdpilot-jev | plan: `.claude/docs/plan-eklenti-api-ve-jev.md` (ölçüm kapısı önce) |
| ⏳ | v0.9.5 (main'de, push/PR/npm onayı bekler) | 08.11: shadow DOM (#3, `>>>` + derin geri düşüş), record/replay (#5, sırlar diske yazılmaz), HAR 1.2 (#4, maskeli), MCP `--tools core` (45→11 araç), bot-auth lsof düzeltmesi (macOS 26), MCP `--har` enjeksiyon kapısı, vaat denetimi; tutanak TT-20261108-032740-36a312 593/593; e2e yalnız CI; redact şeridi (kayıt maskesi) sürüyor |
| ⏳ | Sonraki | UA override `go` bağlantısıyla sınırlı; `--entropy=on` click ayrıca `el.click()` → çift tıklama; frame act bulamazsa sayfaya dönüş; perf tabanı (`.claude/docs/perf-taban-<tarih>.md`); oynak press-hold zamanlama testi |
| ⏳ | Sentinel takip | C6: daily_analytics gece yazmıyor (debug) · C8: 2 failed auto-like sebebi |
| ⏳ | v0.9 tls-proxy | Optional local TLS-MITM (curl-impersonate semantics) |

## Son Oturum
→ 2026-11-08 (gece, CEO kipi): 4 şerit birleşti, T1 güvenlik incelemesi (0 HIGH/MEDIUM, 2 düşük → 1 düzeltildi, 1 şerit), tutanak 593/593. Devir notu: `.claude/docs/devir-notu-2026-11-06.md`.
→ İlk iş: `lane/redact` şeridini incele + birleştir; Nadir kararları devir notu §4 (push/PR/npm, site deploy a25cee1, srv21 token, T2 denetim zamanı).

Son Güncelleme: 2026-11-08

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
