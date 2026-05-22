#!/usr/bin/env bash
# =============================================================================
# cdpilot Twitter Bot — Sunucu 21 Deploy Script
# =============================================================================
# Kullanım:
#   ./deploy.sh           — full deploy
#   ./deploy.sh --dry-run — komutları yazdır, çalıştırma
#
# Gereksinimler:
#   - WireGuard VPN aktif (10.0.0.21 erişilebilir)
#   - SSH key auth kurulu: nadir@10.0.0.21
#   - Sunucu'da /etc/cdpilot-twitter.env mevcut (chmod 600)
#
# Idempotent: tekrar çalıştırmak güvenli, mevcut servisleri bozmaz.
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Konfigürasyon
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_USER="nadir"
REMOTE_HOST="10.0.0.21"
REMOTE_BASE="/home/nadir/cdpilot-twitter-bot"
SYSTEMD_DIR="/etc/systemd/system"

LOCAL_MASTER_PLAN="${HOME}/01dev/cdpilot/.claude/docs/twitter-master-plan/"
LOCAL_SKILL="${HOME}/.claude/skills/cdpilot-twitter-bot/SKILL.md"
LOCAL_RUN_SCRIPT="${SCRIPT_DIR}/cdpilot-twitter-run.sh"

SERVICE_FILE="cdpilot-twitter.service"
TIMER_FILE="cdpilot-twitter.timer"

DRY_RUN=0

# -----------------------------------------------------------------------------
# Argüman işleme
# -----------------------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN=1
      ;;
    *)
      echo "[ERROR] Bilinmeyen argüman: $arg"
      echo "Kullanım: $0 [--dry-run]"
      exit 1
      ;;
  esac
done

# -----------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# -----------------------------------------------------------------------------
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log_step() {
  echo ""
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] >>> $*"
}

run_cmd() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [DRY-RUN] $*"
  else
    eval "$*"
  fi
}

run_ssh() {
  local remote_cmd="$1"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [DRY-RUN] ssh ${REMOTE_USER}@${REMOTE_HOST} '${remote_cmd}'"
  else
    ssh "${REMOTE_USER}@${REMOTE_HOST}" "${remote_cmd}"
  fi
}

die() {
  echo ""
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [HATA] $*" >&2
  exit 1
}

# -----------------------------------------------------------------------------
# Başlangıç
# -----------------------------------------------------------------------------
if [[ "$DRY_RUN" -eq 1 ]]; then
  log "=== DRY-RUN modu aktif — hiçbir şey çalıştırılmayacak ==="
fi

log "=== cdpilot Twitter Bot — Sunucu 21 Deployment Başlıyor ==="

# -----------------------------------------------------------------------------
# Adım 1: VPN bağlantısı kontrolü
# -----------------------------------------------------------------------------
log_step "Adım 1/6: VPN bağlantısı kontrol ediliyor (10.0.0.21)..."

if [[ "$DRY_RUN" -eq 0 ]]; then
  if ! ping -c1 -W2 10.0.0.21 > /dev/null 2>&1; then
    die "Sunucu 10.0.0.21 erişilemiyor. WireGuard VPN aktif mi?\n\
       Kontrol: wg show\n\
       Bağlan: sudo wg-quick up wg0"
  fi
  log "VPN OK — 10.0.0.21 erişilebilir."
else
  echo "  [DRY-RUN] ping -c1 -W2 10.0.0.21"
fi

# -----------------------------------------------------------------------------
# Adım 2: SSH bağlantısı testi
# -----------------------------------------------------------------------------
log_step "Adım 2/6: SSH bağlantısı test ediliyor..."

if [[ "$DRY_RUN" -eq 0 ]]; then
  if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${REMOTE_USER}@${REMOTE_HOST}" "echo OK" > /dev/null 2>&1; then
    die "SSH bağlantısı başarısız: ${REMOTE_USER}@${REMOTE_HOST}\n\
       SSH key kurulu mu? ssh-copy-id ${REMOTE_USER}@${REMOTE_HOST}"
  fi
  log "SSH OK — key auth çalışıyor."
else
  echo "  [DRY-RUN] ssh ${REMOTE_USER}@${REMOTE_HOST} 'echo OK'"
fi

# -----------------------------------------------------------------------------
# Adım 3: Uzak dizin yapısı oluştur
# -----------------------------------------------------------------------------
log_step "Adım 3/6: Sunucu'da dizin yapısı hazırlanıyor..."

run_ssh "mkdir -p ${REMOTE_BASE}/master-plan ${REMOTE_BASE}/skill"
log "Dizinler hazır: ${REMOTE_BASE}/"

# -----------------------------------------------------------------------------
# Adım 4: Dosya senkronizasyonu (rsync)
# -----------------------------------------------------------------------------
log_step "Adım 4/6: Dosyalar senkronize ediliyor..."

