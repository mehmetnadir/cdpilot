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
| ✅ | v0.9.5 | 08.11 14:52 yayında (Nadir onayı: push + release): npm 0.9.5, GitHub release `v0.9.5` + `cdpilot.mcpb`, MCP Registry publish.yml ile. İçerik: shadow DOM (#3), record/replay (#5, kayıt maskesi = oturum günlüğü kuralları), HAR 1.2 (#4), MCP `--tools core` (45→11 araç), bot-auth lsof (macOS 26), `network -- <url>` enjeksiyon kapısı, WebMCP çerçeve araçları Chrome 156 düzeltmesi, vaat denetimi. CI 12 birim + e2e yeşil (Chrome 156); tutanak TT-20261108-144423-57d206 595/595 |
| ✅ | Hız A + daemon v1 | 08.11: runpy bytecode önbelleği + yorumlayıcı önbelleği (01f47fc, ~500 → ~270 ms); `CDPILOT_DAEMON=1` kalıcı süreç (opt-in, POSIX): `content`/`eval` ~370 → ~110 ms. Tasarım/ölçüm `.claude/docs/plan-daemon-insan-hizi.md` |
| ✅ | Faz 3 agent diff | 08.11: `agent observe --diff` + `act` diff tanımlayıcılı, sessiz `--url`, README bölümü, sahte AX ağacı testi; agent komutları daemon'da sıcak (`agent twitter` taze). Kalan: MCP `browser_agent_*` aracı yok, gerçek sayfa token ölçümü |
| ✅ | Öğrenen akış v0 | 09.11 (şef kararı D-0035): `agent act` izi → `agent flow save` → `agent run` (çapa = rol+ad+sıra, sapmada çıkış 4 + sayfa); fixture ölçümü 5.049 → 237 token, 1.655 → ~650 ms. PRD/ölçüm `.claude/docs/plan-ogrenen-akis.md`. İkinci hat aynı gün: `injection_suspect` (6 dar desen, observe/act/run). MCP `browser_agent_*` 4 araç aynı gün. Gerçek site ölçümü 10.11: HN 18.331 → 90, Wikipedia 15.474 → 136, httpbin 2.292 → 119 token, sapma 0/9 (`.claude/docs/olcum/gercek-site-token-2026-11-10.md`). Enjeksiyon korpusu 20+20: 13 → 19/20, 0 alarm |
| ✅ | v0.9.6 | 10.11 16:03 yayında (jüri kararı, Nadir onayı yok): npm 0.9.6, release `v0.9.6` + `cdpilot.mcpb`, MCP Registry. Jüri kapısından geçti (J1/J2 2. tur YAYINLA; T1 3 tur: cwd import HIGH, yer tutucu → `CDPILOT_VAR_*` sızıntısı, günlük maskesi → düzeltmeler accdb54, 17db115 + adım başına izin). Yeni: `CDPILOT_VAR_HOSTS`, origin'e bağlı yer tutucu adımı, akış/state 0600, `-c` yükleyicisi cwd'siz. Çift kip CI matris girdisi (D2 kapısı). Yayın adımları devir notu §13 |
| ✅ | v0.9.7 | 11.11 yayında (jüri 3/3 YAYINLA, D-0101; Nadir onayı yok): npm 0.9.7, release `v0.9.7` + `cdpilot.mcpb`, MCP Registry. Aday eea73f6, tutanak TT-20261111-031710-14b83c 648/648, CI 42919366892. İçerik: replay ortam değeri kuralı (`CDPILOT_VAR_*` yalnız izinli https host'ta girdi adımına; kırıcı, release notunda Changed), `injection_suspect` 2. tur (held-out-2 8/30; kör heldout-3 7/40, heldout-4 13/50), daemon Linux ~10 sn gecikmesi, smart-click değer eşlemesi, CLI yardımı agent komutları. Açık noktalar: `juri-097/acik-noktalar.md` → devir notu §16 |
| ✅ | MCP sıcak süreç | 10.11 (K-0021): `CDPILOT_DAEMON=1` ile MCP araç çağrısı sunucu sürecinde koşar (`_daemon_execute` ortak çekirdek; soket/node yok); eval/tabs/content ~400 → ~10 ms. Ölçüm `plan-daemon-insan-hizi.md` §7, betik `.claude/docs/olcum/olc-mcp.js` |
| ⏳ | Sonraki | **Canlı tuval PRD** `.claude/docs/plan-canli-tuval.md` (v0: `canvas open/set/patch/stream/watch/events`, son token → ilk boyama ≤100 ms; 4 soru Nadir'e). HIZ: daemon inceleme turu 2c2be74 + join gerilemesi c74e04d, tek evaluate eb9cd83; sıcak `go` ~230 ms = node ~125 + sessizlik 100 + Python ≤15 → havuzlu oturum (D2 #1) ertelendi (plan-daemon §6.1), kaldıraç sessizlik penceresi (Nadir kararı; SPA ölçümü 10.11: 4 site × 3, metin `go` dönüşünde yerleşmiş, `olcum/spa-settle-2026-11-10.md`); 2 hafta sonra daemon varsayılan; stealth + UA override `go` oturumuna bağlı; frame act bulamazsa sayfaya dönüş |
| ✅ | Sentinel takip | 10.11 srv21 denetimi: C6 kapandı — `analytics/<gün>.json` 29.10'dan beri her gece 22:00'de yazılıyor (analytics.log). C8 tekrar etmiyor — 2 düşen auto-like 24.08 (boş istisna) ve 04.09 (bağlantı hatası); 06–10.11 günde 8–14 başarılı, hata 0 |
| ⏳ | v0.9 tls-proxy | Optional local TLS-MITM (curl-impersonate semantics) |

## Son Oturum
→ 2026-11-11 03:30: 0.9.7 yayında (jüri 3/3, D-0101; devir notu §16). 0.9.8 hazırlığı: lane/098 (fill, bayat ref, WebMCP, D-json, enj 3. tur), tuval B2 (2. güvenlik incelemesi), observe diyeti (D-0100). Enjeksiyon 4. tur kör kazanç 0 → birleşmedi (D-0099).
→ 2026-11-10 16:10: 0.9.6 yayında (jüri kapısı, devir notu §13); site 0.9.6; X followup'ları güncel; K-0027 (D2 kapıları) açık.
→ 2026-11-10 (şef kararlarıyla, Nadir "devam et"): MCP araç çağrısı sıcak süreçte (e049878, ~400 → ~10 ms); enjeksiyon korpusu 20+20 ve desen genişletmesi (f52acc3, 13 → 19/20, 0 alarm); SPA settle + gerçek site token ölçümleri agy-filo şeritleriyle (e833c60). CI üçü de yeşil. Devir notu: `.claude/docs/devir-notu-2026-11-06.md` §11–§12.
→ 2026-11-09: öğrenen akış v0 + injection_suspect + MCP agent araçları (0114ac7, b9d7e8c, 03161c6). 2026-11-08: 5 şerit birleşti, 0.9.5 yayınlandı (§5–§7).
→ 10.11 Nadir: "benden onay almana gerek yok; bağımsız jüri onaylıyorsa hiç bekleme" → jüri kapısı `.claude/docs/juri-surum.md` (D-0040). Jüri kararları 10.11: `go` penceresi 100 ms sabit (D-0041) · daemon/MCP sıcak varsayılan en erken 24.11, kapılar K-0027 (D-0042) · canlı tuval 4 soru cevaplandı, tetik = çift kip CI + site (D-0043). Nadir'de kalan: srv21 claude-oauth-token (credential).

Son Güncelleme: 2026-11-11

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
