# X (Twitter) Algorithm — Pratik Kurallar

> Kaynak: `twitter/the-algorithm` repo, HeavyRanker model ağırlıkları (2023 açık kaynak release + topluluk gözlemleri).
> Bu dosya her draft için **self-check** olarak uygulanır.

---

## 1. Ağırlık tablosu (HeavyRanker)

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

Son Güncelleme: 2026-05-20
