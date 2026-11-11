> Şef notu 11.11: ölçüm agy-filo (gemini-3.8-flash) şeridinde koştu; ham veri depo dışında `~/01dev/cdpilot-olcum-ham/observe-hedef-2026-11-11/` (sonuc.jsonl). Şef sayıları ham veriden yeniden saydı.

# Büyük Sayfada Hedef Eylem `agent observe` Sıra ve Görünürlük Ölçüm Raporu

Tarih: 11.11.2026. Makine: arm64. Port: 9333. Pencere boyutu: [800,600].

Toplam hedef: 52 (13 sayfa × 4 hedef).

## 1. Hedef Ölçüm Tablosu

| Sayfa | Hedef No | Kategori | Görev | Beklenen Rol/Ad | Eşleşen Ref | Sıra | Toplam Eylem | İlk Ekranda mı | İlk Ekrandaki Eylem |
|---|---|---|---|---|---|---|---|---|---|
| wikipedia-countries | 1 | arama_giris | Wikipedia arama kutusuna odaklan | `searchbox`: Search Wikipedia | - | ölçülmedi | 1108 | Evet | 70 |
| wikipedia-countries | 2 | ana_eylem | Maddenin düzenleme geçmişini görüntüle | `link`: View history | @30123 | 62 | 1108 | ölçülmedi | 70 |
| wikipedia-countries | 3 | sayfa_ortasi_baglanti | Nüfus tablosundaki United States maddesine git | `link`: United States | @31265 | 379 | 1108 | Hayır | 70 |
| wikipedia-countries | 4 | sayfa_sonu_baglanti | Altbilgideki Gizlilik Politikası sayfasına git | `link`: Privacy policy | @30076 | 22 | 1108 | Hayır | 70 |
| wikipedia-ww2 | 1 | arama_giris | Wikipedia arama kutusuna odaklan | `searchbox`: Search Wikipedia | - | ölçülmedi | 4043 | Evet | 90 |
| wikipedia-ww2 | 2 | ana_eylem | Madde geçmişini görüntüle | `link`: View history | @32449 | 277 | 4043 | ölçülmedi | 90 |
| wikipedia-ww2 | 3 | sayfa_ortasi_baglanti | Stalingrad Muharebesi maddesine git | `link`: Battle of Stalingrad | @34708 | 1548 | 4043 | Hayır | 90 |
| wikipedia-ww2 | 4 | sayfa_sonu_baglanti | Altbilgideki Gizlilik Politikası sayfasına git | `link`: Privacy policy | @32019 | 28 | 4043 | Hayır | 90 |
| mdn-element | 1 | arama_giris | MDN arama kutusuna odaklan | `searchbox`: Search MDN | - | ölçülmedi | 354 | ölçülmedi | 23 |
| mdn-element | 2 | ana_eylem | MDN dokümantasyon hatası bildir (Report an issue) | `link`: Report an issue | - | ölçülmedi | 354 | ölçülmedi | 23 |
| mdn-element | 3 | sayfa_ortasi_baglanti | HTML <table> elemanı detay sayfasına git | `link`: <table> | @40128 | 268 | 354 | Hayır | 23 |
| mdn-element | 4 | sayfa_sonu_baglanti | Altbilgideki Gizlilik Politikası sayfasına git | `link`: Privacy Policy | - | ölçülmedi | 354 | Evet | 23 |
| python-functions | 1 | arama_giris | Python dokümantasyonu hızlı arama kutusuna odaklan | `textbox`: Quick search | @40317 | 10 | 589 | Evet | 72 |
| python-functions | 2 | ana_eylem | Genel Dizin bağlantısına git | `link`: General Index | - | ölçülmedi | 589 | Evet | 72 |
| python-functions | 3 | sayfa_ortasi_baglanti | len() fonksiyonu dokümantasyonuna git | `link`: len() | @41987 | 533 | 589 | ölçülmedi | 72 |
| python-functions | 4 | sayfa_sonu_baglanti | Altbilgideki Telif Hakkı (Copyright) sayfasına git | `link`: Copyright | @40300 | 2 | 589 | Hayır | 72 |
| github-vscode | 1 | arama_giris | GitHub arama alanını aç | `button`: Search or jump to... | - | ölçülmedi | 316 | ölçülmedi | 97 |
| github-vscode | 2 | ana_eylem | Kod klonlama/indirme açılır menüsünü aç (Code butonu) | `button`: Code | @42474 | 23 | 316 | Evet | 97 |
| github-vscode | 3 | sayfa_ortasi_baglanti | Dosya listesindeki package.json dosyasına git | `link`: package.json | @40852 | 210 | 316 | Evet | 97 |
| github-vscode | 4 | sayfa_sonu_baglanti | Altbilgideki Terms bağlantısına git | `link`: Terms | @42463 | 13 | 316 | Hayır | 97 |
| github-node-issues | 1 | arama_giris | Issue arama ve filtreleme kutusuna odaklan | `textbox`: Filters | - | ölçülmedi | 146 | ölçülmedi | 73 |
| github-node-issues | 2 | ana_eylem | Yeni sorun kaydı oluşturma sayfasına git (New issue) | `link`: New issue | @43036 | 32 | 146 | Evet | 73 |
| github-node-issues | 3 | sayfa_ortasi_baglanti | Etiketler (Labels) sayfasına git | `link`: Labels | @43237 | 111 | 146 | Evet | 73 |
| github-node-issues | 4 | sayfa_sonu_baglanti | Sonraki sayfa bağlantısına git (Next) | `link`: Next | @43080 | 46 | 146 | Hayır | 73 |
| news-ycombinator | 1 | arama_giris | Sayfa altındaki HN arama kutusuna odaklan | `textbox`: Search | @43313 | 9 | 230 | Hayır | 122 |
| news-ycombinator | 2 | ana_eylem | Hacker News kullanıcı oturumu aç | `link`: login | @43407 | 19 | 230 | Evet | 122 |
| news-ycombinator | 3 | sayfa_ortasi_baglanti | Geçmiş günlerin haber arşivine git (past) | `link`: past | @43401 | 13 | 230 | Evet | 122 |
| news-ycombinator | 4 | sayfa_sonu_baglanti | Sonraki haber sayfasına git (More) | `link`: More | @43559 | 170 | 230 | Hayır | 122 |
| news-ycombinator-item | 1 | arama_giris | Yorum yazma alanına odaklan | `textbox`: text | @43663 | 9 | 1333 | Evet | 34 |
| news-ycombinator-item | 2 | ana_eylem | Yorum gönderme butonuna tıkla (add comment) | `button`: add comment | @43946 | 31 | 1333 | Evet | 34 |
| news-ycombinator-item | 3 | sayfa_ortasi_baglanti | Yoruma yanıt ver (reply bağlantısı) | `link`: reply | @44067 | 38 | 1333 | Evet | 34 |
| news-ycombinator-item | 4 | sayfa_sonu_baglanti | Altbilgideki YC başvuru bağlantısına git | `link`: Apply to YC | @43660 | 7 | 1333 | Hayır | 34 |
| bbc-news | 1 | arama_giris | BBC arama çubuğunu aç | `button`: Search BBC | - | ölçülmedi | 137 | Evet | 24 |
| bbc-news | 2 | ana_eylem | BBC hesabına giriş yap (Sign in) | `link`: Sign In | @45727 | 13 | 137 | Evet | 24 |
| bbc-news | 3 | sayfa_ortasi_baglanti | Business haberleri kategorisine git | `link`: Business | @45774 | 60 | 137 | Evet | 24 |
| bbc-news | 4 | sayfa_sonu_baglanti | Altbilgideki Gizlilik Politikası sayfasına git | `link`: Privacy Policy | @43938 | 75 | 137 | Hayır | 24 |
| stackoverflow-11227809 | 1 | arama_giris | Stack Overflow arama kutusuna odaklan | `textbox`: Search | @45928 | 8 | 1131 | Evet | 84 |
| stackoverflow-11227809 | 2 | ana_eylem | Yeni soru sorma sayfasına git (Ask Question) | `link`: Ask Question | @45955 | 28 | 1131 | Evet | 84 |
| stackoverflow-11227809 | 3 | sayfa_ortasi_baglanti | Soruyu paylaş butonuna tıkla (Share) | `button`: Share | @46043 | 105 | 1131 | Hayır | 84 |
| stackoverflow-11227809 | 4 | sayfa_sonu_baglanti | Altbilgideki Gizlilik Politikası sayfasına git | `link`: Privacy Policy | @46021 | 90 | 1131 | Evet | 84 |
| books-toscrape | 1 | arama_giris | Kategori menüsündeki Travel kategorisine git | `link`: Travel | @48588 | 6 | 115 | Evet | 23 |
| books-toscrape | 2 | ana_eylem | Kitabı sepete ekle (Add to basket) | `button`: Add to basket | @48700 | 96 | 115 | Hayır | 23 |
| books-toscrape | 3 | sayfa_ortasi_baglanti | Soumission kitabının ürün sayfasına git | `link`: Soumission | @48662 | 60 | 115 | Evet | 23 |
| books-toscrape | 4 | sayfa_sonu_baglanti | Sonraki ürün sayfasına git (next) | `link`: next | @48587 | 5 | 115 | Hayır | 23 |
| whatwg-html-parsing | 1 | arama_giris | Standart içi arama kutusuna odaklan | `searchbox`: Search | - | ölçülmedi | 5111 | ölçülmedi | 18 |
| whatwg-html-parsing | 2 | ana_eylem | İçindekiler tablosuna git (Table of Contents) | `link`: Table of Contents | @48880 | 142 | 5111 | Evet | 18 |
| whatwg-html-parsing | 3 | sayfa_ortasi_baglanti | Ayrıştırma (token) kavramı bağlantısına git | `link`: token | @48911 | 154 | 5111 | Hayır | 18 |
| whatwg-html-parsing | 4 | sayfa_sonu_baglanti | Altbilgideki Topluluk ve Davranış Kuralları sayfasına git | `link`: Community and code of conduct | @54874 | 3540 | 5111 | Hayır | 18 |
| theguardian-international | 1 | arama_giris | Guardian iş arama sayfasına git | `link`: Search jobs | - | ölçülmedi | 445 | ölçülmedi | 30 |
| theguardian-international | 2 | ana_eylem | Guardian'a destek ol (Support the Guardian) | `link`: Support the Guardian | - | ölçülmedi | 445 | ölçülmedi | 30 |
| theguardian-international | 3 | sayfa_ortasi_baglanti | Opinion köşesi sayfasına git | `link`: Opinion | @57460 | 66 | 445 | Hayır | 30 |
| theguardian-international | 4 | sayfa_sonu_baglanti | Altbilgideki Gizlilik Politikası sayfasına git | `link`: Privacy Policy | @57463 | 76 | 445 | Hayır | 30 |

## 2. Eylem Sınırı Analizi (N Sınırları)

| Eylem Sınırı (N) | Sınır İçinde Kalan Hedef | Ölçülen Hedefe Oran | Tüm Hedeflere Oran |
|---|---|---|---|
| N = 50 | 20 / 40 | %50.0 | %38.5 |
| N = 100 | 28 / 40 | %70.0 | %53.8 |
| N = 200 | 33 / 40 | %82.5 | %63.5 |
| N = 400 | 37 / 40 | %92.5 | %71.2 |

## 3. Görünür Alan (İlk Ekran) Analizi

- İlk ekranda olan hedef sayısı: 23
- Ölçülen hedefler içindeki oran: %54.8 (23 / 42)
- Tüm hedefler içindeki oran: %44.2 (23 / 52)

## 4. Sistem Yükü

`sysctl -n vm.loadavg` çıktısı:

```text
{ 36.26 39.09 36.30 }
```

> Şef notu: 52 hedefin 12'si ölçülemedi (8'i arama kutusu: rol/ad eşleşmedi — Wikipedia 'Search Wikipedia' searchbox observe listesinde bulunamadı; ayrı inceleme). Sınır oranları yalnız ölçülen 40 hedef üzerindendir.
