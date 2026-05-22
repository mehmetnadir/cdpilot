# Cold-Start Calendar — 12 Haftalık Çerçeve

> @cdpilot_dev için sıfır-takipçi → 300+ organik takipçi → otomasyona hazır.
> Her ay sonu **re-eval**: pillar dağılımı, trend kayması, voice tutarlılığı.
> Detay günlük plan **playbook.md** Step 4-5'te canlı üretilir.

---

## Faz 0 — Hafta 1-2: "Tek Şey Adamı"

**Strateji:** Hesap "cdpilot adamı" diye tanınmalı. 4 pillar henüz YOK.

| Metrik | Hedef |
|---|---|
| Tweet/hafta | 3 (kalite > volume) |
| Reply (outbound) | 30-50/hafta |
| Follow | 3-5/gün (toplam 30-50/hafta) |
| Quote / Retweet | 0 (henüz erken) |
| İçerik konusu | %100 cdpilot |

**Tweet temalar (örnek):**
- "Yesterday I shipped v0.8.0. Stealth Bench V1 result: 29/80 (36.25%). Here's what worked and what didn't"
- "Why cdpilot doesn't use Selenium, Playwright, or Puppeteer" (kısa argüman)
- "The TLS fingerprint ceiling: an honest limitation post"
- "5 lines of cdpilot vs 50 lines of Playwright" (kod örneği)
- "What I learned re-running my own bench 7 times in a row"

**Reply hedefleri:**
- Tier 1 hesapların (`engagement-targets.md`) son tweet'lerine değer kat
- Browser automation hashtag/keyword aramaları
- AI agent topluluğu (browser-use, OpenAI agents, Anthropic Computer Use)

**Hafta sonu re-eval:**
- En çok impression alan tweet ne idi? — gelecek hafta o pattern + bir varyasyon
- Hangi reply'lar reply çekti? — o hesaplarla diyalogu derinleştir

---

## Faz 0.5 — Hafta 3-4: İlk Yan Pillar + İlk Hot-Take

**Strateji:** "cdpilot adamı" konumlanmış, şimdi adjacent topic'i aç → **stealth engineering**.

| Metrik | Hedef |
|---|---|
| Tweet/hafta | 4 |
| Reply (outbound) | 50-70/hafta |
| Follow | 5-7/gün |
| Quote / Retweet | 1-2 quote/hafta |
| Tweet pillar dağılımı | %60 cdpilot, %30 stealth engineering, %10 ekosistem yorumu |
| İlk THREAD | Hafta 3 sonu |

**Tweet temalar:**
- İlk hot-take thread: "Playwright stealth plugins are %80 of the time wrong. Here's why" (kanıtla)
- "TLS fingerprint: the layer everyone ignores until Akamai blocks them"
- "Behavioral entropy ≠ random delays. The real Gauss + Bezier story"
- "browser-use's official bench: what 10 cdpilot bench runs taught me about benchmark design"

**Reply hedefleri:**
- Tier 1 dışında: organic discovery — kim cdpilot/stealth/browser konularında konuşuyor
- İlk reply-zincirlerine gir, "real conversation" başlat

**Hafta sonu re-eval:**
- Thread metrikleri (reply, RT, profile click) sıradan tweet'lerin kaç katı?
- Hot-take direnci nasıl? Polemik mi yarattı, ders mi verdi?

---

## Faz 1 — Hafta 5-8: Pillar Genişleme

**Strateji:** 4 pillar dengeli kullan. İlk 100-300 takipçi organik gelmeli.

| Metrik | Hedef (h5-6) | Hedef (h7-8) |
|---|---|---|
| Tweet/hafta | 5-6 | 7-8 |
| Reply (outbound) | 70-100/hafta | 100-130/hafta |
| Follow | 7-10/gün | 10/gün |
| Quote / Retweet | 2-3 quote/hafta | 3-4 quote/hafta |
| Thread | 1/hafta | 2/hafta |
| Takipçi hedefi | 100-150 | 200-300 |

