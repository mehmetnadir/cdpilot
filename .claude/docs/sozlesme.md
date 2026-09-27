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
| npm publish (`.github/workflows/publish.yml`) | GitHub Release → npm + MCP Registry | OIDC trusted publisher; `mcp-publisher` v1.8.1 sabit; npm adımı yayınlı sürümü atlar, `workflow_dispatch` ile yarım kalan registry yarısı tamamlanır | canlı (ilk registry yayını 0.9.1, 2026-09-27) |
| X botu @cdpilot_dev (`xbot/`, srv21 `/opt/cdpilot-twitter-bot`) | systemd `cdpilot-cycle` → gönderi kuyruğu, mention yanıtları, `pain_hunter` sorun avı | Yanıt günde ≤3, cdpilot adı ≤1; kanıtsız iddia/sızıntı lint'i; alarm ntfy `bekci`; kriz donması 48 sa'te kendiliğinden kalkar | canlı |
| Site (`/Users/nadir/01dev/cdpilot-site`, srv21 port 3400) | Next.js → cdpilot.ndr.ist, `/compare`, `/llms.txt`, blog | `npm test` iddia kapısı: ölçülmemiş sayı yayınlanmaz | canlı |

## Veri ve Sınırlar

- **Kaynaklar:** Yalnız yerel dosya sistemi (`~/.cdpilot/`) + hedef tarayıcının CDP endpoint'i. Harici sunucu/DB yok.
- **Yasaklar:** Kullanıcının gerçek tarayıcı profiline dokunmaz; CDP `127.0.0.1` dışına açılmaz; runtime bağımlılık eklenmez (yalnız stdlib + Python `websockets`).
- **Rationale (anomaliler):** `websockets` "zero-dependency" iddiasına rağmen gerçek bir Python runtime bağımlılığıdır — npm paketine girmez (yalnız `bin/`, `src/cdpilot.py`, README, LICENSE), `cdpilot setup` ilk çalıştırmada pip ile kurar. Bu, iddia ile çelişmiyor: "zero dependency" npm tarafı için doğru.

## Yapılmayacaklar

- iframe içi `click`/`fill`/`type` — issue #1 açık, hiç başlanmadı.
- HAR export — issue #4 açık, hiç başlanmadı.
- `CDPILOT_POOL_SIZE` (çoklu-instance havuzu) — README'den 2026-09-27'de kaldırıldı (hiç kodlanmamıştı), roadmap'te planlı.

## Açık Kararlar (Nadir'e)

- `serve --api` kodda çalışıyor ama README/`--help`'te yok — belgeye eklensin mi, bilinçli mi gizli? (`test`/`trace` 0.9.1'de README'ye girdi.)
- MCP Registry yayını release ile otomatik (0.9.1'de ilk kez oldu); ayrı onay noktası istenirse publish.yml'e environment onayı eklenir.
- v0.9.2 kapsamı: yalnız bağlantı dayanıklılığı (#2) mı, iframe (#1) / shadow DOM seçici (#3) de mi?
