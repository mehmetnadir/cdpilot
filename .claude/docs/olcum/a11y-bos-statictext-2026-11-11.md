# a11y: boş StaticText ölçümü (11.11)

Sonuç: "482 boş StaticText" iddiası ölçümle çürüdü. `a11y` çıktısındaki 482 `[StaticText]` satırı boş değil. Düğümlerin adı var. `a11y full` adı yanlış yerden okuduğu için hiçbir satırda ad yazmıyor.

## Neden

- `a11y` komutu `cmd_a11y` çalıştırır (`a11y-snapshot` değil). `full` kipinde süzgeç yoktu.
- Ad, değer ve açıklama AX düğümünün üst alanlarıdır. `get_prop` yalnız `properties` listesine bakar. Bu yüzden her satır çıplaktır.
- `a11y-snapshot` ve `describe` StaticText satırı hiç yazmaz: rol INTERACTIVE ya da STRUCTURAL kümesinde değil. Büyük harf düzeltmesi bu iki yerde çıktıyı değiştirmez.
- Küçük harfli `staticText` yalnız test sahte ağacında (`ax_tree_for`) var. Chrome üretmez. Küme iki değeri de tutar.

## Ölçüm (aee8d38 öncesi, düzeltme sonrası; o200k_base)

| Sayfa | Komut | Önce satır / token | Sonra satır / token | Fark |
|---|---|---|---|---|
| news.ycombinator.com | a11y | 1617 / 7958 | 1586 / 7838 | −1,5 % |
| en.wikipedia.org/wiki/Web_browser | a11y | 4457 / 22814 | 4443 / 22762 | −0,2 % |
| react.dev | a11y | 1645 / 8671 | 1639 / 8651 | −0,2 % |
| 3 sayfa | a11y-snapshot, describe | aynı | aynı | 0 (sayfa oynaması ±30 token) |

Atlanan satırlar yalnız `generic` yaprağı: HN 31, Wikipedia 14, react 6. Boş StaticText, InlineTextBox ve LineBreak sayısı üç sayfada 0 (hepsinin adı var).

## Boş satır kaynakları (HN / Wikipedia / react; `a11y` önceki çıktı)

| Rol | HN | Wiki | react | Karar |
|---|---|---|---|---|
| InlineTextBox | 485 | 1671 | 708 | adlı; adı üst StaticText ile aynı. Ad yazılırsa metin iki kez çıkar |
| StaticText | 482 | 1358 | 609 | adlı |
| generic | 151 | 582 | 131 | yaprak ve adsız olanlar atlandı (31 / 14 / 6); çocuklu olanlar kaldı |
| LineBreak | 3 | 0 | 59 | adlı (satır sonu) |

## Ref (@N) bağımlılığı

- `a11y` ref yazmaz (`_A11Y_REF_MAP` ve `_save_a11y_refs` yok): ref kayması olamaz.
- `a11y-snapshot` ve `describe` ref'i yalnız yazdıkları satırlara verir. StaticText yazılmadığı için numaralar aynı. Test, gürültülü sahte ağaçta satır listesinin, ref'in ve `click-ref` hedefinin (backend 103) değişmediğini doğrular.

## Adım 2: adlar yazıldı, InlineTextBox ve LineBreak atlandı (11.11)

Geçmiş: hata ilk sürümden beri var. `cmd_a11y` tek commit'te (926b88f, v0.1.1) eklendi ve `get_prop` hep yalnız `properties` listesine baktı. `git log -S` başka commit göstermez: bir değişiklik bozmadı, `a11y` hiç ad yazmadı.

Düzeltme: `get_prop` önce üst alan `name` / `value` / `description` okur, sonra `properties`. `a11y find` gerçek adı yazar. InlineTextBox ve LineBreak her zaman atlanır. Dallanma girintisi yok: `a11y full` düz liste, girinti zaten iki boşluk sabit.

| Sayfa | Önce (aee8d38, adsız) | Adım 1 (adlar + boş yaprak atlama) | Adım 1+2 | agent observe | a11y-snapshot | describe |
|---|---|---|---|---|---|---|
| HN | 1617 sat / 7958 | 1592 / 14612 | 1098 / 9775 | 1 / 6514 | 323 / 8084 | 399 / 8752 |
| Wikipedia | 4457 / 22814 | 4443 / 49243 | 2772 / 31438 | 1 / 17578 | 527 / 13112 | 567 / 13612 |
| react.dev | 1645 / 8671 | 1757 / 14329 | 872 / 7026 | 1 / 3931 | 68 / 1219 | 169 / 1724 |

Not: adım 1 sütunu önceki turdaki boş yaprak atlamayı da içerir (ayrı ölçüm: 7838 / 22762 / 8651, adsız).
Kullanım: `a11y` tam düğüm dökümü (ad, değer, açıklama; kontrol dışı roller dahil). Eylem için `a11y-snapshot` (@ref'li, en az token) ya da `agent observe`. `describe` snapshot + ekran görüntüsü + metin.
