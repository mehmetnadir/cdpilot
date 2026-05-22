# Queue Schema — cdpilot Twitter Bot

Schema v1.0. `queue_executor.py` ve Cowork'ün ortak veri sözleşmesi.

---

## 1. Dosya Yolu Konvansiyonu

| Ortam | Dizin | Dosya adı |
|-------|-------|-----------|
| Mac (dev) | `~/cdpilot-twitter-data/queue/` | `YYYY-MM-DD.json` |
| Server (prod) | `/opt/cdpilot-twitter-bot/queue/` | `YYYY-MM-DD.json` |
| Bugünün kopyası | `~/cdpilot-twitter-data/queue/` | `today.json` (cp, symlink değil) |

---

## 2. Top-Level Yapı

```json
{
  "date": "YYYY-MM-DD",
  "day_n": 42,
  "track": "T1 Foundations",
  "generated_at": "2026-05-19T08:00:00+03:00",
  "generated_by": "cowork",
  "posts": []
}
```

| Alan | Type | Açıklama |
|------|------|----------|
| `date` | string (YYYY-MM-DD) | Kuyruğun ait olduğu gün |
| `day_n` | integer | Launch'tan kaçıncı gün (1-indexed) |
| `track` | string | Günün içerik track'i (T1–T6) |
| `generated_at` | string (ISO8601+tz) | Cowork'ün üretim zamanı |
| `generated_by` | `"cowork"` \| `"manual"` \| `"cowork-v2"` | Üretici kaynağı |
| `posts` | array | Post item'ların listesi |

---

## 3. Post Item Schema

### Alan Tablosu

| Field | Type | Required | Default | Açıklama |
|-------|------|:--------:|---------|----------|
| `id` | string (uuid4) | **Evet** | — | Benzersiz item ID. `str(uuid.uuid4())` |
| `type` | `"post"` \| `"thread"` \| `"reply"` \| `"pin"` \| `"unpin"` \| `"like"` \| `"unlike"` \| `"retweet"` \| `"unretweet"` \| `"bookmark"` \| `"follow"` \| `"unfollow"` | **Evet** | — | Gönderi/aksiyon tipi |
| `scheduled_time` | string (ISO8601+tz) | **Evet** | — | Planlı gönderim zamanı. Örn: `"2026-05-19T17:00:00+03:00"` |
| `status` | `"pending"` \| `"done"` \| `"failed"` \| `"skipped"` | **Evet** | `"pending"` | Mevcut durum |
| `content` | string \| null | *Koşullu* | `null` | `type=post` ve `type=reply` için **zorunlu**. Max 280 chars (long_form=true ise 25000). |
| `thread` | array of strings \| null | *Koşullu* | `null` | `type=thread` için **zorunlu**. Min 2 eleman. Her eleman max 280 chars. |
| `reply_to` | string \| null | *Koşullu* | `null` | `type=reply` için **zorunlu**. Hedef tweet ID (string, sayısal). |
| `pin_target` | string \| null | *Koşullu* | `null` | `type=pin`/`unpin` için **zorunlu** (kendi tweet ID'si veya `"latest"` literal'i — executor `result_url` history'sinden son `done` post'u alır). |
| `long_form` | boolean | Hayır | `false` | `true` ise content 280 limit'i 25000'e çıkar (Premium). |
| `quote_url` | string \| null | Hayır | `null` | Set ise post quote tweet olur. X status URL formatı (`https://x.com/<user>/status/<id>`). |
| `poll` | object \| null | Hayır | `null` | `{options: [s1,s2,...], duration_hours: int}` — options 2-4 eleman, her biri max 25 char; duration_hours ∈ {6, 24, 72, 168}. |
| `media` | array \| null | Hayır | `null` | `[{path: "abs/path", alt_text: "..."}, ...]` — max 4 eleman, alt_text Premium'da 1000 char'a kadar. |
| `result_url` | string \| null | Hayır | `null` | Başarı sonrası executor tarafından doldurulur. |
| `error` | string \| null | Hayır | `null` | Hata sonrası executor tarafından doldurulur. |
| `humanizer_seed` | integer | Hayır | random | Delay re-run determinism. Pozitif integer. |
| `carry_over` | boolean | Hayır | `false` | Önceki günden taşındıysa `true`. |
| `tags` | array of strings | Hayır | `[]` | `["hook", "thread", "educational", "viral", "engagement", "poll", "quote", "long_form", "media"]` |
| `engagement_reply_to` | string \| null | Hayır | `null` | Engagement plan'dan hedef tweet ID. |
| `pin_after_post` | boolean | Hayır | `false` | `type=post|thread|long_post` için — başarılı post sonrası otomatik pin. Önceki pin varsa unpin et. |
| `target_tweet_id` | string \| null | *Koşullu* | `null` | `type=like|unlike|retweet|unretweet|bookmark` için **zorunlu**. Hedef tweet ID. |
| `target_handle` | string \| null | *Koşullu* | `null` | `type=follow|unfollow` için **zorunlu**. `@` olmadan handle. |
| `source` | string \| null | Hayır | `null` | Aksiyon nereden geldi: `"engagement-target"`, `"discovery"`, `"reciprocity"`, `"trending"`, `"manual"`. Analytics için. |
| `reason` | string \| null | Hayır | `null` | Neden bu aksiyon — review için tek satır gerekçe. Örn: `"replied to my T2 thread, returning the engagement"`. |

