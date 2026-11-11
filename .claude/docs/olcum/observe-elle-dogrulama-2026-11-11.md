# observe ince liste: elle doğrulama (D-0100 koşulu)

Tarih: 11.11.2026 · dal lane/obsdogrula (main 603c7f3) · paylaşılan tarayıcı 9333 (connect kipi) · yalnız okuma, tıklama yok.
Ham çıktılar ve betikler: `observe-elle-dogrulama/` (`<site>-ince.json`, `-ince2.json`, `-tam.json`, `-dom.json`, `-kayip-adaylari.json`).

## Sonuç

**D-0100 koşulu: GEÇTİ (0 eylem kaybı, 8 sayfa).**
İnce liste tam listeye göre 27%–85% daha az token kullanır. Etkileşimli hiçbir DOM öğesi yalnız ince listeden düşmedi.

## Yöntem

1. Her sayfa için `go`, sonra `agent observe` iki kez (aynı sayfa durumu) ve `agent observe --full`.
2. İki ince alım aynıdır: 7 sayfada evet. GitHub'da ilk alım sayfa yüklenirken farklıydı; 5 sn bekleyince 3 alım 451 = 451 = 451 oldu.
3. Fark: tam listede olup ince listede olmayan girdi, (rol, ad) çoklu kümesi ile çıkarıldı. Ref numarası kullanılmadı: her `observe` çağrısı ref'leri yeniden numaralar (GitHub'da doğrulandı).
4. Bağımsız eylem testi: sayfada `eval` ile görünür `a[href]`, `button`, `input`, `select`, `textarea`, `summary`, `[role]`, `[onclick]`, `[tabindex]` ve `cursor:pointer` öğeleri toplandı (`probe.js`). Her biri ince listede ada göre arandı. Tam listede de olmayanlar "taban boşluğu" sayıldı. Yalnız ince listeden düşenler "kayıp" sayıldı.
5. Token: o200k, dosya içeriği olduğu gibi (kompakt JSON).

## Site başına tablo

| Site | İnce / tam girdi | Token ince / tam | Tasarruf | Düşen | A | B | C | Kayıp (DOM testi) |
|---|---|---|---|---|---|---|---|---|
| HN ön sayfa | 230 / 348 | 4.270 / 6.855 | 38% | 118 | 0 | 118 | 0 | 0 / 230 |
| HN yorum (item 1) | 40 / 57 | 737 / 1.230 | 40% | 17 | 0 | 17 | 0 | 0 / 43 |
| HN yorum (item 8863) | 320 / 540 | 5.855 / 20.904 | 72% | 220 | 0 | 220 | 0 | 0 / 487 |
| excalidraw.com | 31 / 43 | 554 / 764 | 27% | 12 | 0 | 12 | 0 | 0 / 28 |
| Wikipedia Web_browser | 510 / 933 | 8.580 / 17.801 | 52% | 425 | 0 | 420 | 5 | 0 / 1033 |
| GitHub mehmetnadir/cdpilot | 451 / 2.730 | 9.046 / 61.977 | 85% | 2.279 | 0 | 2.250 | 29 | 0 / 370 |
| httpbin.org/forms/post | 16 / 23 | 313 / 435 | 28% | 7 | 0 | 7 | 0 | 0 / 13 |
| MDN arama (fetch) | 54 / 186 | 1.379 / 3.924 | 65% | 132 | 0 | 122 | 10 | 0 / 34 |

Sınıflar: A = tıklanır/yazılır/seçilir eylem. B = metin ya da yapı (StaticText, cell, LayoutTableCell, ListMarker, group, progressbar, görsel, Abbr, term, Video). C = belirsiz ya da yapısal (heading, navigation, sectionheader, columnheader).
"Kayıp" sütunu: DOM testinde ince listeden düşen eylemlenebilir öğe sayısı / testte bulunan eylemlenebilir öğe sayısı.

## A sınıfı: eylem kaybı listesi

Boş. Düşen hiçbir girdi eylem değil. İlk bakışta şüpheli görünen 6 durumun hepsi elendi:

| Şüpheli | Bulgu |
|---|---|
| excalidraw `Open`, `Help`, `Cmd+O` (StaticText) | Ebeveyn düğmeler `Open Cmd+O` ve `Help ?` ince listede var. Düşen yalnız düğme içi metin. |
| HN `login` / üst çubuk (LayoutTableCell) | `login`, `new`, `past`, `comments`, `hide`, `discuss`, oy okları (ad boş, 31 link) ince listede. Düşen yalnız kap. |
| HN `cell` (başlık, "N points by …") | İçindeki bağlantılar ayrı `link` girdisi olarak ince listede. |
| Wikipedia `[show]` columnheader (4) | `th` imleci pointer, ama toggle düğmesi `[show]` ×4 ince listede. |
| Wikipedia `v`/`t`/`e` Abbr (3) | Sarmalayan `link` ×6 ince listede. |
| GitHub rozetleri, avatarlar, ad boş bağlantılar | DOM testi "kayıp" dedi (13). Neden: DOM'da ad boş, observe ada `alt` verir (`npm version`, `MIT license`, `Node.js`, `@mehmetnadir` …). Ad eşleşmesi yapay uyarı. İnce listede var. |

Diğer yapay uyarılar: MDN altbilgisi 7 bağlantı (`Mozilla careers (external)` gibi, ad sonuna "(external)" eklenmiş), Wikipedia 2 atıf bağlantısı (ince listede ad 80 karakterde `…` ile kesilir), excalidraw ana kap `div` (tabindex 0, işleyici yok).

## C sınıfı: yapı kaybı (eylem değil)

| Site | Düşen | Not |
|---|---|---|
| MDN | 10 `heading` (arama sonucu başlıkları) | Aynı metinli `link` ince listede kalır. Başlık düzeyi bilgisi kaybolur. |
| Wikipedia | 4 `columnheader` + 1 `navigation` (`Appearance`) | Çocuk düğme/bağlantı kalır. |
| GitHub | 28 `columnheader`, 1 `sectionheader` (`Global navigation menu`) | Tablo başlıkları. Eylem yok. |
| GitHub | 3 `progressbar` (dil yüzdeleri) | Salt görsel. B sınıfında sayıldı. |

Kural gözlemi: tasarım belgesi "başlık/bölge/gezinme landmark'ları" kalır diyor. MDN'de `heading` düşüyor, çünkü içindeki link tıklanabilir ve ad aynı. Bu tekilleştirme kasıtlı olabilir. Karar jüriye ait; eylem kaybı değil.

## Taban boşlukları (ince listeyle ilgisiz, `--full` de eksik)

| Site | Bulgu | Kanıt |
|---|---|---|
| HN yorum sayfası (8863) | `parent`, `next`, `prev`, `root` bağlantıları (167 adet) ne ince ne tam listede | DOM'da görünür, `-tam.json`'da ad yok |
| GitHub | README bölümlerinin 4 açma/kapama düğmesi (`aria-expanded=false`, ad boş, `octicon-triangle-right`) ne ince ne tam listede | Düğme sayısı iki listede de 74 |

Bunlar bu koşulu kırmaz. Ayrı iş olarak kaydedilmeli: "ad boş düğme" ve "HN gezinme bağlantıları" `--full`'da da görünmüyor.

## Ek gözlemler

- Bu derlemede `observe` çıktısında `hidden_refs` alanı yok (anahtarlar: `url, title, actions, text, token_estimate`). Görev metni gizli ref'lerin orada olduğunu söylüyordu. `act --ref` ile gizli ref denenmedi (yalnız okuma kuralı).
- `cdpilot --version` bu derlemede `0.9.7` yazıyor.
- Ref'ler her `observe` çağrısında yeniden numaralanır. İnce ve tam alım arasında ref ile eşleştirme yapılamaz. (rol, ad) ile eşleştirildi.
- Sayfa yüklenirken alınan ilk GitHub alımı kararsızdı. Ölçümlerde 5 sn bekleme gerekli.

## Süzgeç kuralı önerisi

Değişiklik gerekmiyor. İsteğe bağlı: MDN'deki gibi "aynı metinli link içeren heading" düşürülürken başlık düzeyi (h2) link girdisine bilgi olarak eklenebilir. Kod yazılmadı.

## Sekme durumu (dürüst kayıt)

Önce 5 sekme, sonra 5 sekme. `new-tab` ile kendi sekmemi açtım (`612683F8…`, kapattım). Ancak `cdpilot go` yeni sekmeye değil, bağlı kipte varsayılan (ilk) sekmeye gitti. İlk sekme, başlangıçta `cdpilot-canvas.invalid/demo/` idi. İş sonunda o sekme yok, yerinde GitHub sayfası var (id `562D8650…`). Yani başka bir şeridin canvas demo sekmesini farkında olmadan yönlendirmiş olabilirim. Soak (`cdpilot-soak-*`) sekmelerine dokunmadım. `connect` kipinde `go`'nun hedef sekmesi `new-tab` ile seçilmiyor. Sonraki koşular için: `go` öncesi hedef sekmeyi `tabs` ile doğrula.
