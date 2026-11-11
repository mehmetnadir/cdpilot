# Tıklanabilir etkileşimsiz `agent observe` girdileri (o200k, 11.11)

> Soru: diyet etkileşimsiz girdileri gizlerse, `<div onclick>` gibi tıklanabilir öğeler kaybolur mu?
> Betik: `.claude/docs/olcum/observe-tiklanabilir.py`. Ham veri: `~/01dev/cdpilot-olcum-ham/observe-tikla-2026-11-11/` (`observe-*.json` = `agent observe` çıktısı, `olcum-*.json` = girdi başına sinyal, `ozet.json`).
> Kod değişmedi. Paylaşılan tarayıcı 127.0.0.1:9333, her sayfa kendi sekmesinde, tarayıcı kapatılmadı.

## 1. Sonuç

Tıklanabilir etkileşimsiz girdi çok az. 6 sayfada toplam 6 girdi, 82 token. Bunlar etkileşimsiz girdilerin %0,5 token payı.
En ucuz kural: **`cursor:pointer` başlatan ya da DOMSnapshot `isClickable` olan ve yerel etkileşimli bir öğenin içinde olmayan girdiyi tut.** Diyet kazancının %0,5'ini geri verir. Ek maliyet: 1 CDP çağrısı, 6–37 ms.

## 2. Yöntem

