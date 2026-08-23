# X (Twitter) Algorithm — Pratik Kurallar

> Kaynak: `twitter/the-algorithm` repo, HeavyRanker model ağırlıkları (2023 açık kaynak release + topluluk gözlemleri).
> Bu dosya her draft için **self-check** olarak uygulanır.

---

## 1. Ağırlık tablosu (HeavyRanker)

> ⚠️ **SUPERSEDED (2026-08):** Bu tablo 2023 legacy release'den. Gerçek 2026 ağırlıkları
> için §5'e bak (xai-org/x-algorithm repo'sundan doğrulanmış). Özellikle: reply +27 ve
> profile click +12 artık GEÇERSİZ.

| Sinyal | Ağırlık | Yorum |
|---|---|---|
| **Reply gönderildi** | **+27** | EN GÜÇLÜ sinyal. Reply çekecek format = boost |
| **Profile click** | **+12** | Tweet'i okuyan profil sayfana tıklıyorsa: ağır pozitif |
| **Detail expand** ("Show more") | **+11** | Long-form / thread'de "Devamını oku" tıklaması |
| Video playback >50% | +0.005 | Çok küçük; video varsa bonus, yoksa kaybetmiyorsun |
| Retweet | +1 | Quote-tweet daha güçlü (reply + RT etkisi) |
| Like | +0.5 | Sıradan |
| Bookmark | +1 (gözlemsel) | "Reference" sinyali |
| **URL in tweet body** | **−1** | Linkleri **reply'a** koy, tweet gövdesine değil |
| Image without alt-text | küçük neg | A11y bonus var; alt-text ekle |
| **Reported as bad** | **−74** | Kaba/clickbait → çok ağır ceza |
| Block / mute author | heavy neg | Polemik dozu = kantitatif risk |
| Negative feedback (post-engagement) | neg | "Show less often" tıklanırsa zarar |

---

## 2. Pratik kurallar (her draft için)