# Twitter master plan dökümanları
if [[ -d "$LOCAL_MASTER_PLAN" ]]; then
  log "Master plan rsync: ${LOCAL_MASTER_PLAN} → ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE}/master-plan/"
  run_cmd "rsync -avz --delete \
    '${LOCAL_MASTER_PLAN}' \
    '${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE}/master-plan/'"
else
  log "[UYARI] Lokal master-plan dizini bulunamadı: ${LOCAL_MASTER_PLAN}"
  log "        Devam ediliyor — sunucu'da önceki versiyon kullanılacak."
fi

# cdpilot-twitter-bot skill
if [[ -f "$LOCAL_SKILL" ]]; then
  log "Skill rsync: ${LOCAL_SKILL} → ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE}/skill/SKILL.md"
  run_cmd "rsync -avz \
    '${LOCAL_SKILL}' \
    '${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE}/skill/SKILL.md'"
else
  log "[UYARI] Lokal skill dosyası bulunamadı: ${LOCAL_SKILL}"
fi

# run script
if [[ -f "$LOCAL_RUN_SCRIPT" ]]; then
  log "Run script gönderiliyor: ${LOCAL_RUN_SCRIPT} → ${REMOTE_BASE}/cdpilot-twitter-run.sh"
  run_cmd "rsync -avz \
    '${LOCAL_RUN_SCRIPT}' \
    '${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE}/cdpilot-twitter-run.sh'"
  run_ssh "chmod +x '${REMOTE_BASE}/cdpilot-twitter-run.sh'"
else
  log "[UYARI] Run script bulunamadı: ${LOCAL_RUN_SCRIPT}"
fi

# -----------------------------------------------------------------------------
# Adım 5: systemd unit dosyaları kopyala + kur
# -----------------------------------------------------------------------------
log_step "Adım 5/6: systemd unit dosyaları kuruluyor..."

SERVICE_LOCAL="${SCRIPT_DIR}/${SERVICE_FILE}"
TIMER_LOCAL="${SCRIPT_DIR}/${TIMER_FILE}"

if [[ ! -f "$SERVICE_LOCAL" ]]; then
  die "Service dosyası bulunamadı: ${SERVICE_LOCAL}"
fi

if [[ ! -f "$TIMER_LOCAL" ]]; then
  die "Timer dosyası bulunamadı: ${TIMER_LOCAL}"
fi

# /tmp üzerinden kopyala (sudo cp ile)
log "systemd dosyaları /tmp üzerinden aktarılıyor..."
run_cmd "scp '${SERVICE_LOCAL}' '${REMOTE_USER}@${REMOTE_HOST}:/tmp/${SERVICE_FILE}'"
run_cmd "scp '${TIMER_LOCAL}'  '${REMOTE_USER}@${REMOTE_HOST}:/tmp/${TIMER_FILE}'"

# sudo ile systemd dizinine taşı
run_ssh "sudo cp /tmp/${SERVICE_FILE} ${SYSTEMD_DIR}/${SERVICE_FILE} \
  && sudo cp /tmp/${TIMER_FILE}  ${SYSTEMD_DIR}/${TIMER_FILE} \
  && sudo chmod 644 ${SYSTEMD_DIR}/${SERVICE_FILE} ${SYSTEMD_DIR}/${TIMER_FILE} \
  && rm -f /tmp/${SERVICE_FILE} /tmp/${TIMER_FILE}"

log "systemd unit dosyaları ${SYSTEMD_DIR}/ altına kopyalandı."

# daemon-reload + enable + start
run_ssh "sudo systemctl daemon-reload"
log "systemctl daemon-reload OK"

run_ssh "sudo systemctl enable cdpilot-twitter.timer"
log "cdpilot-twitter.timer enable edildi."

run_ssh "sudo systemctl start cdpilot-twitter.timer"
log "cdpilot-twitter.timer başlatıldı."

# -----------------------------------------------------------------------------
# Adım 6: Doğrulama
# -----------------------------------------------------------------------------
log_step "Adım 6/6: Deployment doğrulanıyor..."

if [[ "$DRY_RUN" -eq 0 ]]; then
  echo ""
  echo "--- Timer durumu ---"
  ssh "${REMOTE_USER}@${REMOTE_HOST}" "systemctl list-timers 'cdpilot-twitter*' --no-pager"
  echo ""
  echo "--- Service durumu ---"
  ssh "${REMOTE_USER}@${REMOTE_HOST}" "systemctl status cdpilot-twitter.timer --no-pager || true"
else
  echo "  [DRY-RUN] systemctl list-timers cdpilot-twitter*"
  echo "  [DRY-RUN] systemctl status cdpilot-twitter.timer"
fi

# -----------------------------------------------------------------------------
# Tamamlandı
# -----------------------------------------------------------------------------
echo ""
log "=== Deployment tamamlandı ==="
log "Log takibi: ssh ${REMOTE_USER}@${REMOTE_HOST} 'journalctl -u cdpilot-twitter -f'"
log "Son loglar: ssh ${REMOTE_USER}@${REMOTE_HOST} 'ls -lt /var/log/cdpilot-twitter/ | head -10'"