| Adım | Ne yapıldı |
|---|---|
| Girdi | Gerçek `agent observe` çıktısı (cdpilot `CDPILOT_TARGET` sekme sabitleme). Betik AX ağacını yeniden alır, `_snapshot_to_actions` mantığını kopyalar. 6/6 sayfada girdi listesi `observe` ile birebir aynı (ad + rol) |
| Etkileşimsiz | Normalleştirme sonrası rol `AGENT_INTERACTIVE_ROLES` dışında |
| Etkin öğe | Girdi düğümü metin düğümüyse üst öğesi (StaticText `backendDOMNodeId` metin düğümüdür) |
| (b) | `getComputedStyle().cursor == pointer`. `b_orig`: öğede pointer, üstünde yok |
| (c) | etiket a/button/summary/label, ya da `[role]` etkileşimli, `[tabindex]`, `[onclick]`; öğede ya da ilk 3 üstte |
| (a) | `DOMDebugger.getEventListeners` click/mousedown/pointerdown/keydown; öğede ve ilk 3 üstte |
| (d) | `DOMSnapshot.captureSnapshot` `isClickable` (Chrome'un kendi sezgisi), tek çağrı |
| yerel (native) | Öğe ya da herhangi bir üstü `a[href]`, button, input, `[role=button]` vb. Girdi zaten etkileşimli bir girdinin içinde. Gizlense de tıklanır. "net" sayım bunu eler |

(b) için DOMSnapshot yolu ile resolveNode yolu 6 sayfada 0 farkla aynı sonucu verdi.

## 3. Sayfa tablosu

Altıncı sayfa: **excalidraw.com**. Giriş istemez, herkese açık, React SPA. Araç çubuğu ve tuval `div`/`label` ile yapılmış: tam hedef türü.

| Sayfa | Toplam | Etkileşimli | Etkileşimsiz | (b) pointer | (c) etiket | (a) dinleyici | (d) isClickable | yerel içinde | net (b∪c∪a∪d) | net tok / etkileşimsiz tok |
|---|---|---|---|---|---|---|---|---|---|---|
| react.dev | 188 | 47 | 141 | 13 | 12 | 12 | 4 | 12 | 1 | 17 / 3.009 (%0,6) |
| vuejs.org | 78 | 54 | 24 | 2 | 2 | 0 | 1 | 2 | 0 | 0 / 449 |
| angular.dev | 101 | 53 | 48 | 27 | 24 | 0 | 0 | 27 | 1 | 14 / 979 (%1,4) |
| news.ycombinator.com | 349 | 230 | 119 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 2.728 |
| en.wikipedia (Web_browser) | 963 | 497 | 466 | 8 | 5 | 0 | 0 | 5 | 3 | 49 / 9.795 (%0,5) |
| excalidraw.com | 43 | 27 | 16 | 4 | 8 | 5 | 2 | 4 | 4 | 87 / 282 (%31) |
| **Toplam** | 1.722 | 908 | 814 | 54 | 51 | 29 | 7 | 50 | 9 | 167 / 17.242 (%1,0) |

Net sütunu (c) ile çok gürültü içerir (tabindex'li metin kapları). Gerçekten tıklanabilir olanlar §4'te.

### Net girdiler: hangi sinyal yakaladı

| Sayfa | net (b) | net (c) | net (a) | net (d) | Gerçek tıklanabilir |
|---|---|---|---|---|---|
| react.dev | 1 | 0 | 1 | 1 | 1 (`uwu?` div) |
| vuejs.org | 0 | 0 | 0 | 0 | 0 |
| angular.dev | 0 | 1 | 0 | 0 | 0 (`tabpanel` sekme gövdesi, tıklanmaz) |
| HN | 0 | 0 | 0 | 0 | 0 |
| Wikipedia | 3 | 0 | 0 | 0 | 3 (sıralanabilir `th`) |
| excalidraw | 0 | 4 | 1 | 1 | 1 (`Drawing canvas`); 3 metin kutusu (c) yanlış alarm |

### 3 örnek (etkileşimsiz, tıklanabilir, yerel dışı)

| Sayfa | Rol | Ad | Etiket | Sinyal |
|---|---|---|---|---|
| react.dev | StaticText | `uwu?` | div | b, a, d |
| Wikipedia | columnheader | `Market share` | th | b |
| excalidraw | StaticText | `Drawing canvas` | canvas | c, a, d |

## 4. Bulgular

1. **Sinyal (b) cursor:pointer en isabetli.** Gerçek tıklanabilirlerin hepsini yakaladı (react `uwu?`, 3 sıralanabilir `th`). Yakalayamadığı tek örnek: excalidraw tuvali (cursor `crosshair`). (d) onu yakaladı.
2. **Yerel süzgeç şart.** Süzgeçsiz (b) angular'da 27 girdi (576 token, sayfadaki etkileşimsiz tokenin %59'u) saydı. Bunlar bağlantı/düğme içindeki metin. İçeren etkileşimli girdi zaten listede. Net sayımda 0'a iner.
3. **(c) gürültülü.** `[tabindex]` metin kaplarında, `[role]` yapısal rollerde ateşler. angular `tabpanel` ve excalidraw 3 metin kutusu yanlış alarm.
4. **(a) olay dinleyicisi ata zincirinde işe yaramaz.** Kök kapta delegasyon var: react.dev ve excalidraw `#root` üzerinde click/mousedown/pointerdown/keydown, angular `body` üzerinde click/keydown, HN `document` üzerinde click. Ata zinciri (3 seviye) kök kaba ulaşmaz; yakaladığı girdiler (b)/(d) ile aynı. Ayrı bir sinyal olarak değer katmadı. 
5. **Vue / Angular:** ana sayfalar bağlantı ağırlıklı; gerçek net tıklanabilir yok (Vue 0, Angular 0 gerçek).
6. **Kör nokta (bu ölçüm dışı, kodda var):** `generic` rol `AGENT_SKIP_ROLES` içinde. Metni olmayan tıklanabilir `<div>` (yalnız ikon) bugün de görünmez. Metinli `<div onclick>` ise alt metin düğümü `StaticText` çapası olarak görünür (`uwu?`). Çapa yalnız ilk görülen aynı ad için girer (`seen_names`): aynı adlı ikinci tıklanabilir metin bugün de gizli. Diyet bu iki durumu değiştirmez; yalnız `uwu?` gibi çapaları kaldırırsa kaybolur.
7. **Yükleme notu:** Vue, Angular, Wikipedia'da `readyState` 60 sn içinde `complete` olmadı (makine yüklü); girdiler yine tam geldi (Wikipedia 963 = diyet belgesindeki sayı). İlk koşuda 3 sayfa boş gövdeyle ölçüldü; betik sonra içerik bekler ve o sayfalar yeniden ölçüldü. Vue ilk denemede `go` 60 sn aşımına düştü, ikinci denemede geçti. Başarısız sayfa yok.

## 5. Öneri

**Kural:** etkileşimsiz girdiyi şu iki koşuldan biri doğruysa tut, ve ata zincirinde yerel etkileşimli öğe (a[href], button, input, select, textarea, summary, `[role]` etkileşimli) yoksa:
1. etkin öğede `cursor:pointer` başlıyor (üstü pointer değil), ya da
2. DOMSnapshot `isClickable`.

| Ölçü | Değer |
|---|---|
| Ek CDP çağrısı | 1 (`DOMSnapshot.captureSnapshot`, `computedStyles:['cursor']`, `includeDOMRects:false`) |
| Süre (ölçüm) | 6–37 ms (react 18, vue 10, angular 6, hn 10, wikipedia 37, excalidraw 8); AX çağrısı 9–77 ms |
| Python tarafı | `backendNodeId` → düğüm indeksi sözlüğü, ata zinciri yürüyüşü (yerel süzgeç için etiket + role özniteliği) |
| Net tutulan | react 1, wikipedia 3, excalidraw 1 (canvas), diğer 0: 5 girdi, 82 token |
| Diyet kazancından geri verilen | 82 / 17.242 = %0,5 (sayfa başına %0–5,7; en yüksek excalidraw 16/282) |
| Süzgeçsiz (b) geri verirdi | 54 girdi, 1.047 token (etkileşimsiz tokenin %6; angular'da %59): yerel süzgeç şart |

Maliyet karşılaştırması (aynı bilgi için, dinleyici ve resolve yolu):

| Yol | Çağrı | Süre |
|---|---|---|
| DOMSnapshot (önerilen) | 1 | 6–37 ms |
| resolveNode + callFunctionOn (öğe başına) | 33–933 | 7–38 ms (pipeline) |
| getEventListeners (benzersiz öğe başına) | 36–420 | 6–52 ms |

Önerilmeyen: (c) tek başına (yanlış alarm), (a) (kök delegasyonu, ek değer yok), süzgeçsiz (b).

## 6. Sınırlar

- 6 sayfa, 1 SPA uygulaması. Çoğu sayfa bağlantı/düğme ağırlıklı; `<div onclick>` ağırlıklı uygulamada (ör. özel menü, kart ızgarası) net sayı büyür. Öneri kuralı o durumda da çalışır; ek maliyet yine 1 çağrı.
- Yerel süzgeç yaklaşımı ata zincirinde etiket arar; Python tarafında `role` özniteliği için DOMSnapshot `attributes` alanı gerekir (bu ölçümde sayfa içi `closest()` ile hesaplandı, Python eşdeğeri ölçülmedi).
- Aynı adlı ikinci tıklanabilir öğe (`seen_names`) bu ölçümde sayılmadı.
- `cursor:pointer`, kapsam dışı hover durumlarını görmez.
