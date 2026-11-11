# Tuval güvenlik incelemesi 2 — 11.11.2026 (Claude Opus, salt okuma, d78063d)

Sonuç: **BİRLEŞME: EVET.** YÜKSEK yok, erişilebildiği kanıtlanmış ORTA yok. Önceki turun bulguları (ORTA-1a–d, ORTA-2a–d,
D1–D9) düzeldi; düzeltmeler yeni aşma yolu açmıyor. İnceleyen önerisi: jüriden önce O-1, D-3, D-4 vektörleri K9'a girsin.

| ID | Ciddiyet | Yer | Özet | Erişilir mi |
|---|---|---|---|---|
| O-1 | ORTA | CSP `src/cdpilot.py:23868-23876`, vektör listesi `test/canvas_fake_cdp.py:1206-1223` | `<script type="speculationrules">` prefetch'i: satır içi kural CSP'den geçer; prefetch tarayıcı sürecinden çıkarsa Fetch ve CSP görmez. Öneri: vektör (loopback hedef) + `Preload.enable`; savunma: bağlama ölü vekil (`createBrowserContext{proxyServer, proxyBypassList}`) | ölçülmedi |
| D-1 | DÜŞÜK | `24623-24641`, `23850` | `set` içinde `reset` bağlama bağlı, `Page.setDocumentContent{frameId}` değil; dar pencere. Öneri: `loaderId` bağı ya da bağlamda `document.write` | erişilir, zararsız (CSP + sandbox miras) |
| D-2 | DÜŞÜK | `24515-24537` | Kanıt "URL + bağlam"; `javascript:` sonucu belge geçer. D-1 ile aynı çare | erişilir, zararsız |
| D-3 | DÜŞÜK | `exfil.html:127-129`, `23892` | `webrtc_iframe` korumalı 0 ama sebep sandbox (contentWindow SecurityError); alt çerçevenin kendi betiği denenmedi. Öneri: srcdoc + sandbox türevleri; savunma: sayfa oturumunda `setAutoAttach` | muhtemelen erişilmez, ölçülmedi |
| D-4 | DÜŞÜK | blob_nav bloğu, `24304-24375` | Türetilmiş belge (blob:, javascript:, about:blank) sandbox'ı miras almazsa `window.open` aynı bağlamda yeni hedef açar, host Fetch'i görmez. Öneri: `blob_popup`, `jsurl_popup` vektörleri; savunma: ölü vekil ya da `setDiscoverTargets` → yabancı hedefi kapat | muhtemelen miras alınır, ölçülmedi |
| D-5 | DÜŞÜK | `24329` | `X-DNS-Prefetch-Control: off` preconnect'i kapatmaz; asıl koruma OTR bağlamı (LoadingPredictor kapalı). UNMEASURABLE gerekçesi yanlış; sözleşmeye not + test | erişilmez (kaynak okuması) |
| D-6 | DÜŞÜK | `24825` | 64 MB'tan büyük yük host'u kapatır; kapanış güvenli (C1) | yalnız tuvale hizmet engeli |
| D-7 | DÜŞÜK | `24211-24250`, `25912+` | Olaylar sayfadan ajana enjeksiyon kanalı; `data.url` sayfadan. Öneri: MCP `events` çıktısında "güvenilmez sayfa verisi" | tasarım gereği |
| D-8 | DÜŞÜK | CSP `sandbox allow-scripts` | Görünür tarayıcıda tıklamayla pano yazımı, tam ekran; sözleşmede belgele | yalnız görünür tarayıcıda |

WebRTC yeni gerçeklik alanları: srcdoc / about:blank iframe açılabilir (`frame-src 'none'` engellemez); data:/blob: iframe,
`window.open` (sandbox'ta `allow-popups` yok), worker, `contentWindow` erişimi kapalı. Ağ yolları ve host süreci: ayrıntı
inceleyenin raporunda (oturum 0e783adc, 11.11 03:5x); host sürecinde bulgu yok.