### A. Format kuralları
- ✅ Soru + iddia kombinasyonu — reply baitling DEĞİL, dürüst soru
- ✅ İlk satırda **hook** olmalı (ilk 100 karakter feed'de görünür)
- ✅ Thread yazıyorsan: ilk tweet stand-alone bile değerli, "Read more" tetikler
- ❌ URL gövdede — eğer link şartsa, post'u yaz + ilk reply'a "→ link burada" koy
- ❌ Sadece linkten oluşan tweet — full punishment
- ❌ "Like + RT if you agree" — engagement bait, X dehumanizer cezalıyor

### B. İçerik tarzı
- ✅ **Spesifiklik** — "We saw 36.25% on Stealth Bench" > "Performance is decent"
- ✅ **Sayı + kanıt** — claim varsa data
- ✅ **Distinct voice** — sıradan kelimeler yerine kendi terminoloji
- ✅ Hot-take ile **dayanak** — kanıtsız hot-take = sallantılı; kanıtla = paylaşılabilir
- ❌ Bland mütevazılık ("Just wanted to share...") — algoritma "weak signal" olarak ölçüyor
- ❌ Engagement farming ("Drop your opinion 👇") — yakalanır, ceza

### C. Mention/reply kuralları
- Büyük hesaba reply: **değer kat**, "great post!" deme. Spesifik bir nokta üzerine düşünce.
- Yorum gelirse: 30 dk – 3 saat içinde cevapla (`reply-timing.md`)
- Quote tweet: yorum ekle. Pure quote (yorumsuz) = ceza
- @grok mention: Premium avantajı; ayda 3-5 kullan, daha fazlası spam

### D. Zamanlama (PT/ET dev kitlesi için TR saatleri)
- **Peak 1:** 16:00-19:00 TR (= 06:00-09:00 PT, ABD batı sabah)
- **Peak 2:** 22:00-01:00 TR (= 12:00-15:00 PT, ABD batı öğle)
- **Yan peak:** 11:00-13:00 TR (Avrupa öğle)
- Aynı saatte birden fazla tweet → algoritma "spam burst" görür. Min 30 dk aralık.

### E. Hesabın "fingerprint"i
- Cadence tutarlılığı: günde 1-2 sabit ritim > pazartesi 8 / salı 0
- Aynı hashtag tekrarı: 2-3 hashtag rotasyonu OK, 5+ aynı = spam fingerprint
- Reply / tweet oranı: 10:1 minimum (özellikle yeni hesaplarda)

---

## 3. Crisis trigger keyword'leri

Bu kelimeler herhangi bir gelen reply/mention'da varsa **otomatik olarak human onay zorunlu**:
- politika, ülke, parti, lider isimleri (TR + global)
- "scam", "fraud", "fake", "rug"
- "ban", "suspended", "terminate"
- "wrong", "lie", "lying", "misleading" (defansif tepki gerekebilir)
- legal/IP iddiaları ("you stole", "copyright", "infringement")
- "child", "minor", "underage" (zero-tolerance konu)
- ırk/cinsiyet/din terimleri (kaçınılması gereken context'ler)

→ Bu keyword'lerden herhangi biri eşleşirse: draft hazırla **ama gönderme**, Telegram'a "🚨 URGENT" prefix'iyle ilet.

---

## 4. Tweet self-check checklist

Her draft için (kendin kontrol et):
- [ ] URL tweet gövdesinde DEĞİL mi?
- [ ] İlk 100 karakter feed'de stand-alone değer veriyor mu?
- [ ] Engagement bait yok mu? ("Like if...", "Drop a 👇")
- [ ] Spesifik bir iddia + dayanak var mı?
- [ ] Crisis keyword içeriyor mu? (varsa human-must-approve)
- [ ] Görsel varsa alt-text yazıldı mı?
- [ ] Hashtag 0-2 arası mı?
- [ ] Saat peak'te mi? (değilse jitter ile peak'e kaydır)

---

## 5. 2026-08 güncelleme — Açık kaynak algoritma (xai-org/x-algorithm)

> Kaynak: https://github.com/xai-org/x-algorithm (2026-08-13 açık kaynak, Apache-2.0).
> Ağırlıklar `home-mixer/params/param.rs`'den doğrudan okundu (2026-08-23 doğrulandı).
> [TAHMİN] etiketli sayılar üçüncü taraf — repo'da yok, kesin gerçek olarak sunma.
> Detaylı skill: `~/.claude/skills/x-algorithm-truth/SKILL.md`

### 5.1 Grok/Phoenix ranking — içerik tavanı belirler

- Yeni pipeline: Home Mixer → Thunder (in-network cache) + Phoenix retrieval (two-tower
  embedding) + SimClusters → Phoenix scorer (her aksiyon için olasılık tahmini) → Grox
  (yayın anında spam/kalite classifier + text/görsel embedding).
- **Post metni engagement OLMADAN önce embed edilip kullanıcı ilgi vektörleriyle
  eşleştiriliyor.** Belirsiz/jenerik metin ("exciting news!") hiçbir cluster'a oturmaz →
  retrieval'a girmez. Draft'ta TEK net, spesifik iddia + somut terim/sayı zorunlu.
- İçerik skorun tavanı; erken engagement sadece onaylar [TAHMİN — forkoff.xyz yorumu].
  Zayıf post'u hızlı beğeni kurtarmaz.
- Konu tutarlılığı hesap embedding'ini netleştirir; konu dağınıklığı her post'a vergi
  [TAHMİN]. cdpilot niş'inde kal: browser automation / CDP / AI tooling.

### 5.2 Yeni ağırlıklar — reply > like (repo, kesin)

| Sinyal | 2026 ağırlık | Like'a oran |
|---|---|---|
| **Copy-link ile paylaşım** | **+20.0** | **40x** — EN GÜÇLÜ sinyal |
| **Reply** | **+5.0** | **10x** (eski "27x" GEÇERSİZ) |
| Quote | +5.0 | 10x |
| DM ile paylaşım | +5.0 | 10x |
| Follow (post üzerinden) | +4.0 | 8x |
| Retweet | +1.0 | 2x |
| Like | +0.5 | 1x (baz) |
| Profile click | **0.0** | eski +12 SIFIRLANDI |
| Mutual'dan reply boost | +15.0 | mutual reply ≈ 4 normal reply |
| Not interested | −43.2 | |
| Mute | −58.8 | mute > block cezası! |
| **Report** | **−234.0** | 1 report ≈ 468 like siler |

- Bookmark ağırlığı param.rs'de YOK — "bookmark 10-12x" iddiaları [TAHMİN].
- Aynı yazarın ardışık postları ×0.5 decay (taban 0.25) → **min 30 dk aralık kuralı
  artık repo-kanıtlı**. Out-of-network erişim ×0.75 iskonto.
- Drafter hedefi: paylaşılabilir + reply çeken içerik. "Kaydet/paylaş değeri var mı?"
  testi like-optimizasyonundan önemli.

### 5.3 Hız kapıları — ilk 15-30 dakika [TAHMİN]

- 0-5 dk: 3+ etkileşim → ilk boost · 5-15 dk: 10+ → out-of-network yayılım ·
  15-30 dk: 50+ → viral kaskad (teract.ai; repo'da yok, yönsel olarak makul).
- Repo kesin gerçek: 48 saatten eski post aday havuzundan DÜŞER. ~6 saatte görünürlük
  yarılanır [TAHMİN].
- Bot aksiyonu: post'u peak saatte at + **ilk 60 dk mention/reply'lara cevap hazır ol**
  (mutual reply +15 boost bunu ödüllendirir). Post at ve kaybol = israf.

### 5.4 Kök tweet'te link cezası — kural sertleşti

- Üçüncü taraf gözlem: kök tweet'te harici link %30-50 erişim kaybı, Premium olmayan
  hesapta daha ağır [TAHMİN — opentweet.io, teract.ai].
- Repo gerçeği: `OpenLinkWeight` sadece 0.2 (reply 5.0'ın 1/25'i) — link tıklaması
  skora neredeyse hiç katkı vermiyor; ayrı bir "link ceza ağırlığı" param.rs'de yok,
  ceza spam heuristics tarafında.
- Mevcut kural AYNEN geçerli ve güçlendi: **link HER ZAMAN ilk reply'a.** Hashtag ≤2
  (fazlası spam classifier tetikler [TAHMİN ~%40 kayıp]).

### 5.5 Original Content Rewards (OCR) — monetizasyon değişti

- Eski ad revenue share **7 Eylül 2026'da bitiyor** (son ödemeler: 14 Ağu, 28 Ağu,
  11 Eyl). **OCR başvuru: 8 Eylül 2026'dan itibaren**, ödemeler 2 haftada bir.
- Eşik: **500 verified follower + 500K Home Timeline impression** (ölçüm penceresi
  doğrulanamadı; Premium şartı muhtemel ama doğrulanamadı).
- Ödeme birimi: **"qualified impression"** = Premium abonenin Home Timeline'da post'un
  ≥%50'sini görmesi → For You sıralaması artık doğrudan gelir.
- Kalifiye içerik: orijinal analiz/rapor, kendi çektiğin görsel/video, özgün yorum.
  Kopya/agregasyon ve engagement farming HARİÇ. cdpilot bench verileri + build-log
  içerikleri "genuine analytical commentary" sınıfına girer — strategist bu formatlara
  ağırlık versin.
- Kaynak: TechCrunch + Android Headlines (2026-08-08); help.x.com/en/using-x/original-content-rewards (2026-08-23'te 403 verdi, basından doğrulandı).

---

Son Güncelleme: 2026-08-23 (§5 eklendi — xai-org/x-algorithm açık kaynak; §1 legacy işaretlendi)
