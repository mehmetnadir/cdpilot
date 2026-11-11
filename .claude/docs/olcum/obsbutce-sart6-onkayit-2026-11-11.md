# Ön kayıt — D-0108 şart 6: kesik gözlemde model hedefi buluyor mu? (11.11.2026)

> Ölçüm koşmadan ÖNCE yazıldı. Kapı ve görev listesi sonradan değişmez; kalırsa yeni görev kümesi yazılır.

## Soru
`agent observe` 400 eylemden sonrasını keser ve `truncated` notu verir. Hedefi 400'ün ötesinde olan görevde model
`agent find` ya da `--all` ile hedefi bulup doğru öğeye mi tıklıyor, yoksa bulamadı / yanlış öğe mi diyor?

## Düzen
- Özne: agy-filo `kod` rolü (gemini-3.8-flash-high), her görev × kol için TAZE ajan. Özneye cdpilot kaynağı ve bu belge verilmez.
  Özne yalnız 3 komut kullanır (MCP açıklamaları aynen verilir: `browser_agent_observe`, `browser_agent_find`, `browser_agent_act`),
  bir kabuk sarmalayıcısı (`./cdp`) üzerinden; sarmalayıcı her çağrıyı, çıkış kodunu ve çıktının o200k token sayısını yazar.
- Kollar: K = varsayılan (sınır 400) · S = `CDPILOT_OBSERVE_MAX=0` (sınırsız).
- Tarayıcı: ortak 127.0.0.1:9333 (`connect`), her iş ayrı `CDPILOT_HOME`; eşzamanlı en çok 4 iş.
- Doğrulama: özne hedefe tıklar; ölçen, işin son URL'sini beklenen alt dizgeyle karşılaştırır (özne beyanı kanıt değil).

## Görevler (sıra sabit; hedef sırası koşudan hemen önce `--all` ile ölçülür, ≤ 400 ise görev düşer, yedek sıradan gelir)
| # | Sayfa | Görev (özneye verilen) | Beklenen URL alt dizgesi |
|---|---|---|---|
| 1 | docs.python.org/3/library/functions.html | len() fonksiyonunun açıklamasına git | `#len` |
| 2 | en.wikipedia.org/wiki/World_War_II | Stalingrad Muharebesi maddesini aç | `Battle_of_Stalingrad` |
| 3 | html.spec.whatwg.org/multipage/parsing.html | Topluluk davranış kuralları sayfasını aç | `code-of-conduct` |
| 4 | en.wikipedia.org/wiki/World_War_II | Midway Muharebesi maddesini aç | `Battle_of_Midway` |
| 5 | en.wikipedia.org/wiki/World_War_II | Manhattan Projesi maddesini aç | `Manhattan_Project` |
| 6 | en.wikipedia.org/wiki/List_of_countries_by_population_(United_Nations) | Tuvalu maddesini aç | `Tuvalu` |
| 7 | docs.python.org/3/library/functions.html | zip() fonksiyonunun açıklamasına git | `#zip` |
| 8 | html.spec.whatwg.org/multipage/parsing.html | HTML parçalarını serileştirme bölümüne git | `serializing-html-fragments` |
| Y1 | en.wikipedia.org/wiki/World_War_II | Barbarossa Harekâtı maddesini aç | `Operation_Barbarossa` |
| Y2 | docs.python.org/3/library/functions.html | vars() fonksiyonunun açıklamasına git | `#vars` |
| Y3 | en.wikipedia.org/wiki/List_of_countries_by_population_(United_Nations) | Vatikan maddesini aç | `Vatican_City` |

## Kapı (K kolu, 8 görev)
1. Başarı ≥ 7/8 (son URL beklenen alt dizgeyi içerir).
2. Yanlış öğeye tıklama 0 (son URL başka bir maddeye/bölüme gitti).
3. `find` ya da `--all` kullanımı, hedefi kesik olan görevlerde ≥ 7/8.
4. Sarmalayıcı token toplamı medyanı K ≤ S (sınırın amacı).
Kalırsa: `truncated.hint` metni ya da varsayılan sınır jüriye geri döner; aynı görevlerle ayar yapılmaz.
Bilgi (kapı değil): S kolu başarı, çağrı sayısı, agy girdi token'ı.
