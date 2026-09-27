[SÖZLEŞME: TASLAK]
<!-- ONAYLI'ya yalnız Nadir geçirir. TASLAK iken bloklama yok, sadece hatırlatma. -->

# cdpilot — Proje Sözleşmesi

## İş

Zero-dependency tarayıcı otomasyon CLI'ı — Puppeteer/Playwright/Selenium yerine
doğrudan Chrome DevTools Protocol (CDP) üzerinden HTTP/WebSocket konuşur. İki
kullanıcı sınıfı: (1) terminalden elle komut çalıştıran geliştirici, (2) `cdpilot
mcp` üzerinden AI ajanı (Claude Code dahil). npm paketi + GitHub deposu olarak
dağıtılır; ayrı bir SaaS/panel yok.

## İşlevler

| Ad | Girdi → Çıktı | Sınır | Durum |
|---|---|---|---|
| CLI (`npx cdpilot <komut>`) | komut adı + args → stdout/JSON | Yalnız `127.0.0.1` CDP, izole profil (`~/.cdpilot/profile`) | canlı |
| MCP server (`cdpilot mcp`) | stdio JSON-RPC → CLI komutlarının bir alt kümesi tool olarak | AI ajanına CDP kontrolü verir, kullanıcı tarayıcısına dokunmaz | canlı |
| `serve --api` (Browserbase-uyumlu local API) | HTTP `/v1/sessions` → CDP URL | Kodda var, README/`--help`'te belgesiz (2026-09-27 tespiti) | canlı ama belgesiz |
| `test` / `trace` (test runner) | `*.cdpt.js` → pass/fail + trace bundle | Kodda var, README/`--help`'te belgesiz (2026-09-27 tespiti) | canlı ama belgesiz |
| npm publish (`.github/workflows/publish.yml`) | GitHub Release → npm + (v0.9.1'den itibaren) MCP Registry | OIDC trusted publisher; `mcp-publisher` v1.8.1 sabit | canlı |

## Veri ve Sınırlar

- **Kaynaklar:** Yalnız yerel dosya sistemi (`~/.cdpilot/`) + hedef tarayıcının CDP endpoint'i. Harici sunucu/DB yok.
- **Yasaklar:** Kullanıcının gerçek tarayıcı profiline dokunmaz; CDP `127.0.0.1` dışına açılmaz; runtime bağımlılık eklenmez (yalnız stdlib + Python `websockets`).
- **Rationale (anomaliler):** `websockets` "zero-dependency" iddiasına rağmen gerçek bir Python runtime bağımlılığıdır — npm paketine girmez (yalnız `bin/`, `src/cdpilot.py`, README, LICENSE), `cdpilot setup` ilk çalıştırmada pip ile kurar. Bu, iddia ile çelişmiyor: "zero dependency" npm tarafı için doğru.

## Yapılmayacaklar

- iframe içi `click`/`fill`/`type` — issue #1 açık, hiç başlanmadı.
- HAR export — issue #4 açık, hiç başlanmadı.
- `CDPILOT_POOL_SIZE` (çoklu-instance havuzu) — README'den 2026-09-27'de kaldırıldı (hiç kodlanmamıştı), roadmap'te planlı.

## Açık Kararlar (Nadir'e)

- `cdpilot test`/`trace` ve `serve --api` kodda çalışıyor ama README/`--help`'te hiç yok — belgeye eklensin mi, yoksa bilinçli mi gizli tutuluyor (ör. olgunlaşmamış API)?
- MCP Registry'ye ilk gerçek yayın (`mcp-publisher publish`) şef onayı sonrası mı yoksa otomatik mi olacak — publish.yml `release: published` tetikleyicisiyle otomatik çalışacak, bilinçli onay noktası yok.
