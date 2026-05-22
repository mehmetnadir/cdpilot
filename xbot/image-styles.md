# cdpilot — Signature Visual Style: "Field Notebook"

> Tek bir görsel imza. AI gibi hissettirmemek için fotografik + analog.
> Her görselin alt sağ köşesinde cdpilot logo + `@cdpilot_dev` yer alır
> (görselin içinde değil, post-process'te composit).

---

## Kural

**Her görsel aynı stilde üretilir.** Karışıklık YOK. Tutarlılık marka.

Tek stil = "field notebook":
- Üstten çekilmiş (flat-lay) bir Moleskine-tipi defter sayfası
- Krem rengi kağıt (#f4ebd6), hafif doku, sayfa kenarları görünür
- İçerik: kurşun kalemle yazılmış başlık + teknik bir çizim / yazıcı çıktısı / post-it
- Reel aksesuar: kahve halkası, kağıt klips, kurşun kalem, küçük bir post-it
- Işık: öğleden sonra yan pencere ışığı, sol üstten — yumuşak, sıcak
- Kameraya bakan ekran YOK. Eğer cihaz varsa açıyla, ekran görünmez.
- ⚠️ **Alt sağ köşe BOŞ kalır** — logo+watermark oraya post-process'te basılır

---

## Renk paleti (sabit)

- Kağıt krem: **#f4ebd6**
- Grafit/yazı: **#3a3835**
- Amber accent (logo'dan): **#f5a623**
- Red accent (logo'dan, az kullan): **#ff5050**
- Hafif kahve lekesi: **#a87142** (transparan)

Glow yok, neon yok, 3D render yok, glossy yok.

---

## Prompt template

```
A flat-lay top-down photo of an open Moleskine-style notebook with cream
textured paper (color #f4ebd6). Hand-pencilled title in graphite at the top
reads "{title}". Below the title, {content_description}. On the desk around
the notebook: a small ceramic mug with a faint coffee ring stain, a paper
clip, a sharpened wooden pencil. Soft afternoon light from the upper-left
window. Shot on a 50mm lens, slight depth of field on the corners. Color
grade: warm, slightly desaturated, magazine editorial photography. The
bottom-right quadrant of the image is intentionally empty (clear table
surface) — leave at least 18% of the bottom-right corner free of objects.
Color palette: cream paper, graphite pencil, single amber (#f5a623) accent.
NOT a 3D render. NOT digital art. NOT vector. NOT AI-style glossy.
Photo-realistic, analog feel.
```

İçerik tipine göre `{content_description}` örnekleri:

### Code/CDP tip içeriği
```
{content_description}: a small printed snippet pinned with a piece of washi
tape, showing 3-4 lines of monospace code. The code reads:
"npx cdpilot stealth on
npx cdpilot cookies add x.com
npx cdpilot go x.com"
A tiny amber arrow drawn in pencil points to one specific line. Around it,
margin annotations in small pencil handwriting.
```

### Concept/diagram içeriği
```
{content_description}: a hand-drawn architectural sketch of {concept},
boxes-and-arrows style in graphite, with ONE element circled in amber pencil.
Small numbered annotations in the margin.
```

### Repo/highlight içeriği
```
{content_description}: a printed page (looks like a GitHub README screenshot)
clipped to the notebook with a small black binder clip. The visible heading
reads "{repo_name}". A pencil tick mark next to one line.
```

---

## Watermark (post-process'te composite)

`xbot/ops/image_gen.py` her görselin alt sağ köşesine bunu basar:

```
[ logo (96x96 px) ]  @cdpilot_dev
                     cdpilot.ndr.ist
```

- Logo: `~/cdpilot-twitter-data/logo-256.png` (96x96'ya resize)
- Yazı: monospace beyaz, hafif drop shadow (kağıt yansıması gibi)
- Konum: sağ alt köşeden 32px iç, transparan beyaz panel arkası (#fafafa 0.7 opacity)
- Boyut: görselin %18-22 alt-sağ alanı

---

## Üretim akışı

```
draft JSON
  ↓
image_gen.py gen --id <post-id> --style notebook --content "<short desc>"
  ↓ fal.ai gpt-image-2 (signature notebook prompt + content slot)
  ↓ download PNG
  ↓ composite logo + @cdpilot_dev watermark
  ↓
~/cdpilot-twitter-data/images/<post-id>.png
  ↓
Telegram preview to user (✅ approve / 🔁 regenerate / ⏭ no-image)
  ↓ if approve
poster_twikit → twikit upload_media → create_tweet(media_ids=[id])
```

---

## Üretimde KAÇIN

| ❌ | ✅ |
|---|---|
| "cyberpunk", "neon", "glowing" | "warm afternoon light" |
| "3D render", "isometric" | "flat-lay photo" |
| "vector illustration" | "analog, on paper" |
| "vibrant colors" | "muted, warm" |
| "sleek modern" | "field notebook, lived-in" |
| Ekrana doğrudan bakan cihaz | Defter + el çizimi |

---

Son güncelleme: 2026-05-21