### Type Constraint'leri

**Content actions** (üretici — bizim hesabımızdan çıkan içerik):

| Type | content | thread | reply_to | pin_target | quote_url | poll | media |
|------|---------|--------|----------|------------|-----------|------|-------|
| `post` | **zorunlu** | null | null | — | opsiyonel | opsiyonel | opsiyonel |
| `thread` | null | **zorunlu** (min 2) | null | — | — | — | opsiyonel (her tweet için ayrı) |
| `reply` | **zorunlu** | null | **zorunlu** | — | — | — | opsiyonel |
| `pin` | null | null | null | **zorunlu** | — | — | — |
| `unpin` | null | null | null | **zorunlu** | — | — | — |

**Engagement actions** (etkileşim — başkalarının içeriğine yapılan aksiyonlar):

| Type | target_tweet_id | target_handle | content |
|------|-----------------|---------------|---------|
| `like` | **zorunlu** | — | — |
| `unlike` | **zorunlu** | — | — |
| `retweet` | **zorunlu** | — | — |
| `unretweet` | **zorunlu** | — | — |
| `bookmark` | **zorunlu** | — | — |
| `follow` | — | **zorunlu** | — |
| `unfollow` | — | **zorunlu** | — |

**Not**: `quote` ayrı bir type değil; `type=post` + `quote_url` set kombinasyonu quote tweet üretir. Poll, long-form, media — hepsi `type=post`'un opsiyonel modifier'ları. Schema geriye uyumlu — mevcut sadece-content post'lar etkilenmez.

### Engagement Rate Limits (daily caps — playbook tarafından enforce edilir)

X anti-spam classifier bot patterns'i (ani burst, yüksek hacim) tetiklerse hesap kısıtlanır. Daily cap önerileri (yeni hesap için, established hesap %50 daha fazla destekler):

| Action | Daily cap | Notlar |
|--------|-----------|--------|
| `like` | 30 | Önemli olan: aynı handle'a 24h içinde max 3 like |
| `retweet` | 8 | Aşırı RT spam classifier'a girer |
| `bookmark` | 50 | Private aksiyon, rate sınırı daha gevşek |
| `follow` | 15 | Bulk follow algılanır; ramp-up gerek |
| `unfollow` | 10 | "Follow-unfollow" pattern'i ban riski |
| `reply` (engagement) | 20 | Aynı handle'a 24h içinde max 2 reply |
| `quote` | 5 | Kalite > miktar |

