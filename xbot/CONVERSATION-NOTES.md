# xbot — Konuşma Notları & Karar Geçmişi

> Bu dosya, @cdpilot_dev Twitter otomasyon sisteminin kuruluş oturumunun tam kaydıdır.
> Tarih: 2026-05-19 (kuruluş günü). Hesap: **@cdpilot_dev** (Premium / mavi tik).

---

## 0. Amaç

cdpilot (sıfır-bağımlılık, CDP-over-HTTP browser automation aracı) için bir Twitter/X
büyüme ve içerik otomasyon sistemi. @cdpilot_dev hesabını bir "indie maker" gibi
yürütmek: içerik üretimi, zamanlama, engagement (follow/reply/quote/like), keşif paylaşımı.

---

## 1. Mimari evrim (bu oturumda yaşanan)

### v1 — Cowork playbook + 3-day rolling queue
- `playbook.md` (eski adı cdpilot-twitter-cowork.md): her sabah Cowork'ün okuyup uyguladığı adım adım rutin.
- **3-day rolling pencere**: her sabah today + 2 ileri gün için queue üretilir. Amaç: 2 güne kadar
  Cowork açılmazsa bile server'daki kuyruk dolu kalsın, kesinti olmasın.
- **Freeze window 6h, eager refresh**: yeniden üretimde önümüzdeki 6 saatteki post'lar dokunulmaz;
  day+1/+2 her sabah taze üretilir.
- Queue şeması: `queue-schema.md` (v1.0 → genişletildi).

