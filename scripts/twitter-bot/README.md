# cdpilot Twitter Bot — Sunucu 21 Deployment

Sunucu 21 (10.0.0.21) üzerinde günde 5 slot, her biri ±30 dakika jitter ile
otomatik tweet gönderen systemd timer tabanlı setup.

## Mimari

```
Lokal makine                    Sunucu 21 (10.0.0.21)
─────────────────               ──────────────────────────────────────
deploy.sh           →rsync→    /home/nadir/cdpilot-twitter-bot/
                    →ssh+sudo→ /etc/systemd/system/cdpilot-twitter.*

                               systemd timer (5 slot/gün, ±30dk jitter)
                                    │
                                    ▼
                               cdpilot-twitter-run.sh
                                    │
                                    ├── /etc/cdpilot-twitter.env (credentials)
                                    ├── claude CLI (twitter-bot routine)
                                    └── /var/log/cdpilot-twitter/*.log
```

## Önkoşullar

- WireGuard VPN aktif (`wg show`)
- SSH key auth çalışıyor: `ssh nadir@10.0.0.21 "echo ok"`
- Sunucu'da `cdpilot` globally installed: `ssh nadir@10.0.0.21 "which cdpilot"`
- Sunucu'da `claude` CLI installed: `ssh nadir@10.0.0.21 "which claude"`
- Sunucu'da `nadir` user'ının `sudo` yetkisi var
- macOS: XQuartz (ilk login için): `brew install --cask xquartz`

## Kurulum (5 adım)

### Adım 1: Login bootstrap (tek seferlik)

X11 forwarding ile sunucu tarayıcısını lokalinizde açıp manuel Twitter login yapın:

```bash
cd scripts/twitter-bot
./login-bootstrap.sh
```

Script sizi yönlendirecek:
1. Tarayıcı X11 ile lokal ekranınızda açılır
2. `https://x.com/i/flow/login` adresine gidin, giriş yapın
3. Enter'a basın — cookie ve profil yedeklenir

### Adım 2: Secrets dosyası oluştur (sunucu'da, elle)

**Bu adım sunucu'da doğrudan yapılır — hiçbir zaman git'e commit etmeyin.**

```bash
ssh nadir@10.0.0.21

# Sunucu'da:
sudo nano /etc/cdpilot-twitter.env
```

