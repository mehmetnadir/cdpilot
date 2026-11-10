# SPA Settle Ölçümü (10.11.2026)

Sistem yükü (uptime): `33.70, 32.63, 31.06`.
Ölçüm aracı: `.claude/docs/olcum/olc-spa.sh` (`zsh olc-spa.sh <url>…`; ham çıktılar scratchpad'teydi, kalıcı değil — rapordaki sayılar ham dosyalarla birebir denetlendi, 10.11 şef).
Ortam: Apple M1 Max, ortak başsız Chrome (127.0.0.1:9333), cdpilot v0.9.5.

## Ölçüm Sonuçları

Komut şablonu: `zsh olc-spa.sh <url>` (Zaman aralığı: 11:59:13 – 12:00:59).

| Site | Koşu | Zaman | Yük | go ms | innerText ilk → 2 sn | Kaynak ilk → 2 sn | Son Değişim (+ms) |
|---|---|---|---|---|---|---|---|
| https://react.dev/ | 1 (ısınma) | 11:59:13 | 35.64 32.99 30.97 | 1340 | 6547 → 6547 | 59 → 59 | +0 |
| https://react.dev/ | 2 (ölçüm 1) | 11:59:22 | 35.32 33.01 31.00 | 812 | 6547 → 6547 | 57 → 57 | +0 |
| https://react.dev/ | 3 (ölçüm 2) | 11:59:31 | 33.96 32.79 30.95 | 841 | 6547 → 6547 | 57 → 57 | +0 |
| https://angular.dev/ | 1 (ısınma) | 11:59:39 | 33.57 32.73 30.93 | 1472 | 3080 → 3080 | 42 → 44 | +402 |
| https://angular.dev/ | 2 (ölçüm 1) | 11:59:51 | 32.53 32.55 30.90 | 1087 | 3080 → 3080 | 42 → 44 | +403 |
| https://angular.dev/ | 3 (ölçüm 2) | 12:00:02 | 32.51 32.54 30.92 | 1069 | 3080 → 3080 | 42 → 44 | +402 |
| https://vuejs.org/ | 1 (ısınma) | 12:00:11 | 31.39 32.30 30.85 | 1443 | 1313 → 1313 | 37 → 38 | +204 |
| https://vuejs.org/ | 2 (ölçüm 1) | 12:00:20 | 30.72 32.14 30.80 | 850 | 1313 → 1313 | 38 → 38 | +0 |
| https://vuejs.org/ | 3 (ölçüm 2) | 12:00:28 | 30.31 32.01 30.77 | 803 | 1313 → 1313 | 38 → 38 | +0 |
| https://example.com/ | 1 (ısınma) | 12:00:37 | 31.51 32.20 30.85 | 604 | 917 → 917 | 1 → 1 | +0 |
| https://example.com/ | 2 (ölçüm 1) | 12:00:46 | 31.57 32.20 30.86 | 618 | 917 → 917 | 1 → 1 | +0 |
| https://example.com/ | 3 (ölçüm 2) | 12:00:54 | 31.68 32.21 30.88 | 615 | 917 → 917 | 1 → 1 | +0 |

## Sonuç

`go` döndüğünde DOM yerleşmiş miydi: DOM metni (`document.body.innerText`) açısından 4 sitenin 4'ünde (12 koşunun 12'sinde) yerleşmişti; 2,2 saniyelik gözlem süresinde metin uzunluğu değişmedi (0 karakter değişim).

30 ms kısayolunun durumu:
- DOM `innerText` değişimine göre: 0 sitede değişim kaçırırdı (tüm sitelerde son değişim 0 ms).
- Betik `son değişim` metriğine (DOM metni veya kaynak sayısı değişimi) göre: 4 siteden 2'sinde (angular.dev 3 koşuda [+402 ms, +403 ms, +402 ms]; vuejs.org 1 koşuda [+204 ms]) son değişim 30 ms üzerindedir. react.dev ve example.com sitelerinde 3 koşunun tamamında son değişim 0 ms'dir.

## Şef notu (10.11, ölçümün sınırı ve okuması)

- Örnekleme `go` döndükten sonra ayrı bir `eval` komutuyla başlar; sıcak süreçte bu ~150 ms sonradır. Yani "0 ms değişim"
  = `go` dönüşünden ~150 ms sonrasından 2,2 sn'ye kadar metin değişmedi. İlk ~150 ms içindeki bir değişim görünmez.
- Kaynak sayısı artışları (angular +402 ms, vue ısınmada +204 ms) geç yüklenen kaynaklardır (yazı tipi, ölçüm betiği);
  metin (`innerText`) değişmedi. Karar girdisi: 100 ms sessizlik penceresi bu 4 sitede metni kaçırmadı; "bekleyen istek yok →
  30 ms" kısayolu metin açısından da kaçırmazdı, ama angular'da kaynaklar `go` sonrası 400 ms daha akıyor. Karar Nadir'de
  (plan-daemon-insan-hizi.md §6 sonu); 4 site 3 koşu küçük örneklemdir.
