# cdpilot

> Zero-dependency browser automation CLI. Tek komut, tam kontrol.

## Kimlik

- **Stack:** Node.js (entry) + Python 3 (core) | Pure CDP over HTTP/WebSocket
- **Port:** CDP: 9222 (varsayılan, `CDP_PORT` ile değiştirilebilir)
- **Paket Yöneticisi:** npm
- **Monorepo:** Hayır — tek modül
- **Bağımlılık:** Sıfır (npm + Python stdlib)

## Hızlı Başlangıç

- `npx cdpilot launch` — Tarayıcı başlat (CDP modunda)
- `npx cdpilot setup` — Otomatik tarayıcı algılama, profil oluşturma
- `npx cdpilot status` — Bağlantı kontrolü
- `node test/test.js` — Test çalıştır
- `npm publish` — npm'e yayınla

## Dosya Haritası (Nereye Bakmalısın?)

> **EN KRİTİK BÖLÜM.** "X yapmak istiyorum" → "Y'ye bak"

| Yapmak İstediğin | Bakman Gereken Yer | Not |
|---|---|---|
| Yeni CLI komutu ekleme | `src/cdpilot.py` → `main()` dispatch (~satır 2460) | `cmd_` prefix convention |
| Tarayıcı algılama/başlatma | `src/cdpilot.py` → `_find_browser()`, `cmd_launch()` | Platform-specific yollar |
| CDP WebSocket iletişimi | `src/cdpilot.py` → `cdp_send()`, `get_page_ws()` | asyncio tabanlı |
| MCP server (AI entegrasyonu) | `src/cdpilot.py` → `class MCPServer` (~satır 2320) | stdin/stdout JSON-RPC |
| Node.js entry point | `bin/cdpilot.js` | Python bulma + browser detect + delegate |
| Cross-platform tarayıcı yolları | `bin/cdpilot.js` → `findBrowser()` | macOS, Linux, Windows |
| Oturum yönetimi | `src/cdpilot.py` → `_load_sessions()`, `_save_sessions()` | JSON dosya tabanlı |
| Request interception | `src/cdpilot.py` → `cmd_intercept()`, `_run_intercept_session()` | Fetch.enable CDP |
| Cihaz emülasyonu | `src/cdpilot.py` → `cmd_emulate()` | iPhone, iPad, Android preset |
| Geolocation override | `src/cdpilot.py` → `cmd_geo()` | Şehir preset + custom koordinat |
| Erişilebilirlik (a11y) | `src/cdpilot.py` → `cmd_a11y()` | ARIA tree, role filter |
| DevExtension sistemi | `src/cdpilot.py` → `cmd_extensions()`, `cmd_ext_install()` | Native JS injection |
| Vision fallback | `src/cdpilot.py` → `cmd_describe()` | a11y + screenshot + text |
| Annotated screenshot | `src/cdpilot.py` → `cmd_shot_annotated()` | Badge overlay |
| Auto-wait | `src/cdpilot.py` → `WAIT_AND_QUERY_JS` | MutationObserver 5s |
| Batch commands | `src/cdpilot.py` → `cmd_batch()` | JSON stdin pipe |
| Glow/VFX sistemi | `src/cdpilot.py` → `GLOW_CSS`, `VISUAL_FEEDBACK_JS` | Kalıcı glow, cursor, ripple |
| Multi-project isolation | `src/cdpilot.py` → `_allocate_port()`, `_resolve_project_config()` | Registry tabanlı |
| Duyuru içerikleri | `docs/` → blog, twitter, HN, reddit | Hazır, yayınlanacak |
| Site kaynak kodu | `/Users/nadir/01dev/cdpilot-site/` | Ayrı repo |
| Rakip analizi | `.claude/docs/browserless-analysis.md` | Browserless deep dive |
| Testler | `test/test.js` | Node.js tabanlı, basit assertions |
| npm paket yapılandırması | `package.json` → `files`, `bin` | Yayınlanan dosyalar: bin/, src/, README |

## Mimari Özet

