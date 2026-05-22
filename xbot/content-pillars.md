# xbot — Content Pillars (Revised 2026-05-21)

> Nadir feedback (2026-05-21): "self-deprecation azalsın, mix genişlesin, vaatler tamamlansın,
> conductor / diğer makinedeki projeler ileride teaser olarak girsin."

---

## Yeni pillar karışımı (Hafta 2+)

| % | Pillar | Örnek |
|---|---|---|
| 35% | **cdpilot ürün** — feature, recipe, bench | "shipped v0.6.1 — per-host cookies safe-list" |
| 25% | **LLM/AI/vibe-coder ipuçları** | "most agent stacks miss Page.setDownloadBehavior" |
| 20% | **Az bilinen ama iyi repolar** | rebrowser-patches, twikit, anubis, vd. |
| 10% | **Behind-the-scenes** — kararlar, tradeoffs | "why we chose Option C for TLS" |
| 10% | **Teaser** — gizli proje sızıntıları (Faz 1+) | conductor, kokpit, mastershop, vd. |

cdpilot artık posts'un yarısı değil. Marka olarak değer üretmek > kendini reklam etmek.

---

## Vaat takibi (ZORUNLU)

Vaat eden tweet → mutlaka kapanış zinciri. Kayıt:

| Tweet | Vaat | Kapanış |
|---|---|---|
| `fz0-2` | "thread incoming." | `fz0-2-thread-1..5` (queue'da, Hafta 2 aralığında) |
| _gelecek_ | "v0.9 target" | v0.9.0 release post + comparison thread |

**Kural:** Vaat eden bir tweet'i atmadan önce kapanışı planlı olmalı. Eğer kapanış 1 hafta içinde yapılamayacaksa vaat kelimesini ("thread incoming", "next post", "soon") **kullanma**.

---

## Teaser stratejisi: Conductor + diğer makinedeki projeler

Şu an Faz 0 (sıfır-km hesap). Conductor + sair projeler teaser olmak için çok erken — önce ana persona (cdpilot kurucusu, browser/automation expert) oturmalı.

### Faz timeline

| Faz | Hafta | Conductor sızıntısı |
|---|---|---|
| Faz 0 | 1-2 | YOK — sadece cdpilot ekosistem işleri |
| Faz 0.5 | 3-4 | İmalı 1-2 post: "i have a private orchestration setup that..." (proje adı yok) |
| Faz 1 | 5-8 | "the orchestration thing has a name now: Conductor. it does X, Y, Z." (still WIP) |
| Faz 2 | 3-4 ay | "shipping `cdpilot launch` from Conductor in a few lines — here's how" |
| Faz 3 | 5+ ay | Conductor public alpha (eğer yayımlanırsa) |

### Diğer makine projeleri (yan-tema kaynakları)

Hepsi bir gün öne çıkabilir ama önce şu an alakalı olanları öne çıkar:

- **inventory-shelf, mastershop** — e-commerce / vendor tooling tarafı (eğer cdpilot kullanım örneği varsa)
- **konu-poster-uretim, blog-writer, ads-ai** — content/SEO/AI dünyası (LLM pillar'ı için kaynak)
- **bilet-alarmi-app, tcdd-bilet-bot** — automation acı örnekleri (browser/CDP narrative ile uyumlu — "i built a TCDD bot once and learned X about anti-bot")
- **interactive-software, yds-digital** — eğitim teknolojisi (uzun vade, ayrı persona riski)
- **x-bookmarked, wa-chat-history** — kişisel araçlar (yan teaser olabilir)
- **kokpit** — devops/sunucu görselleştirme (ileride Conductor ile bağlandığında ortaya çıkar)

### Teaser anatomisi

İyi teaser = curiosity gap + concrete detail + no fake hype.

❌ "i'm building something big" — boş.
❌ "wait until you see what's coming" — pazarlamacı tonu.
✅ "i have an orchestration setup that delegates 70% of my coding to Gemini Flash and keeps Claude as the architect. one day i'll ship it." — somut + merak uyandıran.

---

## Tone audit (ANTI-PATTERN)

Yarın atılan her draft'ı şu kontrolden geçir:

| ❌ Anti-pattern | ✅ Yerine |
|---|---|
| "honest disclaimer: still leaks X" | "the X category is a future problem — here's why" |
| "i know what every line costs" | "the interesting thing about line N is..." |
| "no MITM, no fork" (defansif) | "investing in behavioral layer is healthier" (positive frame) |
| "this is acemi" yaklaşımları | "this is the part i find interesting" |
| Kendine güvensizlik | Observational curiosity |

---

## Engagement → push CDP'yi yavaş

Reply ve quote tweet'lerde cdpilot bahsetmek ZORUNLU değil. Eğer:
- Soru cdpilot ile direkt alakalı → bahset
- Soru genel browser/CDP/automation → cdpilot anekdot olarak EN ÇOK 1 cümle, geri kalanı genel bilgi
- Soru tamamen başka konu → cdpilot bahsetme, kazanılan trust > kazanılan impression

Aralara serpiştirmek bu demek. Marka değer üretiyor, kendini ezberlemiyor.

---

---

## URL-in-reply taktiği (15 gün sıkı takip — 2026-05-21 başladı)

X HeavyRanker dış URL içeren tweet'leri hafifçe baskılıyor (-1 ila -3 weight).
Bu yüzden link içeren post'larda body link-free tutulur, link **ilk reply'a** otomatik
self-reply olarak atılır. Poster (`poster_twikit.py`) bunu `followup_text` field'ı
ile destekler.

### Ne zaman uygula
| Tip | URL nereye |
|---|---|
| Repo / gem highlight | body link-free, `followup_text` → ilk reply |
| Blog / release post | aynı pattern |
| Quote tweet | quote URL body'de OK (quote zaten link-friendly) |
| Reply chain | body'de OK (reply'lar link-penalty almıyor) |
| URL'siz tip / tool ismi | sorun yok |

### 15 günlük doğrulama protokolü (2026-05-21 → 2026-06-05)
Her URL'li post için kayıt:
- impressions (24h, 7d)
- engagement (likes, replies, profile clicks)
- followup reply'ın kendi impression'ı

Karşılaştırma: link-in-body vs link-in-reply. Gain (impression delta) %15+ ise
patterni kalıcı yapacağız; değilse drop. Sonuç `xbot/url-reply-experiment.md`'ye yazılacak.

### Draft schema
```json
{
  "id": "gem-001-rebrowser",
  "kind": "tweet",
  "text": "an underrated repo: rebrowser-patches.\n...\nlink below ↓",
  "followup_text": "→ github.com/rebrowser/rebrowser-patches"
}
```

`kind == "tweet"` olduğunda poster `followup_text`'i 12-45s sonra (insan tipi gap)
parent tweet'e reply olarak atar.

---

Son güncelleme: 2026-05-21 (URL-in-reply taktiği + 15-day experiment)
