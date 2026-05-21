# cdpilot — Mimari ve CLI Komutları

## Mimari Diyagram

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

## Dosya Haritası (Tam)

| Yapmak İstediğin | Bakman Gereken Yer | Not |
|---|---|---|
| Yeni CLI komutu ekleme | `src/cdpilot.py` → `main()` dispatch (~satır 2460) | `cmd_` prefix |
| Tarayıcı algılama/başlatma | `src/cdpilot.py` → `_find_browser()`, `cmd_launch()` | Platform-specific yollar |
| CDP WebSocket iletişimi | `src/cdpilot.py` → `cdp_send()`, `get_page_ws()` | asyncio |
| MCP server | `src/cdpilot.py` → `class MCPServer` (~satır 2320) | stdin/stdout JSON-RPC |
| Node.js entry point | `bin/cdpilot.js` | Python bulma + browser detect |
| Cross-platform tarayıcı yolları | `bin/cdpilot.js` → `findBrowser()` | macOS, Linux, Windows |
| Oturum yönetimi | `src/cdpilot.py` → `_load_sessions()`, `_save_sessions()` | JSON dosya tabanlı |
| Request interception | `src/cdpilot.py` → `cmd_intercept()` | Fetch.enable CDP |
| Cihaz emülasyonu | `src/cdpilot.py` → `cmd_emulate()` | iPhone, iPad, Android preset |
| Geolocation override | `src/cdpilot.py` → `cmd_geo()` | Şehir preset + custom |
| Erişilebilirlik (a11y) | `src/cdpilot.py` → `cmd_a11y()` | ARIA tree, role filter |
| DevExtension sistemi | `src/cdpilot.py` → `cmd_extensions()` | Native JS injection |
| Vision fallback | `src/cdpilot.py` → `cmd_describe()` | a11y + screenshot + text |
| Annotated screenshot | `src/cdpilot.py` → `cmd_shot_annotated()` | Badge overlay |
| Auto-wait | `src/cdpilot.py` → `WAIT_AND_QUERY_JS` | MutationObserver 5s |
| Batch commands | `src/cdpilot.py` → `cmd_batch()` | JSON stdin pipe |
| Glow/VFX sistemi | `src/cdpilot.py` → `GLOW_CSS` | Kalıcı glow, cursor, ripple |
| Multi-project isolation | `src/cdpilot.py` → `_allocate_port()` | Registry tabanlı |
| Duyuru içerikleri | `docs/` | blog, twitter, HN, reddit |
| Testler | `test/test.js` | Node.js tabanlı |
| npm paket yapılandırması | `package.json` → `files`, `bin` | Yayınlanan: bin/, src/, README |

## Versiyon Özellikleri

| Versiyon | Özellik |
|---|---|
| v0.5.0 | Stealth, Adaptive Escalation, Auto-Dismiss, Cookies save/load, Context Pool, Efficient Mode, WS Pool, wait-for-text, eval-batch, block |
| v0.6.1 | Cookies safe-host scoping |
| v0.6.2 | Per-task wipe (wipe komutu) |
| v0.7.0 | Residential proxy framework |
| v0.8.0 | TLS fingerprint probe (cdpilot tls-check) |
| v0.9 (planned) | Optional local TLS-MITM |

## Teknik Notlar

- **İletişim:** Pure HTTP + WebSocket (urllib + asyncio)
- **Profil:** `~/.cdpilot/profile` — izole, kişisel tarayıcıdan bağımsız
- **MCP:** JSON-RPC over stdin/stdout, Claude Code uyumlu
- **Stealth smart no-op:** `navigator.webdriver` patch'i sadece value=true ise devreye girer
- **CDP detection:** `incolumitas.overflowTest` ve `fpscanner.WEBDRIVER` aşılamaz — kabul edilen sınır
- **Glow kalıcılığı:** `_control_end` glow+vfx'i yeni sayfaya re-inject eder, 10s sonra timeout