```
bin/cdpilot.js (Node.js entry)
    │
    ├── Python kontrolü (python3 arama)
    ├── Tarayıcı algılama (Brave > Chrome > Chromium)
    └── → spawn python3 src/cdpilot.py <komut> <args>

src/cdpilot.py (~2600 satır, TEK DOSYA)
    │
    ├── CDP iletişim katmanı (HTTP + WebSocket)
    │   ├── cdp_get() — HTTP GET (tab listesi vb.)
    │   ├── cdp_send() — WebSocket komutları
    │   └── navigate_collect() — Sayfa yükleme + veri toplama
    │
    ├── 40+ CLI komutu (cmd_* fonksiyonları)
    │   ├── Navigasyon: go, content, html, shot, pdf
    │   ├── Etkileşim: click, fill, type, submit, hover, drag, keys
    │   ├── Debug: console, network, perf, eval, debug
    │   ├── Tab: tabs, new-tab, switch-tab, close-tab
    │   ├── Ağ: throttle, proxy, intercept
    │   ├── Emülasyon: emulate, geo, permission
    │   └── Gelişmiş: cookies, storage, upload, a11y, frame, dialog
    │
    ├── Oturum yönetimi (izole profil)
    └── MCP Server (class MCPServer — stdin/stdout)

Brave/Chrome/Chromium (CDP modu, port 9222)
    └── --remote-debugging-port=9222
        --user-data-dir=~/.cdpilot/profile
```

- **İletişim:** Pure HTTP + WebSocket (urllib + asyncio)
- **Profil:** `~/.cdpilot/profile` — izole, kişisel tarayıcıdan bağımsız
- **MCP:** JSON-RPC over stdin/stdout, Claude Code uyumlu

## Aktif Çalışma

| Durum | Alan | Açıklama |
|-------|------|----------|
| ✅ | Core CLI | 50+ komut, cross-platform |
| ✅ | MCP Server | Claude Code entegrasyonu + browser_describe tool |
| ✅ | DevExtension | Native JS injection sistemi |
| ✅ | Visual Feedback | Yeşil glow (kalıcı), cursor, ripple, keystroke, AI uyarı toast |
| ✅ | Multi-Project | Proje bazlı izole tarayıcı (otomatik port/profil) |
| ✅ | A11y Snapshot | Yapılandırılmış a11y tree + @ref click |
| ✅ | Vision Fallback | describe komutu (a11y + screenshot + text) |
| ✅ | Annotated Shot | Screenshot üzerinde @N badge'leri |
| ✅ | Auto-Wait | 5s MutationObserver bekleme |
| ✅ | Batch Commands | JSON pipe desteği |
| ✅ | Site | cdpilot.ndr.ist canlı (landing + 61 komut docs) |
| ✅ | GitHub & npm | v0.1.2 yayınlandı, 6 awesome repo PR'ı |
| 🔄 | Stealth Mode | Premium tier - insan benzeri davranış (roadmap) |
| 🔄 | cdpilot Cloud | Hosted browser sessions API (roadmap) |
| ⏳ | npm 0.2.0 | Yeni özelliklerle versiyon yükseltme |

## Dikkat Edilecekler (Gotchas)

- **Tek dosya mimari:** Tüm Python kodu `src/cdpilot.py` içinde (~2600 satır), modüllere bölünmemiş
- **Sıfır bağımlılık kuralı:** Harici Python/npm paketi eklenmez — stdlib only
- **Port 9222:** Varsayılan CDP portu, `CDP_PORT` env ile değişir
- **Brave öncelikli:** Tarayıcı arama sırası: Brave > Chrome > Chromium
- **Python 3 zorunlu:** `bin/cdpilot.js` Python3 bulamazsa hata verir
- **İzole profil:** `~/.cdpilot/profile` — kullanıcının kişisel tarayıcısına dokunulmaz
- **MCP screenshot güvenliği:** Dosya adları sanitize edilir, path traversal engellenir
- **Glow kalıcılığı:** `_control_end` glow+vfx'i yeni sayfaya re-inject eder, persistent script 10s sonra JS timeout ile temizlenir
- **Multi-project:** `CDPILOT_PROJECT_ID` env var'ı Node→Python aktarılır, `_get_project_id()` bunu öncelikli okur
- **cdpilot-site:** Ayrı dizin `/Users/nadir/01dev/cdpilot-site/`, Server 21'de port 3400

## İlgili Dosyalar

| Dosya | Amaç |
|-------|------|
| `CONTRIBUTING.md` | Katkı rehberi |
| `LICENSE` | MIT lisansı |
| `cdpilot-demo.gif` | README'deki demo animasyonu |
| `cdpilot-video.mp4` | Tam demo videosu (1080x1080, 30fps) |

---
Son Güncelleme: 2026-03-28

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