**Pillar dağılımı:**
- cdpilot insights: %40
- Stealth/anti-bot engineering: %25
- Browser/AI agent ekosistem yorumu: %25
- Recipe / 5-line tutorial: %10

**Tweet temalar:**
- Recipe: "Scrape any single-page-app in 5 cdpilot commands"
- Ekosistem: "browser-use 0.12 released — here's what's notable" (gerçek yorum)
- Stealth: "JA3 vs JA4 — practical differences for stealth"
- cdpilot: "v0.9 design log: how we're tackling the TLS layer"

---

## Faz 2 — Ay 3-4 (Hafta 9-16): Yarı-otonom Geçiş

**Strateji:** Voice anchor birikti (60-80 onaylı tweet). T1 otonomiye geçiş.

| Metrik | Hedef |
|---|---|
| Tweet/gün | 1-2 |
| Reply (outbound) | günde 10-15 |
| Thread | haftada 2-3 |
| Quote tweets | günde 1-2 |
| Cowork x daily | 3-4 invocation (sabah, öğlen, akşam, gece) |
| Telegram batch approval | aktif |
| Takipçi hedefi (ay 4 sonu) | 500-1000 |

**Pillar dağılımı sabit:**
- cdpilot: %35
- Stealth: %25
- Ekosistem yorumu: %25
- Recipe / use-case: %15

**Yeni format'lar:**
- Weekly "build log" thread (her cuma)
- Monthly "ecosystem state" thread (ayın 1'i)
- Hot-take Friday: cesur ama dayanaklı görüş

---

## Faz 3 — Ay 5+: Full Cadence

**Strateji:** Sistemli olarak hergün 3-4 tweet + 15-20 reply. Hâlâ Telegram batch onay (T1 final hal).

| Metrik | Hedef |
|---|---|
| Tweet/gün | 3-4 |
| Reply (outbound) | günde 15-20 |
| Follow | doğal (organic ramp) |
| Thread | haftada 3-4 |
| Cowork x daily | 4 invocation |
| Takipçi hedefi (ay 6 sonu) | 2000-5000 |
| Faz 3 sonu | "T2 Selective Auto" değerlendirme noktası |

---

## Aylık Re-evaluation Protokolü

**Her ayın 1'i Cowork bunu yapacak (`playbook.md` Step Aylık):**

1. **Trend tarama (discovery scan):**
   - GitHub trending: AI/browser/automation keyword'leri son 30 gün
   - HN: en çok upvote AI/browser konuları
   - arXiv: yeni paper'lar (browser agents, anti-bot detection)
   - X search: hashtag trendleri ekosistemde

2. **Pillar tartı:**
   - Geçen ayda hangi pillar en çok engagement getirdi? — gelecek ay %5 artır
   - Hangisi boğuldu? — %5 azalt veya zaviye değiştir
   - Yeni bir trend var mı? — yeni pillar eklenebilir mi?

3. **Voice anchor sample:**
   - Geçen ayın TOP 10 tweet'ini "voice anchor" klasörüne ekle
   - Yeni draft generation few-shot örneklerinde kullanılacak

4. **Crisis post-mortem:**
   - Crisis trigger ne sıklıkta tetiklendi? Yanlış pozitif var mı? Keyword listesi rafine

5. **Sonraki ayın günlük plan iskeleti:**
   - 30 gün için her gün tweet konusu (broad — playbook günlük detaylandırır)

---

## İlgi alanı kayması — adaptif sistem

**Sabit pillar'lar yok.** Yıl içinde:
- Ay 1-3: cdpilot + stealth + browser ekosistem (kuruluş)
- Ay 4-6: + AI agent + LLM tooling commentary (genişleme)
- Ay 7-9: + scraping/data engineering (use-case derinleşmesi)
- Ay 10-12: trend ne ise — community demand'a göre pivot

**Pivot kuralı:** Yeni topic ancak şu üçü tutarsa eklenir:
1. Mevcut audience'la kesişiyor (browser-automation Venn)
2. cdpilot'un teknik avantajıyla bağlanabiliyor
3. Senin gerçek ilgi alanın (sahte iddia = anlaşılır)

---

Son Güncelleme: 2026-05-20
