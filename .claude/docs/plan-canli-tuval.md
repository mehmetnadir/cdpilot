# Canlı tuval — `cdpilot canvas` (PRD taslağı, Nadir kararına)

Durum: TASLAK, 08.11.2026. Nadir'in sözü (08.11): "LLM'lerin bir tarayıcı sekmesinde canlı canlı yaptıkları kodlamalarının
anında canlı uygulamalara dönüşmesi … insanların Google'da yaptıkları aramaları görsel arayüzlere dönüştürmek isteyenlere
altyapı … biz de kullanırız." Kod yazılmadı; bu belge karar içindir (TURN_KEY_LIFECYCLE: araştırma → PRD → onay → kod).

## 1. Ne

Bir LLM'in (ya da betiğin) ürettiği HTML/CSS/JS'i, kullanıcı hiçbir şey kurmadan, tek komutla açık bir sekmeye anında
basan ve sekmedeki etkileşimi geri okuyan altyapı. Ölçülebilir vaat: **son token → ilk boyama ≤ 100 ms.** Tarayıcı
statik sayfayı 12–20 ms'de boyuyor (perf-taban), kalan bütçe iletim ve DOM yamasıdır.

```
LLM / betik ──stdout──▶ cdpilot canvas stream ──CDP──▶ tuval sekmesi (DOM yaması, durum korunur)
                                 ▲                          │
                                 └──── canvas events ◀──────┘  (tık, form, seçim: JSON satırı)
```

## 2. v0 kapsamı (yalnız bunlar)

| Komut | İş | Üzerine kurulduğu şey |
|---|---|---|
| `canvas open [--name n]` | Tuval sekmesi açar (boş belge + gömülü yama/olay betiği), kimliğini kaydeder | `new-tab`, `_mark_owned_tab`, profil dosyaları |
| `canvas set <dosya\|->` | Belgeyi tamamen değiştirir (`Page.setDocumentContent` ya da `document.open/write`) | `cdp_send` |
| `canvas patch <dosya\|->` | Yeni HTML'i mevcut DOM'a yamar: odak, kaydırma, form değerleri, açık `<details>` korunur | gömülü morph betiği (~300 satır JS, `WEBMCP_*_JS` gibi dize) |
| `canvas stream` | stdin'i token token okur, 50 ms sessizlikte ya da kapanış etiketinde yamar (canlı kodlama görüntüsü) | `patch` + tek uzun istek |
| `canvas watch <dosya>` | Dosya değişince yamar (editörden canlı önizleme) | `patch` + mtime döngüsü |
| `canvas events [--follow]` | Sekmedeki etkileşimleri JSON satırı basar: `{"type":"click","action":"...","data":{...}}` | `Runtime.addBinding` ya da yoklama |
| `canvas close` | Tuvali kapatır | `close-tab` |

Dışarıda (v1+): çoklu tuval, paylaşımlı URL (başkasının görmesi), sunucu kipi (`serve` ile birleşik), MCP araçları
(`browser_canvas_set/patch/events`), ekran kaydı.

## 3. Kullanım örnekleri

```bash
cdpilot canvas open --name arama
claude -p "Şu arama sonuçlarını tek sayfa karşılaştırma tablosu olarak HTML yaz: ..." | cdpilot canvas stream
cdpilot canvas events --follow      # kullanıcı "Fiyata göre sırala"ya tıkladı → LLM'e geri beslenir
```

```bash
# editörden canlı önizleme
cdpilot canvas open && cdpilot canvas watch ./taslak.html
```

## 4. Ölçüm ve kapılar

