# xbot — cdpilot Twitter/X Automation

@cdpilot_dev hesabı için içerik + engagement otomasyon sistemi.
Kuruluş oturumu ve tüm kararlar için → [`CONVERSATION-NOTES.md`](./CONVERSATION-NOTES.md)

## Mevcut durum (2026-05-19)

- Hesap: **@cdpilot_dev** (Premium). Faz 0 tamamlandı (bio + pinned tweet hazır).
- Otomasyon: **DURDURULMUŞ** (Faz 0/1 manuel-first stratejisi gereği).
- Sonraki: Faz 1 (kademeli warm-up) + Telegram mobil-onay köprüsü.

## Klasör yapısı

```
xbot/
├── README.md                  ← bu dosya
├── CONVERSATION-NOTES.md      ← kuruluş oturumu, kararlar, açık işler
├── playbook.md                ← Cowork sabah rutini (3-day rolling, engagement, discovery)
├── queue-schema.md            ← queue JSON veri sözleşmesi (v1.0+, tüm type'lar)
├── queue_executor.py          ← server-side executor (scheduled_time'a göre post atar)
├── bootstrap.sh               ← ~/cdpilot-twitter-data/ kurulumu (tek seferlik)
│
├── systemd/                   ← srv21 systemd unit'leri (şu an disable)
│   ├── cdpilot-chrome.service       (Xvfb + Chrome, port 9222)
│   ├── cdpilot-cookies.service      (login cookie inject)
│   ├── cdpilot-keep-alive.{service,timer}  (session warmth, 30dk)
│   ├── cdpilot-snapshot.{service,timer}    (cookie snapshot, 2h)
│   └── cdpilot-twitter-executor.{service,timer}  (queue executor, 5dk)
│
├── server-scripts/            ← srv21'de çalışan scriptler
│   ├── run-chrome.sh                (Chrome'u Xvfb içinde başlat)
│   ├── inject-cookies.sh            (cookies snapshot'tan yükle)
│   ├── keep-alive.sh                (x.com ping + session doğrula)
│   ├── snapshot-cookies.sh          (canlı Chrome'dan cookie kaydet)
│   └── deploy-executor.sh           (unit'leri srv21'e deploy)
│
├── mac-scripts/               ← Mac'te çalışan scriptler
│   ├── refresh-cookies-mac.sh       (oturum düşünce fresh cookie → srv21)
│   └── check-alerts-mac.sh          (srv21 alert'lerini poll + macOS bildirim)
│
├── ops/                       ← operasyon araçları (doğrudan CDP, ÇALIŞAN yöntem)
│   ├── _phase0_lib.py               (browser WS bağlan, tab aç, eval helper)
│   ├── _post_and_pin.py             (tweet at + pin)
│   ├── _update_bio.py               (bio güncelle)
│   ├── _delete_tweet.py             (tweet sil)
│   ├── _search_users.py             (X user search scrape)
│   ├── _gen_queue_day1.py           (queue üretici örnek)
│   └── _requeue_failed.py           (failed → pending)
│
└── archive/
    ├── legacy/                ← eski tasarım (server'da claude CLI ile planlama)
    └── scratch/              ← debug/deneme scriptleri
```

## Çalışan post yöntemi (önemli)

cdpilot CLI'ın `agent twitter post` wrapper'ı X DOM'unda güvenilmez çıktı.
**Çalışan yöntem**: doğrudan CDP WebSocket + JS injection — bkz `ops/_phase0_lib.py` + `ops/_post_and_pin.py`.

```bash
# Mac'te Vivaldi açık + @cdpilot_dev login (port 9227) gerekir
/opt/homebrew/bin/python3.13 ops/_post_and_pin.py
```

## Hızlı referans

| İhtiyaç | Komut / dosya |
|---------|---------------|
| Veri klasörü kurulumu | `bash bootstrap.sh` |
| Oturum düştü, yenile | `bash mac-scripts/refresh-cookies-mac.sh` |
| Sabah rutini (manuel) | Cowork'e "playbook'u çalıştır" |
| Otomasyonu tekrar aç | `systemd/` unit'lerini srv21'de enable (Faz 3'te) |

## Strateji özeti

Faz 0 (profil) ✅ → Faz 1 (manuel warm-up, 4-6 hafta) → Faz 2 (yarı-otonom) → Faz 3 (full otomasyon).
Detay: `CONVERSATION-NOTES.md` §2.
