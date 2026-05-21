---
title: cdpilot Twitter Daily Routine
schedule: daily, randomized 09:00-11:00 Istanbul
description: Plan today's tweets, apply humanizer/strategy skills, sync queue to server
---

> Bu playbook Claude Cowork tarafından sabah session açılışında okunur ve adım adım uygulanır.
> Her step spesifik komut ve format içerir — vague instruction yoktur.
> Adım sırası önemlidir: önce kriz kontrol, sonra içerik, sonra sync.

---

## Step 0 — Crisis Check (ÖNCE YAP, devam kararını burada ver)

### 0a. Idempotency guard

Bugün için queue zaten varsa ve son 2 saat içinde üretildiyse rutini tekrarlama:

```bash
mkdir -p ~/cdpilot-twitter-data/{queue,logs,alerts,analytics}
TODAY_QUEUE=~/cdpilot-twitter-data/queue/$(date +%Y-%m-%d).json
if [ -f "$TODAY_QUEUE" ]; then
  MTIME=$(stat -f %m "$TODAY_QUEUE" 2>/dev/null || stat -c %Y "$TODAY_QUEUE")
  AGE=$(( $(date +%s) - MTIME ))
  if [ "$AGE" -lt 7200 ]; then
    osascript -e 'display notification "Today already queued — skipping" with title "cdpilot Twitter"'
    echo "[SKIP] queue generated $AGE seconds ago"
    exit 0
  fi
fi
```

2 saatten yeniyse sessizce çık. Daha eskiyse logla ve devam et (overwrite olacak).
Kullanıcıdan onay alındıktan sonra zorla çalıştırmak için: `FORCE=1` env var ile guard'ı atla.

### 0b. Server hata logu

```bash
rsync -avz --timeout=15 srv21:/var/log/cdpilot-twitter/error.log \
  ~/cdpilot-twitter-data/logs/server-error.log 2>/dev/null || true
```

Dosya varsa, son 24 saatte FAILED satır sayısını hesapla (basit kriter — log format değişirse refine et):

```bash
LOG=~/cdpilot-twitter-data/logs/server-error.log
if [ -f "$LOG" ]; then
  FAILED_COUNT=$(grep -c 'FAILED' "$LOG" 2>/dev/null || echo 0)
  if [ "${FAILED_COUNT:-0}" -gt 5 ]; then
    osascript -e 'display notification "Server error rate high — routine paused" with title "cdpilot Twitter" subtitle "ALERT"'
    cp "$LOG" ~/cdpilot-twitter-data/alerts/$(date +%Y-%m-%d-%H)-server-errors.txt
    echo "[CRISIS] $FAILED_COUNT FAILED entries in server-error.log — awaiting user approval"
    # DUR: Kullanıcıya net soru sor:
    #   "Son log'ta N FAILED kayıt var. (1) Detayları göster (2) Queue-paused devam et (3) Tüm rutini iptal"
    exit 2
  fi
fi
```

### 0c. Queue tıkanması

`~/cdpilot-twitter-data/queue/` içinde son 3 güne ait dosyalara bak.
Her dosyada `status=failed` item sayısını topla. Toplam > 6 ise kriz sinyali, 0b ile aynı onay akışını uygula.

### 0d. Follower düşüşü