Cap aşılırsa: queue'ya eklenir ama executor `status=skipped` + reason yazar.

### Status Geçiş Kuralları

```
pending ──→ done
pending ──→ failed
pending ──→ skipped

(Geriye dönüş yoktur)
```

---

## 4. Validation Kuralları

1. `id` — uuid4 formatında olmalı, dosya içinde benzersiz.
2. `scheduled_time` — timezone bilgisi içermeli (UTC offset veya Z).
3. `content` uzunluğu — max 280 Unicode karakter (Twitter limiti).
4. `thread` her elemanı — max 280 karakter.
5. `humanizer_seed` — pozitif integer (0 dahil).
6. `carry_over=true` ise — orijinal gün `scheduled_time` değil, taşınan gün saati kullanılmalı.
7. `reply_to` — tweet ID, sayısal string. URL değil. Örn: `"1924567890123456789"`.

---

## 5. Tam Örnek JSON

```json
{
  "date": "2026-05-19",
  "day_n": 19,
  "track": "T3 Use Cases",
  "generated_at": "2026-05-19T09:15:00+03:00",
  "generated_by": "cowork",
  "posts": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "type": "post",
      "scheduled_time": "2026-05-19T14:05:00+03:00",
      "status": "pending",
      "content": "Browser automation without a driver binary. No version mismatch, no Java process. Just a WebSocket.",
      "thread": null,
      "reply_to": null,
      "result_url": null,
      "error": null,
      "humanizer_seed": 2741,
      "carry_over": false,
      "tags": ["educational"]
    },
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "type": "thread",
      "scheduled_time": "2026-05-19T17:00:00+03:00",
      "status": "pending",
      "content": null,
      "thread": [
        "Most scraping tools break when a site deploys Cloudflare. Here's how cdpilot handles it",
        "Step 1: Detect the challenge page before spending time parsing bad HTML. cdpilot captcha-check exits 2 if blocked.",
        "Step 2: Stealth layer — patches webdriver tell, plugins, WebGL fingerprint. Zero deps, pure JS injection.",
        "Step 3: If still blocked — save the clearance cookie. Next run replays it. cdpilot cookies save / load."
      ],
      "reply_to": null,
      "result_url": null,
      "error": null,
      "humanizer_seed": 8832,
      "carry_over": false,
      "tags": ["hook", "thread", "viral"]
    },
    {
      "id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
      "type": "reply",
      "scheduled_time": "2026-05-19T21:30:00+03:00",
      "status": "pending",
      "content": "exactly — the driver abstraction layer is where most latency hides. direct CDP is not that scary once you see the raw frames",
      "thread": null,
      "reply_to": "1924100000000000001",
      "result_url": null,
      "error": null,
      "humanizer_seed": 391,
      "carry_over": false,
      "tags": ["engagement"],
      "engagement_reply_to": "1924100000000000001"
    },
    {
      "id": "d4e5f6a7-b8c9-0123-defa-234567890123",
      "type": "post",
      "scheduled_time": "2026-05-19T21:00:00+03:00",
      "status": "done",
      "content": "Carried over from yesterday. CDP is not Selenium.",
      "thread": null,
      "reply_to": null,
      "result_url": "https://x.com/nadirabbas/status/1924200000000000001",
      "error": null,
      "humanizer_seed": 105,
      "carry_over": true,
      "tags": ["educational"]
    }
  ]
}
```

---

## 6. Versiyon Notu

- **Mevcut:** Schema v1.0
- **Breaking change kuralı:** Yeni alan zorunlu hale gelirse veya tip değişirse → `generated_by` değeri `"cowork-v2"` (ya da `"cowork-v3"`) olarak güncellenir. `queue_executor.py` bu tag'e bakarak backward compat sağlar.
- **Non-breaking change:** Opsiyonel alan ekleme → minor versiyon, `generated_by` değişmez.
