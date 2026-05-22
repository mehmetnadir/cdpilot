# URL-in-Reply A/B Experiment (15 gün)

> **Hipotez:** HeavyRanker'ın URL-penalty ağırlığı (-1 ila -3) yüzünden body link'siz +
> ilk reply'da link içeren post'lar, body'de URL içeren post'lardan **+15-40%
> impression** alır.
>
> **Süre:** 2026-05-21 → 2026-06-05 (15 gün)
> **Pattern:** poster_twikit'in `followup_text` mekanizması ile otomatik

---

## Metrik kayıtları

| post_id | kind | url_loc | impressions_24h | impressions_7d | likes | replies | profile_clicks | followup_impr |
|---|---|---|---|---|---|---|---|---|
| _(daily_analytics dolduracak)_ | | | | | | | | |

## Karar kuralı (2026-06-05'te)

- **+15% gain veya üstü** → kalıcı pattern, tüm URL'li post'lara
- **0-15% gain** → durum nötr, body-URL daha tipik / okunabilir; pattern opsiyonel
- **<0% (gerileme)** → drop, body-URL'ya dön

## Önyargı kontrolü

Aynı 15 gün içinde tutarsız değişkenler:
- Saat (sabah vs akşam) — random'a yakın dağıtmaya çalış
- Tipler — gem/repo/blog karışık olmalı, sadece bir kategori değil
- Hesap yaşı — günler ilerledikçe baseline değişir, mutlak değil **göreceli** ölçüm

Bir günde 3+ URL'li post atma; daily_analytics'in günlük baseline'ı bozulur.

---

Son güncelleme: 2026-05-21