Son iki analitik dosyasını (Step 2'de yüklenir — bu kontrol ilk koşuşta atlanır, ikinci günden itibaren çalışır) karşılaştır, `follower_count` farkını hesapla.
Günlük düşüş > %10 ise: kriz-playbook davranışına geç, alert yaz.

**Kriz yoksa Step 1'e devam et.**

### 0e. Server queue pull (durum korunsun)

Generation öncesi server'daki güncel queue durumunu yerel'e çek. Bu adım, executor'ın işlediği `status=done|failed` post'ların yerel taraftan üzerine yazılmasını önler.

```bash
rsync -avz --timeout=30 srv21:/opt/cdpilot-twitter-bot/queue/ \
  ~/cdpilot-twitter-data/queue/ 2>/dev/null || true
```

Başarısız olursa devam et — Step 8'de yeniden sync edilecek. Sadece lokal state stale olur, executor zaten gerçeği biliyor.

---

## Step 1 — Skills + Schema Load

Şu dosyaları sırayla Read ile oku:

- `~/.claude/skills/cdpilot-twitter-bot/SKILL.md` (yoksa sessizce atla)
- `~/.claude/skills/viral-mechanics/SKILL.md` (yoksa sessizce atla)
- `~/.claude/skills/cold-start-amplification/SKILL.md` (yoksa sessizce atla)
- `~/.claude/skills/engagement-reciprocity/SKILL.md` (yoksa sessizce atla)
- `~/01dev/cdpilot/scripts/twitter-bot/queue-schema.md` — **ZORUNLU**, Step 7'de JSON yazılmadan önce şema bağlama yüklenmeli. Dosya yoksa: alert üret ve **dur** (queue JSON üretmek schema olmadan riskli).

Her skill okunduğunda içeriğindeki kuralları session bağlamına yükle.
Skill dosyası yoksa: `[SKIP] skill not found` logla, devam et.
queue-schema.md yoksa: `[ABORT] schema missing` logla, kullanıcıya bildir.

---

## Step 1.5 — Discovery Scan (fenomen "keşfettim" tweet'leri için)

Her sabah niche-relevant content kaynaklarını tarayıp `~/cdpilot-twitter-data/discoveries/$(date +%Y-%m-%d).md` dosyasına yaz. Step 5g bu listeden seçer.

```bash
mkdir -p ~/cdpilot-twitter-data/discoveries
DISCOVERY_FILE=~/cdpilot-twitter-data/discoveries/$(date +%Y-%m-%d).md
```

Kaynaklar (her birinden 3-5 item, niche filter uygulayarak):

| Kaynak | URL pattern | Filter |
|--------|-------------|--------|
| GitHub Trending | `https://github.com/trending/{lang}?since=daily` | python, javascript, go — readme'de browser/automation/scraping/CDP/LLM keyword'leri |
| HN Front Page | `https://news.ycombinator.com/` | başlık veya yorumlarda niche keyword'leri |
| arXiv yeni | `https://arxiv.org/list/cs.CL/recent` | LLM-agent, web-agent, browser-control |
| Product Hunt | `https://www.producthunt.com/` | dev tools, automation kategorisi |
| X search (kendi handle'ımızı mention edenler hariç) | `https://x.com/search?q=cdp+browser+automation&f=live` | son 24h, 10+ like |

cdpilot'ta WebFetch yoksa veya scrape edilemiyorsa: `[SKIP] discovery source unreachable` logla, devam et. Tek source bile bulursa Step 5g işler.

Dosya formatı:
```markdown
## YYYY-MM-DD Discovery Scan

### GitHub
- [repo-name](url) — 1 cümle neden ilginç

### HN
- [title](url) — 1 cümle takeaway

### arXiv
- [paper title](url) — abstract'tan 1 cümle

### X
- @handle tweet: <quote_url> — neden RT/quote edilebilir
```

Step 5g bu dosyadan 1-2 item seçer ve içeriğini queue'ya ekler.

---

## Step 2 — Yesterday's Analytics

Dünün tarihini hesapla:

```bash
YESTERDAY=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)
```

Analitik dosyasını çek:

```bash
rsync -avz --timeout=20 srv21:/opt/cdpilot-twitter-bot/analytics/${YESTERDAY}.json \
  ~/cdpilot-twitter-data/analytics/ 2>/dev/null || true
```

Dosya varsa `~/cdpilot-twitter-data/analytics/${YESTERDAY}.json` oku.
Şu alanları çıkar: `posts[].impressions`, `posts[].likes`, `posts[].hour`, `follower_count`.

Hesaplamalar:
- **best_tweet**: impression + like toplamı en yüksek, `content` ilk 60 char
- **worst_tweet**: impression + like toplamı en düşük
- **best_hour**: engagement toplamı en yüksek saat (örn. `17`)

`~/cdpilot-twitter-data/learnings.md` dosyasına append et:

```markdown
## [BUGÜN_TARİHİ] Analytics Review
- Best tweet: "[içerik 60 char]…" — score: [N]
- Worst tweet: "[içerik 60 char]…" — score: [N]
- Best posting hour: [HH]:00
- Observation: [tek cümle çıkarım]
- Applied to today: [bugün nasıl kullanılacak]
```

Dosya yoksa (sunucu henüz çalışmamış): `[SKIP] no analytics for ${YESTERDAY}` yaz, devam et.

---

## Step 3 — Day N + Rolling Window Calculation

`~/cdpilot-twitter-data/launch-date.txt` oku (tek satır ISO date, örn: `2026-05-01`).

Dosya yoksa: bugünün tarihini yaz ve Day 1 ile başla:
```bash
date +%Y-%m-%d > ~/cdpilot-twitter-data/launch-date.txt
```

**Rolling 3-day pencere**: bu rutin her sabah `{today, today+1, today+2}` üçlüsü için plan üretir. Amaç: Cowork session 2 güne kadar açılmazsa bile server'daki kuyruk dolu kalsın.

Her gün için Day N ve NNN'i hesapla:

```bash
python3 <<'PY' > /tmp/cdpilot-window.json
import json, os
from datetime import date, timedelta
launch = date.fromisoformat(
    open(os.path.expanduser('~/cdpilot-twitter-data/launch-date.txt')).read().strip()
)
today = date.today()
out = []
for offset in (0, 1, 2):
    d = today + timedelta(days=offset)
    day_n = (d - launch).days + 1
    out.append({
        "date": d.isoformat(),
        "day_n": day_n,
        "nnn": f"{day_n:03d}",
        "weekday": d.weekday(),
        "offset": offset,
    })
print(json.dumps(out, indent=2))
PY
```

`/tmp/cdpilot-window.json` üç element içerir — her birini `WIN[0]`, `WIN[1]`, `WIN[2]` olarak referansla.

Her offset için içerik dosyasını oku (NNN zero-padded):
```
Read ~/01dev/cdpilot/.claude/docs/twitter-master-plan/days/day-${NNN}.md
```

Day+0 dosyası yoksa Step 1'de yüklediğin track ve learnings'ten üret. Day+1 ve day+2 dosyaları yoksa: master plan README'sinden weekday → track çıkar, içeriği daha **evergreen** tut (yarının analytics'ine reaktif olamayız).

Dosya yoksa: Read `~/01dev/cdpilot/.claude/docs/twitter-master-plan/README.md`
Bugünün weekday'ine göre track belirle:

| Weekday | Track |
|---------|-------|
| Pazartesi (0) | T1 Foundations |
| Salı (1) | T2 Anti-Bot Mechanics |
| Çarşamba (2) | T3 Use Cases |
| Perşembe (3) | T4 LLM×Automation |
| Cuma (4) | T5 Maker Stories |
| Cumartesi (5) | T6 Community |
| Pazar (6) | 60% skip: `python3 -c "import random,sys; sys.exit(0 if random.random() > 0.6 else 1)"` — exit 0 ise devam, exit 1 ise `daily-log.md`'ye `## YYYY-MM-DD — SKIPPED (Sunday roll)` ekle ve **rutinden tamamen çık** (Step 4-9 atlanır), `osascript` ile bilgi notify et |

---

## Step 4 — Tweet Generation (× 3 day)

**Üç gün için ayrı ayrı üret** (WIN[0], WIN[1], WIN[2]). Day+0 dünün analytics'ine reaktiftir (best_hour observation). Day+1 ve Day+2 **evergreen** tutulur — bilinmeyen yarınki veriye yaslanmaz.

Her gün için: day-NNN.md içeriğini, learnings'i ve viral-mechanics skill kurallarını birleştirerek üret.

### Slot planı (her gün için aynı şablon, Gauss jitter ±20dk uygulanır)

| Slot | Hedef saat (İST) | Tür | İçerik kaynağı |
|------|-----------------|-----|----------------|
| mid-day | 14:00 | `post` | Bilgi odaklı, day-NNN Tweet 2–3 |
| hook | 17:00 | `post` veya `thread` başlangıcı | day-NNN Tweet 1 (Hook) |
| evening | 21:00 | `thread` (min 3 tweet) veya `post` | Teknik derinlik |

**Engagement replies sadece day+0'a eklenir** (gerçek-zamanlı hedef seçimi gerektirir). Day+1 ve Day+2'de engagement slot'ları boş bırakılır; bir sonraki Cowork run o günü day+0 olarak ele aldığında doldurur.

### @grok mention kuralı

State dosyasını oku: `~/cdpilot-twitter-data/state.json` → `last_grok_mention` (ISO date).
Dosya yoksa oluştur: `{"last_grok_mention": null}`.

```bash
LAST=$(python3 -c "import json,os; p=os.path.expanduser('~/cdpilot-twitter-data/state.json'); print(json.load(open(p)).get('last_grok_mention') or '')" 2>/dev/null)
```

`LAST` boşsa veya 7+ gün geçtiyse VE bugün Perşembe ise: hook veya evening slot'una `@grok` mention ekle, `state.json`'ı güncelle.
7 günden azsa: bu haftaki Perşembe'ye ertele (Perşembe değilse zaten skip).

### Humanizer kuralları (hepsini uygula)

1. **Noktalama**: her 3 cümleden birinin sonunda nokta yok
2. **Typo**: 1-2 yaygın hata — sadece bilinçsiz görünmeli (örn: `tthe`, `automattion`, `directy`)
3. **Büyük harf**: tweet başında büyük harf, ortada rastgele 1 kelime küçük
4. **Emoji**: maks 1, evening slot tercihli, mid-day'de hiç
5. **Thread timing notu**: JSON'a yaz, sunucu 8–45s delay uygular (not: `"thread_delay_hint": true`)

---

## Step 5 — Engagement Plan (fenomen davranış paterni)

Bu adım sadece reply değil — **influencer behavior portfolio**'su: like, retweet, quote, follow, reply, comment, bookmark. Tümü daily cap'ler içinde queue'ya `scheduled_time` ile dağıtılarak eklenir.

### 5a. Targets dosyası

`~/cdpilot-twitter-data/engagement-targets.md` oku. Dosya yoksa, şu şablonla oluştur:

```markdown
# Engagement Targets

Niche: CDP / DevTools / browser automation / headless / LLM×automation

## Tier 1 — high signal accounts (günlük etkileşim)
<!-- 5-10 hesap. Bunlara her gün en az 1 reply + 1-2 like -->
- @handle — why — last engaged: YYYY-MM-DD

## Tier 2 — medium signal (haftalık etkileşim)
<!-- 20-30 hesap. Rotation ile her gün 2-3'ü ile etkileşim -->
- @handle — why

## Tier 3 — discovery pool (keşif/yeni)
<!-- Trending'den, mention'lardan toplanır. 1 hafta sonra Tier 2'ye terfi veya düşer. -->
```

Hedef her gün toplamda 8-12 farklı handle ile etkileşim.

### 5b. Replies (mention'lara + Tier 1'e)

Mevcut Step 1'de yüklenen mentions/replies'lerden (`cdpilot agent twitter mentions --since ...`):
- Bizim tweet'lerimize gelen 5+ reply varsa → en kaliteli 3'üne `type=reply` ile yanıt taslakla
- Tier 1'den 3-5 hesap seç, son 24h tweet'lerinden engagement-reciprocity skill kuralına uygun olanı seç, reply taslakla

Queue: `type=reply`, `reply_to=tweet_id` (URL değil), `source="engagement-target"` veya `source="reciprocity"`.

### 5c. Likes (Tier 1+2 son tweet'leri)

10-20 like dağıt (cap 30):
- Tier 1: her hesabın son 24h içinde en yüksek engagement'lı 1-2 tweet'i
- Tier 2: rotation'la günlük 3-5 hesabın son tweet'i
- Aynı handle'a 24h içinde max 3 like (cap)
- Queue: `type=like`, `target_tweet_id=...`, `source="reciprocity"`, scheduled_time gün içinde dağıtılmış

### 5d. Retweets (yüksek seçicilikle)

Günde max 8 (cap), gerçekte 2-4 yeterli. Sadece:
- Niche'imizin tam ortasında olan içerik (CDP, automation, AI×automation)
- Tier 1'den gelen yüksek değerli teknik içerik
- Asla generic motivational/political içerik

Queue: `type=retweet`, `target_tweet_id=...`, `source="discovery"` veya `"engagement-target"`.

### 5e. Quote tweets (network amplification)

Günde max 3 (cap 5). Quote tweet, RT'den daha güçlü algoritmik sinyal — kendi yorumunla başkasının içeriğini paylaşırsın. Hedef:
- Tier 1'den ilginç bir tweet → "thoughts: ..." formatında 1-2 cümle ekle
- Discovery pool'dan bir GitHub repo / paper / tool → "found this — ..." formatında

Queue: `type=post`, `quote_url="https://x.com/handle/status/ID"`, content = bizim yorumumuz.

### 5f. Follow (ramp-up dikkatli)

Günde max 15 (cap), gerçekte yeni hesap için 5-8 daha güvenli. Hedefler:
- Tier 3 discovery pool'dan, son 7 gün niche'imizde içerik üretmiş 3-5 hesap
- Bizim tweet'lerimize quality reply atan hesaplar (reciprocity)
- Spam classifier "follow-unfollow" pattern'ini tanır — unfollow'u **asla** otomatik yapma; 7+ gün boyunca etkileşim üretmeyen hesapları manuel review

Queue: `type=follow`, `target_handle="handle"` (`@` olmadan), `source="discovery"` veya `"reciprocity"`.

### 5g. Discovery & sharing (fenomen behavior'ın kalbi)

Fenomenler "ben şunu keşfettim" tweet'leri atar. Bu en organik growth driver'larından biri. Kaynaklar (Step 2.5 ile günlük scan — aşağıda):
- GitHub trending (language: python, javascript, go)
- HN front page (24h)
- arXiv yeni paper'lar (cs.CL, cs.LG)
- Product Hunt (varsa niche'imizde)

Günde 1-2 keşif paylaşımı (cap yok, kalite konstrant):
- `type=post`, content = "found this: <bir cümle> + link veya screenshot"
- Veya `type=post` + `quote_url` = paylaşımcının orijinal tweet'i varsa quote
- Tags: `["discovery"]`, source: `"discovery"`

### 5h. Bookmark (private radar)

Günde max 50 ama gerçek hedef 5-10. Bookmark public görünmez ama:
- Discovery için "ileride paylaşırım" listesi tutar
- Mention'lardan dikkat çekenleri saklar
- Search history'den daha kalıcı

Queue: `type=bookmark`, `target_tweet_id=...`, `source="discovery"`.

### 5i. Daily cap enforcement

Tüm aksiyonları queue'ya ekledikten sonra cap kontrolü:

```bash
python3 <<'PY'
import json, os, glob
from collections import Counter
today = $(date +%Y-%m-%d)
caps = {"like": 30, "retweet": 8, "bookmark": 50, "follow": 15, "unfollow": 10, "reply": 20, "quote": 5}
queue = json.load(open(os.path.expanduser(f'~/cdpilot-twitter-data/queue/{today}.json')))
counts = Counter()
for p in queue["posts"]:
    t = p["type"]
    # quote = post + quote_url
    if t == "post" and p.get("quote_url"): counts["quote"] += 1
    elif t == "reply": counts["reply"] += 1
    elif t in caps: counts[t] += 1
for action, cnt in counts.items():
    if action in caps and cnt > caps[action]:
        print(f"[CAP] {action}: {cnt} > {caps[action]} — fazlalık skip edilecek")
PY
```

Cap aşan item'lar `status="skipped"` ve `reason="daily cap exceeded"` ile işaretlenir.

### 5j. Frekans dağılımı (önemli — burst pattern'i kırma)

Tüm engagement aksiyonlarını gün içine dağıt. Toplu olarak 1 saat içinde 30 like + 10 follow atmak bot tetikler. Hedef:
- Aksiyonlar arası ortalama 8-15 dakika
- Aktif saatler İST 10:00-23:00 (gece yarısı aksiyon → bot şüphesi)
- Her 30 dakikalık pencerede max 5 aksiyon
- `scheduled_time` için Gauss jitter, executor zaten humanizer_seed ile delay ekliyor

---

## Step 6 — Rolling Merge Logic (eager refresh, 6h freeze)

Bu adım, **0e**'de server'dan çekilen mevcut queue dosyalarıyla Step 4'te üretilen yeni planı birleştirir.

### Carry-over (dün → bugün)

Dünün queue dosyasını oku: `~/cdpilot-twitter-data/queue/${YESTERDAY}.json`

`status=pending` item varsa (zamanı geldi ama bir nedenle post edilmediyse):
- Bugünün queue'suna ekle
- `scheduled_time` = şu an + 30dk (ISO8601+03:00)
- `carry_over = true`
- Logla: `Carried over N items from ${YESTERDAY}`

### Üç gün için merge

Her gün için (day+0, day+1, day+2):

```
existing = read queue/YYYY-MM-DD.json (server'dan 0e ile geldi)
fresh    = Step 4'te üretilen yeni plan

for each existing item:
  if status in {done, failed, skipped, in_flight}:
    → KEEP, dokunma
  if status == pending AND scheduled_time < now + 6h:
    → KEEP (freeze window, executor bunu yakında çalıştırabilir)
  if status == pending AND scheduled_time >= now + 6h:
    → DROP (yenisiyle değiştirilecek)

merged = (kept items) + (fresh items, freeze window dışında kalan)
```

Çakışma kuralı: aynı `scheduled_time` slot'una hem kept hem fresh düşerse kept kazanır (executor görme ihtimali var). Fresh item'ın saatini ±15dk kaydır.

UUID politikası: kept item'lar mevcut UUID'lerini korur. Fresh item'lar yeni UUID alır.

### Server posting gap → comeback tweet

Eski mantık "Cowork session 2 gün açılmadı mı?" idi. Yeni mantık: "**Server gerçekten 2 gün post atmadı mı?**" Çünkü Cowork kapalıyken bile kuyruk akıyorsa hesap "ara verdim" görünmemiş; sahte comeback yalan üstüne yalan olur.

```bash
LAST_POST_TS=$(python3 -c "
import json, os, glob
files = sorted(glob.glob(os.path.expanduser('~/cdpilot-twitter-data/queue/*.json')))
ts = ''
for f in files[-5:]:
    try:
        for p in json.load(open(f)).get('posts', []):
            if p.get('status') == 'done' and p.get('scheduled_time', '') > ts:
                ts = p['scheduled_time']
    except Exception: pass
print(ts)
")
```

`LAST_POST_TS` ile şu anki zaman arasındaki fark > 48h ise comeback eklenir (aşağıdaki havuzdan random). Tek mesaj yerine pool kullan + ardışık tekrarı önle (`state.json.last_comeback_index`):

```
- "been heads-down testing some edge cases. back now"
- "long debug session, finally surfacing"
- "fell into a rabbit hole around <topic>. back to the thread"
- "ok the bug was annoying. back online"
- "a few quiet days = shipping. back at it"
```

`<topic>` bugünün track'inden veya day-NNN başlığından gelir; yoksa cümleyi placeholder'sız kısalt.

`scheduled_time` ISO8601+03:00:
```bash
date -v+30M +"%Y-%m-%dT%H:%M:%S+03:00" 2>/dev/null || \
  date -d '+30 minutes' +"%Y-%m-%dT%H:%M:%S+03:00"
```

```json
{
  "type": "post",
  "content": "<seçilen mesaj>",
  "scheduled_time": "<ISO8601+03:00>",
  "tags": ["comeback"],
  "humanizer_seed": <random>
}
```

---

## Step 7 — Queue JSON Write (× 3 day)

**Üç dosya yaz**, her biri kendi tarihine ait:

```
~/cdpilot-twitter-data/queue/${WIN[0].date}.json   # bugün
~/cdpilot-twitter-data/queue/${WIN[1].date}.json   # yarın
~/cdpilot-twitter-data/queue/${WIN[2].date}.json   # öbür gün
```

Server-side `queue_executor.py` her gün kendi tarihine ait dosyayı okuduğu için (`{today}.json`) bu naming uyumlu — executor'da değişiklik gerekmez.

Top-level format (her dosya için, queue-schema.md §2):

```json
{
  "date": "YYYY-MM-DD",
  "day_n": N,
  "track": "T1 Foundations",
  "generated_at": "<ISO8601+03:00>",
  "generated_by": "cowork",
  "posts": [ ... ]
}
```

Her post: `id=uuid4()`, `type`, `scheduled_time` (ISO8601+03:00), `status=pending`, `content` veya `thread[]`, `reply_to`, `result_url=null`, `error=null`, `humanizer_seed=randint(1,99999)`.

Schema validasyonu: queue-schema.md §3 ve §4'e her dosya için ayrı ayrı uygula.

Bugünün kopyasını da yaz (uyumluluk için):

```bash
cp ~/cdpilot-twitter-data/queue/$(date +%Y-%m-%d).json \
   ~/cdpilot-twitter-data/queue/today.json
```

---

## Step 8 — Sync to Server + Heartbeat

Sırayla çalıştır, her biri için başarı/başarısızlık logla:

```bash
# 1. Queue sync (3 dosya + today.json hepsi gider)
rsync -avz --timeout=30 ~/cdpilot-twitter-data/queue/ \
  srv21:/opt/cdpilot-twitter-bot/queue/

# 2. Master plan sync
rsync -avz --timeout=30 \
  ~/01dev/cdpilot/.claude/docs/twitter-master-plan/ \
  srv21:/opt/cdpilot-twitter-bot/master-plan/

# 3. Heartbeat — son Cowork run zamanını işaretle
date -u +"%Y-%m-%dT%H:%M:%SZ" > ~/cdpilot-twitter-data/heartbeat.txt
rsync -avz --timeout=15 ~/cdpilot-twitter-data/heartbeat.txt \
  srv21:/opt/cdpilot-twitter-bot/heartbeat.txt
```

Server'da heartbeat dosyası, 3-gün penceresinin ne zaman tazelendiğini gösterir. İleride server-side cron şunu kullanabilir: heartbeat > 72h ise hafif moda geç (sadece evening slot), > 120h ise tamamen duraklat.

rsync başarısız olursa (exit != 0):

```bash
osascript -e 'display notification "Queue sync FAILED — server unreachable" with title "cdpilot Twitter" subtitle "Check VPN / ssh srv21"'
```

`~/cdpilot-twitter-data/alerts/$(date +%Y-%m-%d-%H)-sync-fail.txt` oluştur.
`daily-log.md`'ye `Sync: FAILED` yaz.
Rutini devam ettir (queue lokal olarak hazır, elle sync edilebilir).

---

## Step 9 — Daily Summary + Notify

`~/cdpilot-twitter-data/daily-log.md` dosyasına append et:

```markdown
## YYYY-MM-DD — Day N — [TRACK ADI]
- Posts planned: N (M thread, K post, J reply)
- Carry-overs: N
- Best yesterday: "[snippet 60 char]…"
- Skills applied: cdpilot-twitter-bot, viral-mechanics
- queue_sync: OK / FAILED
- plan_sync: OK / FAILED
- Notes: [varsa özel durum]
```

İki sync ayrı satır — queue OK + plan FAIL gibi parçalı durumlar görünür kalsın.

macOS notification:

```bash
osascript -e 'display notification "Day N: X posts queued" with title "cdpilot Twitter" subtitle "Sync: OK"'
```

---

## Configuration Reference

| Dosya | İçerik | Yoksa |
|-------|--------|-------|
| `~/cdpilot-twitter-data/launch-date.txt` | ISO date (2026-05-01) | Bugünü yaz, Day 1 başla |
| `~/cdpilot-twitter-data/tone-prefs.md` | Güncel ton notları | Oluştur (boş şablon) |
| `~/cdpilot-twitter-data/engagement-targets.md` | Reply hedefleri | Step 5 şablonu oluşturur |
| `~/cdpilot-twitter-data/learnings.md` | Kümülatif analytics | Oluştur (boş) |
| `~/cdpilot-twitter-data/daily-log.md` | Günlük özet log | Oluştur (boş) |
| `~/.ssh/config` | `srv21` → `10.0.0.21` alias | `ssh -p 22 nadir@10.0.0.21` ile direkt bağlan |
| `~/.claude/skills/*/SKILL.md` | Strategy skill'leri | Sessizce atla |
| `/opt/cdpilot-twitter-bot/queue/` | Server queue dir | `ssh srv21 "mkdir -p /opt/cdpilot-twitter-bot/queue"` |
| `~/01dev/cdpilot/.claude/docs/twitter-master-plan/days/` | Day-NNN içerikleri | README'den track çıkar |

---

## Queue Schema Reference

Detaylı schema: `~/01dev/cdpilot/scripts/twitter-bot/queue-schema.md`

Executor: `~/01dev/cdpilot/scripts/twitter-bot/queue_executor.py`

Server'da çalışma şekli: systemd timer her 5dk `queue_executor.py` çalıştırır.
Executor `scheduled_time <= now` olan `pending` item'ları işler, JSON'u günceller.
