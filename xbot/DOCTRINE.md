# cdpilot xbot — Master Doctrine

> **Claude (xbot)** = strateji + karar
> **Nadir** = onay + veto
> **srv21 sistem** = operasyon (görünmez)
>
> Hesap 100% Claude'un yargısıyla yönetilir. Nadir Telegram'da tek tıkla onay/red verir,
> manuel müdahale gerektiren tek nokta. Geri kalan her şey — neyin atılacağı, ne zaman,
> kime cevap verileceği, kimi takip edileceği, hangi trende girileceği, hangi
> deneyin yapılacağı — Claude tarafından önerilir ve Nadir onaylayınca uygulanır.

---

## 1. Üç katman

### Strateji (Claude'un işi)

Bu katmandaki kararlar **veri + bağlam + judgement** gerektirir. Otomatik üretilemez,
Claude'un her gün düşünüp önermesi gerekir.

1. **Günlük içerik kararı** — bugün ne pillar, ne format, ne timing, ne hook
2. **Haftalık tema** — bu hafta neye odaklanıyoruz (bench? release? ekosistem?)
3. **Aktif deneyler** — şu an hangi A/B çalışıyor (URL-in-reply, image style, vd.)
4. **KPI assessment** — geçen hafta ne işe yaradı, hangi format/saat/topic kazandı
5. **Engagement hedef seçimi** — bu hafta hangi Tier 1'lerle daha sık etkileşim
6. **Trend kararı** — bugün hangi trende cevap veriyoruz, hangisini geçiyoruz
7. **Reply tonu** — her gelen yoruma özel cevap (mevcut: AI drafter)
8. **Crisis response** — ratio/shadowban tetiklenirse hangi recovery patikası
9. **30-günlük backlog güncellemesi** — sürpriz olaylara göre planı revize et

### Operasyon (sistem'in işi — görünmez)

Bu katmandaki şeyler manuel müdahale gerektirmez. Cycle'da otomatik döner.

- Posting (poster_twikit) · Mention/reply scraping (mention_scraper)
- AI reply drafting (reply_drafter) · Engagement scanning (engagement_scanner)
- Follow proposals (follow_manager) · DM monitoring (dm_handler)
- Crisis detection (crisis_check) · URL-in-reply mechanics (followup_text)
- Image generation (image_gen) · Length/reply-bait validation (bridge)
- Cycle orchestration (run_cycle, 4x/gün) · Telegram daemon (approval loop)

### Onay (Nadir'in işi — minimal)

Mobile-first, tek tıkla. Telegram bot UI tek arayüz.

- Draft kararı: ✅ Onayla / 🔁 Tekrar / ⏭ Geç
- AI reply: ✨ AI taslağı / 💬 Manuel / 💛 Like / ⏭ Atla
- Follow proposal: ✅ / ⏭
- Crisis alarm: oku, gerekirse `crisis_check --clear`

---

## 2. Mevcut sistem (operasyon katmanı tamam)

✅ poster_twikit, mention_scraper, reply_drafter, engagement_scanner, follow_manager,
   dm_handler, crisis_check, image_gen, telegram_bridge, run_cycle, grok_provocation

Geriye **strateji katmanı** kalıyor — Claude'un her gün/hafta düşünüp önerdiği
kararlar. Bu doktrinin kurulumu bundan sonraki iş.

---

## 3. Strateji katmanı — kurulum sırası (ideal → şu an)

### Faz A: Karar Üretimi (bu hafta)

1. **Daily Strategist** (`ops/daily_strategist.py`) — her sabah 08:00 cycle başı:
   - Geçen 24h KPI'yı oku · aktif deneylerin durumunu tara · trend listener
     çıktısını al · pillar mix'i denge · bugünün CONCRETE önerisini üret:
     "bugün Pillar X, format Y, saat HH:MM, hook Z, görsel A — neden:" → Telegram'a kart

2. **Weekly Strategist** (Pazar 22:00) — `ops/weekly_review.py`:
   - Hafta KPI · top/bottom posts · format ROI · follower delta · audience saat dağılımı
   - Çıktı: 1 sayfalık rapor Telegram'a + gelecek haftanın 7 günlük backlog'unu öner

