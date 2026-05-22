# Reply Policy

> "Başkalarının midesini bulandırmadan" yaklaşım. Soft, değer-katmalı, asla promo.
> URL bombası YASAK. Mention bombası YASAK. Self-promo gibi okunan her şey YASAK.

---

## 1. Temel İlke

**Profile click +12 ağırlığı zaten var.** Reply'da link/mention koyma — kişi merak ettiyse profile'ına gider, bio'daki link ve pinned tweet işi yapar.

Reply'ın işi: **değer kat**, link satma.

---

## 2. URL / Repo / npm linki ne zaman gönderilir?

| Durum | Link gönder? |
|---|---|
| Kişi spesifik teknik soru sordu, cevap link gerektirmiyor | ❌ |
| "How can I try it / link var mı / where can I find it" gibi açık talep | ✅ |
| Kendi tweet'imizin altına gelen "tell me more" reply'ı | ✅ (tek mesajda, profesyonel) |
| Random "this looks cool" reply | ❌ — "thanks, more on it in the pinned" gibi soft yönlendir |
| Bir tartışmaya katılıp ürünü tanıtmak için | ❌ ASLA |
| Tier 1 hesabıyla derin teknik diyalog → "wrote about this here" | ✅ tek seferlik blog post linki, npm değil |

### Pratik şablonlar

**Spesifik soru, link gerekmez:**
```
the reason X happens is — [teknik açıklama 2-3 cümle]. you can patch 
it via Page.addScriptToEvaluateOnNewDocument so it survives navigation.
```

**Açık talep "nasıl deneyeyim":**
```
`npx cdpilot launch` to get a CDP-instrumented Brave, then `npx cdpilot 
go <url>`. zero install. full docs in the repo (link in bio).
```

**Tartışma içinde, soft yönlendirme:**
```
wrote up the protocol-level differences last week — pinned tweet has 
the breakdown. tl;dr: ~/X is doing it via WebDriver, cdpilot via raw CDP.
```

---

## 3. Playwright / Selenium / Puppeteer tartışmalarında reply

**Parasitic engagement YASAK.** ("Try cdpilot instead, much better" → mute bölgesi.)

### 3 koşul birden tutmalı (yoksa reply atma):
1. Post **yüksek engagement** (200+ reply VEYA 1000+ like)
2. Post'ta **spesifik teknik acı/soru** var (genel övgü değil)
3. cdpilot'un **gerçekten farklı yaptığı bir nokta** var (sıfır bağımlılık, raw CDP, vs.)

### İçerik formülü (her satırı tutmalı):
- 1. cümle: kişinin acısını teknik olarak adlandır
- 2. cümle: o acının altında ne var, kısa
- 3. cümle: alternatif yaklaşım (cdpilot adını söylemeden veya tek seferlik)
- 4. (opsiyonel): "wrote about this" → pinned'e veya blog'a soft pointer

### Doğru örnek (Playwright-stealth tartışması)
```
the reason Playwright-stealth covers ~half the JS surface is that 
Playwright's CDP relay drops some events. you can hit the same 
patches against raw CDP via Page.addScriptToEvaluateOnNewDocument 
and they actually stick. wrote about it here last week ↓
```
→ Değer var. Saldırı yok. Profile click eder, repo'yu bulur.

### Yanlış örnek (yapma)
```
Playwright is bloated. try cdpilot, zero deps, way faster.
github.com/cdpilot/cdpilot
```
→ Promo bot. Mute.

---

## 4. Tier 1 hesaplarla reply etiketi

**Tier 1** = `engagement-targets.md` listesindeki ana takip ettiklerin (browser-use, addyosmani, paul_irish, anthropics vb.).

- ✅ Spesifik teknik nokta üzerine düşünce ekle
- ✅ Onların paylaştığı konuyu derinleştir
- ❌ Sadece "great post!" reply (algoritma "weak signal" görür, ceza)
- ❌ Aynı kişiye günde 3+ reply (stalker sinyali)
- ❌ İlk reply'ında ürün adı söyleme — önce ilişki, sonra context

---

## 5. Kendi tweet'lerimizin altındaki yorumlar

İki tipte gelir, ikisine farklı muamele:

### Tip A — Teknik soru
- 1-3 cümle teknik cevap
- Soru "nasıl yaparım" ise basit kod örneği (URL DEĞİL, inline kod)
- "Daha fazlasına bak" istiyorsa: **profile/pinned** yönlendir, repo linki vermesi gereken zorunlu durum değil

### Tip B — Övgü/cool
- "thanks, more coming" gibi tek cümle, fazla efor yok
- Premium markası: çok fazla beğeniye teker teker cevap = bot sinyali. Genel teşekkür tweeti at, tek tek yanıtlama.

### Tip C — Eleştiri/şüphe
- ❌ Defansive olma
- ✅ "fair point — here's the limitation honestly: [X]" gibi açık konuş
- Eleştiri tweetimizi paylaşmak/quote etmek için altın fırsat (dürüstlük sinyali +)

---

## 6. Crisis trigger (Bekleme YOK, escalation)

`x-algo-rules.md` §3'teki keyword listesi tetiklenirse:
- Reply DRAFT'ı hazırla, **AMA GÖNDERME**
- Telegram'a `🚨 URGENT` prefix
- Kullanıcı manuel onaylayana kadar bekle

Özellikle hassas:
- Politik / sosyal mesele
- "scam / fraud / fake" iddiası  
- Legal / IP iddiası
- Kişisel saldırı / küfür içeren reply

---

## 7. Reply timing

Bkz: `reply-timing.md` — inbound/outbound bekleme süreleri orada.

Reply policy timing kuralları ile uyumludur. İçerik politikası BU dosyadadır, ne zaman atılacağı `reply-timing.md`'dedir.

---

## 8. Self-check her reply'da

- [ ] Soruyu somut çözüyor muyum? (yoksa yazma)
- [ ] URL/link koymadan da değer veriyor mu? (varsayılan: link YOK)
- [ ] Mention yapmadan da kişi profile'ıma tıklayabilir mi? (bio çekiyor diye)
- [ ] Promosyon dili var mı? ("try our", "check out", "much better") → SİL
- [ ] Kişiye sorulu/eşit tonda mı, üstten mi konuşuyorum? → eşit ton
- [ ] Premium beğeniye genel teşekkür mü, tek tek yanıt mı? → genel
- [ ] Crisis keyword var mı? → URGENT escalate

---

Son Güncelleme: 2026-05-21
