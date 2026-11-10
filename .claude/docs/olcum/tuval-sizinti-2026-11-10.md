# Canlı tuval — jüri ölçümleri M1–M5 (11.11.2026 00:1x)

Ortam: HeadlessChrome 152.0.7977.30 (ortak, 127.0.0.1:9333), ham CDP, `python3.13 -I .claude/docs/olcum/tuval-sizinti.py --tablo`.
Yük: başta 177, sonda 97. Ham satırlar betiğin çıktısıdır. Betiği agy-filo `tuval-olcum` şeridi (Sonnet 5.5) yazdı. Şerit kota
ve arka plan beklemesiyle raporsuz bitti. Şef betiği okudu (sinyal yalnız kendi host sürecine, `Browser.close` yok) ve koşturdu.
Kip adları: `csp` = plan K2 (başlık CSP + `sandbox allow-scripts`, yabancı istek 204) · `nocsp_*` = karşı deney (CSP yok).

| # | Ölçüm | Sonuç | Hüküm |
|---|---|---|---|
| M1 | WebRTC STUN (IP, ad, TURN) | `csp` 0 · karşı deney de 0 UDP (`gather: gathering`) | **ölçülemedi**: başsız Chrome loopback'e STUN yollamadı; karşı deney kanıt vermiyor |
| M1 | `dns-prefetch`, `preconnect` (IP ve çapraz) | `csp` 0 · karşı deney 0 | **ölçülemedi** (karşı deney sızıntı göstermedi) |
| M1 | `prefetch`/`preload` | `csp` 0 (ihlal olayı `default-src`, `connect-src`) · karşı deney acc 1–2 | sızıntı yok |
| M1 | `<a ping>` (2 biçim) | `csp` 0 (ihlal `connect-src`) · karşı deney POST /ping | sızıntı yok |
| M1 | `sendBeacon` | `csp` 0 (sayfa `true` döndü ama istek çıkmadı) · karşı deney POST /beacon | sızıntı yok |
| M1 | CSS `url()`, `<img>` | `csp` 0 (ihlal `img-src`) · karşı deney GET | sızıntı yok |
| M2 | `blob:`/`data:`/`about:blank` üst düzey gezinme (`location=`, `window.open`) | `csp`: yeni belge `SecurityError` + `fetch` engelli + ihlal olayları; acc 0 · karşı deney acc 1–3 | CSP/sandbox **miras kalıyor**, sızıntı yok. `window.open` → `null` |
| M3 | Host canlı | sekme canvas URL'sinde, acc 0 | — |
| M3 | Host **SIGKILL**, sonra `location='http://127.0.0.1:<p>/after-kill?x=secret'` | sekme kaldı; dinleyici TCP bağlantısı aldı (acc **1**) | **sızıntı yolu açık** → C1 koruması şart |
| M3 | Host SIGSTOP → SIGCONT | acc 0 | Fetch duraklamada istek tutuluyor |
| M4 | `Target.createBrowserContext{disposeOnDetach:true}` + host SIGKILL (3 tekrar) | bağlam kullanılabilir; sekme 2–3 ms içinde gitti; bağlam listede yok | **C1 koruması çalışıyor** |
| M5 | Tuval oturumunda `Fetch.enable{*}`, ikinci sıradan sekme | öteki sekmenin isteği dinleyiciye dokunulmadan ulaştı; tuval Fetch'i yalnız kendi belgesini gördü | yalıtım var |

Sonuçlar ve şerit spec'ine giren kurallar:
1. C1 için ölçülmüş yol `createBrowserContext{disposeOnDetach:true}`. Host SIGKILL'de sekme 2–3 ms'de kapanır. Bağlamsız host ölümü `location=` ile
   dışarı TCP açtırdı (M3). Şerit B bu bağlam olmadan `canvas open` yazmaz.
2. Fetch tuval oturumuna bağlı kalır (M5). Tarayıcı düzeyi `setAutoAttach` + Fetch (`_BotAuthSigner` kalıbı) yasağı ölçümle uyumlu.
3. WebRTC ve DNS önyükleme bu ortamda ölçülemedi: karşı deney de trafik üretmedi. Sızıntı fixture'ı bu vektörleri taşır ama kanıt
   sayılmaz. Gerçek ağ arayüzlü CI koşusunda yeniden denenir (açık nokta; plan §7 eksik ölçüm listesinde kalır).
4. `sendBeacon` sayfaya `true` döndürür ama istek çıkmaz. Olay sayacı sayfanın dönüş değerine değil, host'un `blocked`/ihlal kaydına bakar.

Temizlik: betiğin açtığı sekme ve bağlam kalmadı (`tabs_left: []`, `ctx_left: []`).