3. **Trend Listener** (`ops/trend_scan.py`) — günlük 09:00 ve 17:00:
   - HN top stories (zaten var) · X niş trending search · GitHub trending in niş
   - Bizim niş için "şu an konuşulan" konuları çıkar → Telegram'a 3 candidate öner

4. **Search-to-Respond** (`ops/search_respond.py`) — günlük 13:00:
   - X search: "playwright stealth not working", "captcha bypass", "cdp protocol",
     "browser automation help", + 5-10 niş soru pattern'i
   - Yüksek-takipçili (5k+) ve son 24h içindeki soru tweet'lerini bul
   - Her birine AI reply drafter ile cool cevap üret → Telegram'a 3 öneri/gün

### Faz B: Ölçüm (1-2 hafta sonra anlam kazanır)

5. **Best-Time-to-Post Learning** — analytics'te aktif: bizim audience'ımızın
   peak'leri ne, statik 17-19 / 22-01 dışında?
6. **Follow-Back Tracker** — yaptığımız her follow 7 gün içinde follow-back aldı mı?
7. **Format ROI Tracker** — single/thread/image/URL-in-reply hangisi en yüksek
   follower/engagement getiriyor
8. **Hashtag Intelligence** — Tier 1 hangi tag'leri kullanıyor, hangileri reach getiriyor

### Faz C: İleri Otomasyon (Faz 0.5+)

9. **Content Backlog Generator** — weekly review çıktısı → 7 günlük taslak hattı
10. **Reply-Velocity Booster** — bizim post'umuza geç gelen reply'i hızlı yakala,
    cevap ver → tweet'i algoritmik olarak yeniden surface et
11. **Conductor Teaser Calendar** — Faz 0.5+ (Hafta 3+) imalı teaser'lar
12. **X Articles haftalık** — Faz 1+ uzun-form (Pazar yayın)

---

## 4. Kararların yürütüldüğü protokol

```
Sabah 08:30 cycle başında:
  ↓
  Daily Strategist çalışır:
    • Geçen 24h KPI oku
    • Aktif deneyleri kontrol et
    • Pillar denge hesapla
    • Trend listener çıktısını oku
    • TODAY'S RECOMMENDATION üret (concrete):
      "Bugün: Pillar 'LLM tip', tek tweet, 17:23 TR, hook: 'X works because Y'
       hashtag: yok, görsel: Field Notebook style 'a printed snippet with...',
       reply-bait: 'right?' ile bitir. Neden: ekosistem pillar'ı 2 gündür eksik,
       17:23 statik peak içi + audience pattern'ine uygun, görsel boost.
       Cost: 1 image (~$0.04) + 1 tweet."
  ↓
  Telegram'a kart: önerinin tam metni, AI image preview, [✅ Bugün bunu yap]
  ↓
  Onaylarsan: image_gen + drafter + queue → 17:23'te poster atar
  Beğenmediysen: Telegram'a reply'la "X yerine Y" yaz → revize edip yeniden öner
```

---

## 5. Şeffaflık + audit

- `audit/strategy-YYYY-MM-DD.jsonl` — günlük her öneri + onay/red kararı + nedeni
- `audit/weekly-YYYY-WW.json` — haftalık rapor snapshot
- 90 gün retention. Geriye dönük "neden o gün şu kararı verdim" sorgulanabilir.

---

## 6. İstisnalar — onaysız atış (gelecekte)

Faz 0'da **HER ŞEY** onaya tabi. Faz 1+ (1000+ takipçi sonrası) belirli düşük
risk aksiyonları onaysız atılabilir:

- Tier 1 reply'lerine like (skor ≥ 7) — onaysız
- @grok provokasyon (haftalık 1) — onaysız
- AI reply drafter çıktısı, reply-bait skoru 3/3 + length < 200 char ise — onaysız

Bu eşik **Nadir tarafından açıkça** kullanıma alındığında geçerli. Default = her şey
onaylıdan geçer.

---

Son güncelleme: 2026-05-22
