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
| iframe hedefleme (`>>>`, `--frame`) | seçici zinciri → çerçeve içinde click/fill/type/smart-* | smart-fill/select kendiliğinden yalnız aynı kökenli çerçeveye; sayfa gerçek eşleşmesi önce gelir | canlı (0.9.3) |
| Boşta kapanma + oturum günlüğü (`cdpilot log`) | etkinlik damgası → 15 dk sonra kendi açtığı tarayıcıyı kapatır; komut başına maskeli JSON satırı | Kullanıcının başlattığı tarayıcı asla kapanmaz; sırlar diske yazılmadan maskelenir | canlı (0.9.3) |
| `connect` (açık tarayıcıya bağlan) | kullanıcının `--remote-debugging-port` ile açtığı tarayıcı → cdpilot komutları onun üzerinde; insan CAPTCHA'yı çözer, ajan sürer | Yalnız kullanıcı açıkça `connect` derse; asla kendiliğinden bağlanmaz, kapatmaz (idle close dışı); sahiplik kanıtı (GUID/pid) olmadan hiçbir tarayıcıya sinyal/Browser.close yok | canlı (0.9.4) |
| WebMCP köprüsü (`tools list/call`, MCP `browser_site_tools`) | sayfanın `document/navigator.modelContext` araçları → listele/çağır | Chrome 149-156 origin trial / bayrak; destek yoksa açık mesaj, çökme yok; araçlar sayfanın göremediği izole dünyada çağrılır | canlı (0.9.4) |
| Web Bot Auth kipi (`--bot-auth`) | Ed25519 anahtar + imza dizini → istekler RFC 9421 imzalı (`Signature`, `Signature-Input`, `Signature-Agent`) | Stealth'in tersi, meşru ajan kimliği; isteğe bağlı `cryptography` paketi (yoksa kurulum ipucu) | canlı (0.9.4) |
| İnsan gibi basılı tutma + kaçan tıklama çıkış kodu | gerçek fare tıklaması → 40-120 ms basılı tutma; bırakış hedefi kaçırırsa exit 3 (batch/run: hata 1 > kaçan 3 > 0) | `CDPILOT_PRESS_MS=0-0` eski anlık davranış; MCP'de `{"clicked":false}` yalnız tıklama araçlarında | canlı (0.9.4) |
| Dağıtım: Claude Code eklenti mağazası + `.mcpb` | `/plugin marketplace add mehmetnadir/cdpilot`; release'e `.mcpb` eki | Sürüm alanları package.json ile testle eşit | canlı (0.9.4) |
| Chrome for Testing (`browser install chrome-for-testing`) | Google'ın resmi test sürümü → `~/.cdpilot/browsers/`; eklenti işinde markalı Chrome yerine seçilir | Yalnız açık komutla indirir (~150 MB), kendiliğinden indirmez; gizlilik (stealth) için değil, eklenti geliştirme için | canlı (0.9.4) |
| Örnekler (`examples/`) | her özellik için çalışan betik + gerçek koşu çıktısı + cdpilot ekran görüntüsü | Çıktı elle yazılmaz; test bayatlığı yakalar (Nadir 28.09: özellikler kendi örneğimizle anlatılır) | canlı (0.9.4) |
| Eklenti API v1 (`cdpilot plugins`, `cdpilot.plugins` entry point) | ayrı pip paketleri → yeni komut, MCP aracı, karar sağlayıcı | Çekirdek bağımlılıksız kalır; yalnız açıkça kurulan paketler, cwd'den yükleme yok; yerleşik komut gölgelenemez; `CDPILOT_NO_PLUGINS=1` | planlı — `plan-eklenti-api-ve-jev.md` |
| `cdpilot-jev` eklentisi (`decide page-state/pick/fields/verify`) | kırpılmış sayfa durumu → TypeSafe Jev tipli karar (sağlayıcı parametrik: jev / systemone / heuristic) | Sayfa içeriği üçüncü tarafa gider (ilk kullanımda onay, `--dry-run`); "daha hızlı" iddiası yalnız ölçüm kapısını geçerse | planlı — ölçüm kapısı önce |

## Veri ve Sınırlar

- **Kaynaklar:** Yalnız yerel dosya sistemi (`~/.cdpilot/`) + hedef tarayıcının CDP endpoint'i. Harici sunucu/DB yok.
- **Yasaklar:** Kullanıcının gerçek tarayıcı profiline kendiliğinden dokunmaz (tek istisna: kullanıcının açıkça çağırdığı `connect`); CDP `127.0.0.1` dışına açılmaz; zorunlu runtime bağımlılık eklenmez (yalnız stdlib + Python `websockets`). İsteğe bağlı paket (`try/except ImportError`, yoksa kurulum ipucu) Nadir kararıyla serbest (28.09: Web Bot Auth için `cryptography`).
- **Rationale (anomaliler):** `websockets` "zero-dependency" iddiasına rağmen gerçek bir Python runtime bağımlılığıdır — npm paketine girmez (yalnız `bin/`, `src/cdpilot.py`, README, LICENSE), `cdpilot setup` ilk çalıştırmada pip ile kurar. Bu, iddia ile çelişmiyor: "zero dependency" npm tarafı için doğru.

## Yapılmayacaklar

- HAR export — issue #4 açık, hiç başlanmadı.
- `CDPILOT_POOL_SIZE` (çoklu-instance havuzu) — README'den 2026-09-27'de kaldırıldı (hiç kodlanmamıştı), roadmap'te planlı.

## Açık Kararlar (Nadir'e)

- `serve --api` kodda çalışıyor ama README/`--help`'te yok — belgeye eklensin mi, bilinçli mi gizli? (`test`/`trace` 0.9.1'de README'ye girdi.)
- MCP Registry yayını release ile otomatik (0.9.1'de ilk kez oldu); ayrı onay noktası istenirse publish.yml'e environment onayı eklenir.
- 0.9.4 kapsamı (Nadir 28.09 onayladı): `connect`, WebMCP köprüsü, Web Bot Auth, iframe'de `Runtime.enable` izinin kaldırılması. Shadow DOM CSS (#3) sonra.
