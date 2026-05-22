#!/usr/bin/env bash
# =============================================================================
# cdpilot Twitter Bot — Login Bootstrap (TEK SEFERLİK)
# =============================================================================
# Bu script ilk Twitter oturumunu açmak için kullanılır.
# X11 forwarding ile sunucu'daki tarayıcıyı lokalinizde gösterir,
# manuel login yapmanızı bekler, ardından cookie ve profil yedekler.
#
# Gereksinimler:
#   - macOS: XQuartz kurulu (brew install --cask xquartz)
#   - Linux: X11 sunucusu aktif
#   - VPN aktif (10.0.0.21 erişilebilir)
#   - ssh -X ile sunucuya bağlanabilme yeteneği
#
# Kullanım:
#   ./login-bootstrap.sh
#
# Tekrar gerekliyse (session expire):
#   ./login-bootstrap.sh  (aynı script, idempotent)
# =============================================================================

set -euo pipefail

REMOTE_USER="nadir"
REMOTE_HOST="10.0.0.21"
REMOTE_BOT_DIR="/home/nadir/cdpilot-twitter-bot"
LOCAL_PROFILE_BACKUP="${HOME}/.cdpilot-backup-twitter-profile"

log() {
  echo ""
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

separator() {
  echo ""
  echo "─────────────────────────────────────────────────────"
}

# -----------------------------------------------------------------------------
# Başlangıç uyarıları
# -----------------------------------------------------------------------------
separator
echo "  cdpilot Twitter Bot — Login Bootstrap"
echo "  Bu script tek seferlik (veya session expire sonrası) kullanılır."
separator

log "UYARI: Bu script X11 forwarding gerektirir."
echo "       macOS için XQuartz kurulu olmalı: brew install --cask xquartz"
echo "       DISPLAY değişkeni: ${DISPLAY:-'(tanımlı değil)'}"

if [[ -z "${DISPLAY:-}" ]]; then
  echo ""
  echo "[UYARI] DISPLAY ortam değişkeni boş. X11 forwarding çalışmıyor olabilir."
  echo "        XQuartz açık ve SSH -X ile bağlı olduğunuzdan emin olun."
  echo ""
fi

# -----------------------------------------------------------------------------
# Adım 1: VPN kontrolü
# -----------------------------------------------------------------------------
separator
log "Adım 1: VPN bağlantısı kontrol ediliyor (${REMOTE_HOST})..."

if ! ping -c1 -W2 "$REMOTE_HOST" > /dev/null 2>&1; then
  echo ""
  echo "[HATA] ${REMOTE_HOST} adresine ulaşılamıyor."
  echo "       WireGuard VPN aktif mi? Kontrol: wg show"
  exit 1
fi

echo "VPN OK — ${REMOTE_HOST} erişilebilir."

# -----------------------------------------------------------------------------
# Adım 2: SSH bağlantı testi
# -----------------------------------------------------------------------------
separator
log "Adım 2: SSH bağlantısı test ediliyor (${REMOTE_USER}@${REMOTE_HOST})..."

if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${REMOTE_USER}@${REMOTE_HOST}" "echo ok" > /dev/null 2>&1; then
  echo "[HATA] SSH bağlantısı başarısız."
  echo "       ssh-copy-id ${REMOTE_USER}@${REMOTE_HOST} ile SSH key ekleyin."
  exit 1
fi

echo "SSH OK."

# -----------------------------------------------------------------------------
# Adım 3: Sunucu'da cdpilot headless=false başlat (X11 forwarding ile)
# -----------------------------------------------------------------------------
separator
log "Adım 3: Sunucu'da tarayıcı başlatılıyor (X11 forwarding aktif)..."
echo ""
echo "  NOT: Tarayıcı penceresinin lokalinizde açılması 5-15 saniye sürebilir."
echo "  Açılmazsa XQuartz'ı restart etmeyi deneyin."
echo ""

# X-forward ile arka planda başlat
ssh -X "${REMOTE_USER}@${REMOTE_HOST}" 'cdpilot launch --headless=false' &
BROWSER_PID=$!
log "Tarayıcı PID (lokal SSH process): ${BROWSER_PID}"

echo ""
echo "Tarayıcının başlaması için 5 saniye bekleniyor..."
sleep 5

# -----------------------------------------------------------------------------
# Adım 4: Manuel login adımları
# -----------------------------------------------------------------------------
separator
echo ""
echo "  MANUEL ADIMLAR:"
echo ""
echo "  1. Açılan tarayıcıda şu adrese gidin:"
echo "     https://x.com/i/flow/login"
echo ""
echo "  2. @cdpilot hesabına giriş yapın."
echo "     (2FA gerekirse telefonunuzdan onaylayın)"
echo ""
echo "  3. Ana sayfa yüklendiğinde giriş tamamdır."
echo ""
echo "  4. Hazır olunca aşağıda Enter'a basın."
echo ""
separator

read -r -p "Login tamamlandı, Enter'a basın... "

# -----------------------------------------------------------------------------
# Adım 5: Cookie kaydet
# -----------------------------------------------------------------------------
separator
log "Adım 5: Twitter cookie'leri kaydediliyor..."

ssh "${REMOTE_USER}@${REMOTE_HOST}" \
  "cdpilot cookies save ${REMOTE_BOT_DIR}/twitter-cookies.json"

echo "Cookie kaydedildi: ${REMOTE_BOT_DIR}/twitter-cookies.json"

# -----------------------------------------------------------------------------
# Adım 6: Profil yedekle (lokal)
# -----------------------------------------------------------------------------
separator
log "Adım 6: Tarayıcı profili lokal'e yedekleniyor..."

mkdir -p "$LOCAL_PROFILE_BACKUP"
rsync -av --delete \
  "${REMOTE_USER}@${REMOTE_HOST}:/home/nadir/.cdpilot/profile/" \
  "${LOCAL_PROFILE_BACKUP}/"

echo "Yedek tamamlandı: ${LOCAL_PROFILE_BACKUP}/"

# -----------------------------------------------------------------------------
# Temizlik: arka plan SSH process'ini kapat
# -----------------------------------------------------------------------------
log "Arka plan tarayıcı process'i kapatılıyor..."
kill "$BROWSER_PID" 2>/dev/null || true

# -----------------------------------------------------------------------------
# Tamamlandı
# -----------------------------------------------------------------------------
separator
log "Bootstrap tamamlandı."
echo ""
echo "  Sonraki adım: ./deploy.sh çalıştır (systemd timer kurmak için)"
echo "  Yeniden login gerekirse: ./login-bootstrap.sh"
separator
echo ""