### v2 — Schema + executor genişletme (fenomen davranışı)
Kullanıcı "tweet atmak dışında X'in tüm özelliklerini + fenomen davranışlarını" istedi.
Eklenenler:
- **İçerik type'ları**: post, thread, reply, pin, unpin + modifier'lar (long_form, quote_url, poll, media)
- **Engagement type'ları**: like, unlike, retweet, unretweet, bookmark, follow, unfollow
- **Daily rate limit'ler** (anti-spam): like 30, retweet 8, follow 15, reply 20, quote 5, vb.
- Playbook Step 5 baştan yazıldı: replies + likes + retweets + quotes + follows + discovery + bookmarks
- Playbook Step 1.5: Discovery scan (GitHub trending, HN, arXiv, Product Hunt, X search)
- `queue_executor.py`: tüm yeni type'ları dispatch eder, CDP pre-flight health check'li.
- `cdpilot.py` (ana repo): `agent twitter` namespace'ine yeni komutlar eklendi
  (quote/poll/media/long flag'leri, native thread fix, pin/unpin, unlike/retweet/unretweet/bookmark/unfollow, analytics scrape).

### v3 — Server-side deployment ("B mimarisi")
Karar: post atma server'da (srv21) olsun ki Mac kapalıyken bile çalışsın.
- Mac'teki cdpilot Chrome profile'ı srv21'e transfer edildi.
- Cookies, Mac Vivaldi'den export → srv21'e inject (Network.setCookies).
- srv21'de **Xvfb + headless-equivalent Chrome** (systemd service).
- systemd unit'ler: chrome.service, cookies.service, executor.timer (5dk), keep-alive.timer (30dk), snapshot.timer (2h).
- 4 katmanlı oturum yenileme: keep-alive + snapshot + failure-alert + Mac launchd watcher.

### Karşılaşılan teknik sorunlar
1. **Python sürümü**: cdpilot.py PEP604 (`X | None`) kullanıyor → Python 3.13 gerekti (Mac'te `/opt/homebrew/bin/python3.13`).
2. **websockets paketi** eksikti (3.13'e kuruldu).
3. **Chrome instabilitesi**: srv21'de Chrome periyodik çöktü (on_device_model + video_capture internal crash). Disable flag'ler + Restart=always eklendi.
4. **Çoklu Chrome instance çakışması**: test'lerden kalan instance'lar 9222'yi tutuyordu, cdpilot yanlış instance'a bağlanıyordu → clean restart gerekti.
5. **Cookies persist etmiyor** Chrome restart sonrası → her başlangıçta otomatik re-inject (cookies.service).
6. **Sürüm uyumsuzluğu**: srv21'deki cdpilot.py eskiydi (8548 satır), Mac'teki yeni (9090). Senkronize edildi.
7. **twikit denemesi**: Chrome'suz HTTP-only alternatif denendi; X'in son "client transaction id" değişikliği ile uyumsuz ("Couldn't get KEY_BYTE indices") → çalışmadı.

### v4 — Doğrudan CDP (çalışan yöntem)
- cdpilot CLI wrapper'ının `_tw_click_sel` selector-bounding-box yaklaşımı güvenilmez çıktı.
- **Çözüm**: doğrudan CDP WebSocket'ine bağlanıp 3 adım JS gönder:
  `execCommand('insertText')` → button enable check → click.
- İLK TWEET bu yöntemle atıldı (sonra silindi, aşağıya bakınız).

---

## 2. STRATEJİK DÖNÜŞ (en önemli karar)

İlk tweet atıldıktan sonra kullanıcı sordu: "yeni açılan bu hesap için doğru yol bu mudur?"

**Net cevap: HAYIR.** Bugünkü altyapı 100+ takipçili yerleşik hesap için tasarlanmış.
Yeni hesap (0 takipçi) için tam otomasyon yanlış:
- Cold-start: 0 takipçiyle tweet kimseye ulaşmaz.
- Otomasyon + humanizer + 0 takipçi = bot sinyali çakışması → suspend riski (özellikle ilk 30 gün).
- Engagement boyutu (reply/quote ağı) eksikti.

**Yeni strateji — fazlı yaklaşım:**
- **Faz 0** (1-2 saat, manuel): profil fundamentals — bio, pinned, profil foto, banner, Tier 1 listesi.
- **Faz 1** (4-6 hafta, çoğu manuel): günde 1 tweet + 5-10 elden reply + 1-2 quote/hafta. Hedef 100-300 organik takipçi. Otomasyon YOK.
- **Faz 2** (2-3. ay): yarı-otonom. Draft AI, post sen.
- **Faz 3** (4+ ay): bugün kurduğumuz full otomasyon devreye girer.

---

## 3. Faz 0 — bu oturumda YAPILANLAR

- ✅ İlk "webdriver" tweet'i **silindi** (bağlamsız, sıra dışı atılmıştı).
- ✅ **Pinned tweet** atıldı + profile sabitlendi:
  "browser automation without the driver tax / no selenium, no playwright, no puppeteer — just raw CDP over a websocket. zero deps, one npx command / building cdpilot in public ↓"
- ✅ **Bio** güncellendi:
  "I build cdpilot — browser automation without the driver tax. pure CDP over a WebSocket, zero deps. protocol-level notes for devs & AI agents"
- ✅ **Otomasyon durduruldu**: srv21'deki tüm timer/service'ler (executor, keep-alive, snapshot, chrome) stop + disable. Queue dosyalarındaki 11 pending item "skipped" işaretlendi.
- ✅ **Tier 1 aday listesi** hazırlandı (`engagement-targets.md`) — follow anında her biri doğrulanacak.

---

## 4. AÇIK İŞLER / SONRAKİ ADIMLAR

### Faz 1 başlangıcı (yarından itibaren, kademeli warm-up)
- Gün 2-3: günde 3-5 follow + 2-3 düşünülmüş reply (30 follow ASLA — yeni hesap red flag).
- Gün 4-7: günde 1 tweet + 3-5 reply + birkaç follow.
- Reply'ler: ben taslak hazırlarım, kullanıcı kendi sesiyle onaylar/düzeltir (gerçek insan sinyali kritik).

### Telegram köprüsü (mobil onay sistemi — planlandı, kurulmadı)
Kullanıcı: "PC başında olmasam da telefondan onaylayıp devam ettirmek istiyorum."
- Cowork'ün native mobil push + uzaktan onayı YOK.
- Çözüm: Telegram bot köprüsü. Akış:
  sabah hazırlık → Telegram'dan plan + onay sorusu → kullanıcı telefondan /onayla → poller uygular.
- Gerekli: kullanıcı @BotFather'dan bot token oluşturacak (credential işi — Claude yapamaz).
- Güvenlik notu: Telegram onayı "harici kanal"; follow gibi düşük-riskli eylemler için yeterli,
  bot sadece kullanıcının chat ID'sine kilitlenir. Hassas eylemler ayrıca dikkatle ele alınır.

### Tier 1 listesini gerçek doğrulama
- Keyword X-search kalitesiz çıktı (spam scraping hesapları).
- Doğru yöntem: bilinen kaliteli figürlerin (addyosmani, paul_irish, browser-use, vb.) following ağından genişletmek.

---

## 5. ÖNEMLİ TEKNİK NOTLAR

- **Mac Python**: `/opt/homebrew/bin/python3.13` (3.9 değil — PEP604 gerek).
- **Mac Vivaldi CDP portu**: 9227 (cdpilot izole profil, login @cdpilot_dev).
- **Çalışan post yöntemi**: doğrudan CDP WS + JS injection (`ops/_post_and_pin.py`, `ops/_phase0_lib.py`). cdpilot CLI `agent twitter post` wrapper'ı güvenilmez.
- **srv21**: ssh alias, 10.0.0.21:2222. Otomasyon şu an DURDURULMUŞ durumda.
- **Veri klasörü**: `~/cdpilot-twitter-data/` (queue, logs, alerts, analytics, discoveries, state, backups). Bu klasör runtime data — repo'da değil.
- **Cookies session**: ~14-30 gün geçerli. Expire olunca `mac-scripts/refresh-cookies-mac.sh`.

---

## 6. GÜVENLİK / İLKE NOTU

- Her public posting eylemi (tweet, reply, follow, quote, profil değişikliği) kullanıcı onayı gerektirir.
- Otomasyon = kullanıcının önceden açıkça onayladığı sistem (scheduled task / cron). Bu meşru.
- Yeni hesapta tam otonom posting hem güvenlik hem strateji açısından yanlış — Faz 0/1 manuel-first.