Dosya içeriği (placeholder'ları gerçek değerlerle değiştirin):

```bash
# cdpilot Twitter Bot — Credentials
# chmod 600 — ASLA git'e ekleme
CLAUDE_API_KEY=sk-ant-BURAYA_GERCEK_KEY
GEMINI_API_KEY=AIzaSy_BURAYA_GERCEK_KEY
ALERT_WEBHOOK_URL=https://hooks.slack.com/... # opsiyonel, boş bırakılabilir
```

Dosya izinlerini ayarlayın:

```bash
sudo chmod 600 /etc/cdpilot-twitter.env
sudo chown root:root /etc/cdpilot-twitter.env
```

### Adım 3: deploy.sh çalıştır

```bash
# Önce dry-run ile ne yapacağını gör:
./deploy.sh --dry-run

# Gerçek deploy:
./deploy.sh
```

Otomatik olarak:
- Dosyaları rsync ile gönderir
- systemd service + timer'ı kurar
- Timer'ı enable + start eder
- Doğrulama çıktısı gösterir

### Adım 4: Timer doğrula

```bash
ssh nadir@10.0.0.21 'systemctl list-timers cdpilot-twitter* --no-pager'
```

Beklenen çıktı: `NEXT` sütununda yaklaşan zaman, `ACTIVATES` sütununda `cdpilot-twitter.service`.

### Adım 5: İlk log kontrolü

```bash
# Canlı log (systemd journal):
ssh nadir@10.0.0.21 'journalctl -u cdpilot-twitter.service -f'

# Dosya log'ları:
ssh nadir@10.0.0.21 'ls -lt /var/log/cdpilot-twitter/ | head -10'
ssh nadir@10.0.0.21 'tail -50 /var/log/cdpilot-twitter/$(ls -t /var/log/cdpilot-twitter/ | head -1)'
```

## Zamanlama

5 slot / gün (UTC+3 Türkiye saati):

| Slot | TR Saati | UTC    | Jitter     |
|------|----------|--------|------------|
| 1    | 13:00    | 10:00  | ±30 dakika |
| 2    | 15:30    | 12:30  | ±30 dakika |
| 3    | 17:30    | 14:30  | ±30 dakika |
| 4    | 21:00    | 18:00  | ±30 dakika |
| 5    | 22:30    | 19:30  | ±30 dakika |

`Persistent=true` ile sunucu downtime'ından kaynaklanan kaçan run'lar telafi edilir.

## Troubleshooting

### Timer fire etmedi

```bash
# Timer state kontrolü (active waiting = normal)
ssh nadir@10.0.0.21 'systemctl status cdpilot-twitter.timer'

# Son timer logları
ssh nadir@10.0.0.21 'journalctl -u cdpilot-twitter.timer --since today'

# Timer sıfırla
ssh nadir@10.0.0.21 'sudo systemctl restart cdpilot-twitter.timer'
```

### Login expired (yeniden bootstrap)

X platformu oturum düşürdüğünde:

```bash
./login-bootstrap.sh
# ve ardından:
./deploy.sh  # güncel cookie dosyasını gönderir
```

### claude CLI bulunamadı

```bash
ssh nadir@10.0.0.21 'which claude || echo NOT FOUND'
# Bulunamazsa PATH düzeltin veya full path kullanın:
# cdpilot-twitter-run.sh içinde CLAUDE_BIN değişkenini düzenleyin
```

### Log dosyaları büyüdü

Run script 30 günden eski logları otomatik siler. Manuel temizleme:

```bash
ssh nadir@10.0.0.21 'find /var/log/cdpilot-twitter -name "*.log" -mtime +7 -delete'
```

### systemd unit değişti, timer güncellenmiyor

```bash
./deploy.sh  # idempotent — yeniden çalıştırılabilir
```

### Tüm log geçmişi

```bash
ssh nadir@10.0.0.21 'ls /var/log/cdpilot-twitter/'
```

## Dosya Yapısı

**Lokal (bu repo):**
```
scripts/twitter-bot/
├── deploy.sh                  # Ana deploy scripti (./deploy.sh)
├── cdpilot-twitter.service    # systemd service unit
├── cdpilot-twitter.timer      # systemd timer unit (5 slot/gün)
├── cdpilot-twitter-run.sh     # Sunucu'da çalışan execute scripti
├── login-bootstrap.sh         # Tek seferlik login (X11 forwarding)
└── README.md                  # Bu dosya
```

**Sunucu (10.0.0.21):**
```
/home/nadir/cdpilot-twitter-bot/
├── master-plan/               # Twitter içerik planı (rsync ile gelir)
├── skill/
│   └── SKILL.md               # Bot skill tanımı (rsync ile gelir)
├── twitter-cookies.json       # Oturum cookie'leri (login-bootstrap ile)
└── cdpilot-twitter-run.sh     # Execute scripti (deploy ile gelir)

/etc/cdpilot-twitter.env       # Credentials (chmod 600, ASLA git'e gelme)
/etc/systemd/system/
├── cdpilot-twitter.service
└── cdpilot-twitter.timer

/var/log/cdpilot-twitter/
└── YYYY-MM-DD-HHMM.log        # Her run için ayrı log
```

## Güvenlik Notları

- `/etc/cdpilot-twitter.env` asla git'e eklenmez (`.gitignore` kuralı mevcut)
- chmod 600 ile sadece root okuyabilir
- systemd service `NoNewPrivileges=yes` ile privilege escalation engellenir
- `User=nadir` ile root olmadan çalışır
