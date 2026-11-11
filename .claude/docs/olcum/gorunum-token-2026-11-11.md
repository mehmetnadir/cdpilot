# Sayfa görünümü token ölçümü (2026-11-11)

Commit: `1a6ddbc` (dal `lane/gorunum`, kod değişmedi). Tarih: 11.11.2026.
Tarayıcı: ortak başsız Chrome 152 (127.0.0.1:9333), `CDPILOT_LOG=0`, `CDPILOT_NO_AUTOLAUNCH=1`.
Makine yükü (`vm.loadavg`): 81–120 (ölçüm boyunca). Sayaç: o200k_base, `stdout` metni. Her hücre 3 koşu, medyan.

## Medyan token (stdout)

| Görünüm | HN | Wikipedia | react.dev | MDN | Ref ile eyleme geçilir mi |
|---|---|---|---|---|---|
| `content` | 1.194 | 4.743 | 1.455 | 401 | hayır |
| `a11y-snapshot` | 8.088 | 13.112 | 1.219 | 4.985 | evet (`click-ref @N`) |
| `a11y` | 9.770 | 31.438 | 7.026 | 10.786 | hayır (ref yok, adlar var) |
| `describe` | 8.753 | 13.612 | 1.724 | 5.452 | evet (`click-ref @N`); PNG yazar |
| `agent observe` | 4.284 | 8.305 | 1.531 | 3.324 | evet (`agent act --ref`) |
| `agent observe --rows` | 2.870 | 5.235 | 1.134 | 2.387 | evet |
| `agent observe --full` | 6.895 | 17.342 | 4.182 | 6.590 | evet |

3 koşu her hücrede aynı sayıyı verdi (sayfa koşular arasında değişmedi). Sayfa kayması: Wikipedia `observe --rows`
5.235 (ilk tur) ile 5.630 (1 sa sonraki tur) arasında; yani saatler arası ~%7. HN `observe` 10.11'de 5.836 idi
(filtre öncesi), bugün 4.284.

`describe`: metin kısmı `a11y-snapshot` + "Page Content (first 2000 chars)"; ekran görüntüsünü
`/tmp/cdpilot-describe-<ts>.png` dosyasına yazar (token sayımına girmez, görsel maliyeti ayrı).

## Eylemden sonra fark (3 koşu, medyan)

| Sayfa | Tıklanan | `observe --rows` (taban) | `agent act` çıktısı | `observe --diff` (act'ten sonra) |
|---|---|---|---|---|
| Wikipedia | "Toggle the table of contents" | 5.630 | 242 | 51 |
| react.dev | "Search ⌘ K" (her koşuda yeniden `go`) | 1.147 | 496 | 45 |
| MDN | "Toggle sidebar" | 2.392 | 142 | 60 |
| HN | atlandı: aynı sayfada düğme yok (oklar bağlantı, tıklama oy/gezinme) | — | — | — |

`act` değişikliği kendisi basar; ondan sonraki `observe --diff` "act'ten beri değişmedi" der (45–60 token). Wikipedia
2. koşuda 539/511 verdi (düğme durumu ters döndü: aç/kapa); medyan 242/51.

## Bulgular

- `content` MDN'de yalnız 2.025 karakter (401 token): makale özetini ve içindekileri verir, kod örneği ve
  uyumluluk tablosu yok (`document.body.innerText` böyle). "Okuma" görünümü olarak tam sayfa sanılmamalı.
- react.dev'de `a11y-snapshot` (1.219) `content`'ten (1.455) küçük: sıralama sayfaya bağlı.
- `a11y` Wikipedia'da en pahalı görünüm (31.438) ve ref içermez.
- Yan etki: `describe` her koşuda `/tmp`'ye PNG yazdı (12+ dosya). Başsız `context create` ile açılan sekme süreç
  bitince yok oluyor (`CDPILOT_TARGET` sonraki komutta "no such tab"); ölçüm CWD oturum sekmesiyle yapıldı.