| Kapı | Hedef | Nasıl ölçülür |
|---|---|---|
| Son token → ilk boyama | ≤ 100 ms (p50), ≤ 200 ms (p95) | `stream` son baytın `monotonic` damgası; sayfada `requestAnimationFrame` sonrası `performance.now()` → `events` ile geri |
| `patch` sonrası durum | odak, kaydırma, form değeri, `<details>` açık/kapalı korunur | fixture sayfa + CI e2e |
| `set` tam değişim | 20 KB belge ≤ 50 ms | aynı ölçüm |
| Bozuk/yarım HTML | yama hata vermez, son geçerli duruma kadar basar | fixture |
| Bellek | 1.000 yama sonrası sekme belleği ≤ 2× başlangıç | `Performance.getMetrics` |

Taze süreçle de çalışır (`stream`/`watch` tek uzun istek); `set`/`patch` ardışık çağrılarda daemon kazancı ~150 ms.

## 5. Güvenlik (karar ister)

LLM'in yazdığı JS tuval sekmesinde çalışır. Varsayılan öneri:

| Konu | Öneri | Alternatif |
|---|---|---|
| Köken | `about:blank` türevi, çerez yok, depolama yok | `file://` (yerel dosya okur, istenmez) |
| Ağ | CSP `connect-src 'none'`; `--allow-net <host>` ile açılır | tamamen serbest (sızıntı riski) |
| Betik | satır içi betik serbest (uygulama olmaz yoksa), `eval` serbest | betik yasak = yalnız görsel sayfa |
| Dış kaynak | `img-src data: https:`; `script-src` yalnız satır içi | CDN'e izin (`--allow-cdn`) |
| Tuval → CLI | `events` yalnız `data-action`/form olaylarını taşır, serbest metin 1 KB kesilir | tüm DOM olayları |

Günlük: `canvas` komutları oturum günlüğüne girer; stdin'den gelen HTML günlüğe YAZILMAZ (boyut + sır riski), yalnız uzunluk.

## 6. Var olan çözüm sorusu (hesaplamadan-önce §0)

| İhtiyaç | Var mı | Karar |
|---|---|---|
| Sekme aç/kapat, sahiplik | `new-tab`, `close-tab`, `_mark_owned_tab` | kullan |
| Sayfaya JS enjekte | `eval`, `WEBMCP_*_JS` dize kalıbı | kullan |
| DOM yaması | yok | gömülü morph betiği; aday referanslar idiomorph/morphdom (MIT); bağımlılık eklenmez, ölçülerek ~300 satır yerel sürüm |
| Olay geri okuma | yok (`observe` DOM gözler, etkileşim değil) | `Runtime.addBinding` ile `window.__cdpilotCanvas.emit` |
| Akış ayrıştırma | yok | tolerant HTML: kapanmamış etiketi tarayıcı tamamlar; yalnız "sessizlik ya da kapanış etiketi" tetiği |
| Dosya izleme | `watch` (ekran yayını, farklı iş) | mtime döngüsü 100 ms, ad çakışmasın: `canvas watch` |

## 7. İş ve süre tahmini

| Adım | Süre | Kim |
|---|---|---|
| Morph betiği + fixture testleri (durum koruma) | 1 gün | agy-filo `kod` (spec şef) |
| `canvas open/set/patch/close` + e2e | 0,5 gün | şef |
| `stream`/`watch` + ölçüm betiği | 0,5 gün | şef |
| `events` (addBinding) + örnek LLM döngüsü (`examples/canvas/`) | 0,5 gün | şef |
| Güvenlik gözden geçirme (CSP, köken) | 0,5 gün | reviewer |

## 8. Nadir'e sorular

1. v0'a başlayalım mı, yoksa önce Faz 3 (gözlem çıktısında token azaltma) mı?
2. Güvenlik varsayılanı: ağ kapalı + satır içi betik serbest (öneri) kabul mü?
3. Hedef ölçü "son token → ilk boyama ≤ 100 ms" yeterli mi, yoksa "kullanıcı tıkı → LLM cevabı → yeniden boyama" döngüsü de
   ölçülsün mü (LLM gecikmesi bizim değil)?
4. MCP araçları v0'a girsin mi (Claude Code içinden `browser_canvas_stream`)?
