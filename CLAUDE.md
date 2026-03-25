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
| ✅ | Core CLI | 40+ komut, cross-platform |
| ✅ | MCP Server | Claude Code entegrasyonu |
| ✅ | DevExtension | Native JS injection sistemi |
| ✅ | GitHub & npm | v0.1.2 yayınlandı, demo GIF, badge'ler |
| ⏳ | npm 0.1.3 | Cross-platform iyileştirmeler |

## Dikkat Edilecekler (Gotchas)

- **Tek dosya mimari:** Tüm Python kodu `src/cdpilot.py` içinde (~2600 satır), modüllere bölünmemiş
- **Sıfır bağımlılık kuralı:** Harici Python/npm paketi eklenmez — stdlib only
- **Port 9222:** Varsayılan CDP portu, `CDP_PORT` env ile değişir
- **Brave öncelikli:** Tarayıcı arama sırası: Brave > Chrome > Chromium
- **Python 3 zorunlu:** `bin/cdpilot.js` Python3 bulamazsa hata verir
- **İzole profil:** `~/.cdpilot/profile` — kullanıcının kişisel tarayıcısına dokunulmaz
- **MCP screenshot güvenliği:** Dosya adları sanitize edilir, path traversal engellenir

## İlgili Dosyalar

| Dosya | Amaç |
|-------|------|
| `CONTRIBUTING.md` | Katkı rehberi |
| `LICENSE` | MIT lisansı |
| `cdpilot-demo.gif` | README'deki demo animasyonu |
| `cdpilot-video.mp4` | Tam demo videosu (1080x1080, 30fps) |

---
Son Güncelleme: 2026-03-16

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
