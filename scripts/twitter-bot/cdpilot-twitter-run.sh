#!/usr/bin/env bash
# =============================================================================
# cdpilot Twitter Bot — Run Script (Sunucu'da çalışır)
# =============================================================================
# systemd tarafından çağrılır. /etc/cdpilot-twitter.env'den credential okur,
# claude CLI'ı çalıştırır, log yazar, hata durumunda webhook alert gönderir.
#
# ASLA doğrudan düzenleme — deploy.sh ile güncellenir.
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Log yardımcıları
# -----------------------------------------------------------------------------
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $*"
}

log_err() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2
}

# -----------------------------------------------------------------------------
# Credentials kontrolü
# -----------------------------------------------------------------------------
ENV_FILE="/etc/cdpilot-twitter.env"

if [[ ! -f "$ENV_FILE" ]]; then
  log_err "Credentials dosyası bulunamadı: ${ENV_FILE}"
  log_err "Kurulum: sudo nano ${ENV_FILE} && sudo chmod 600 ${ENV_FILE}"
  exit 1
fi

# shellcheck source=/dev/null
source "$ENV_FILE"

if [[ -z "${CLAUDE_API_KEY:-}" ]]; then
  log_err "CLAUDE_API_KEY tanımlı değil — ${ENV_FILE} dosyasını kontrol edin."
  exit 1
fi

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  log_err "GEMINI_API_KEY tanımlı değil — ${ENV_FILE} dosyasını kontrol edin."
  exit 1
fi

# Ortam değişkenlerine aktar (claude CLI için)
export CLAUDE_API_KEY
export GEMINI_API_KEY

# -----------------------------------------------------------------------------
# Log dizini hazırla
# -----------------------------------------------------------------------------
LOG_DIR="/var/log/cdpilot-twitter"

if [[ ! -d "$LOG_DIR" ]]; then
  sudo mkdir -p "$LOG_DIR"
  sudo chown nadir:nadir "$LOG_DIR"
  sudo chmod 755 "$LOG_DIR"
fi

LOG_FILE="${LOG_DIR}/$(date '+%Y-%m-%d-%H%M').log"

# Bundan sonraki tüm çıktıyı dosyaya da yaz
exec > >(tee -a "$LOG_FILE") 2>&1

log "=== cdpilot Twitter Bot run başlıyor ==="
log "Hostname: $(hostname)"
log "Log dosyası: ${LOG_FILE}"

# -----------------------------------------------------------------------------
# claude CLI kontrolü
# -----------------------------------------------------------------------------
CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"

if [[ -z "$CLAUDE_BIN" ]]; then
  log_err "claude CLI PATH'te bulunamadı."
  log_err "Kontrol: which claude | ls /usr/local/bin/claude"
  exit 1
fi

log "claude CLI: ${CLAUDE_BIN}"

# -----------------------------------------------------------------------------
# Gerekli dosyalar var mı?
# -----------------------------------------------------------------------------
BOT_DIR="/home/nadir/cdpilot-twitter-bot"
SKILL_FILE="${BOT_DIR}/skill/SKILL.md"
MASTER_PLAN_DIR="${BOT_DIR}/master-plan"

if [[ ! -f "$SKILL_FILE" ]]; then
  log_err "SKILL.md bulunamadı: ${SKILL_FILE} — deploy.sh çalıştırıldı mı?"
  exit 1
fi

if [[ ! -d "$MASTER_PLAN_DIR" ]]; then
  log_err "master-plan dizini bulunamadı: ${MASTER_PLAN_DIR}"
  exit 1
fi

# -----------------------------------------------------------------------------
# claude CLI çalıştır
# -----------------------------------------------------------------------------
log "claude çalışıyor..."

set +e  # Hata durumunda exit code yakala, script durmasın
"$CLAUDE_BIN" \
  --model claude-opus-4-5 \
  --no-confirm \
  --print \
  "Run today's cdpilot-twitter-bot posting routine. \
   Read ${SKILL_FILE} and files in ${MASTER_PLAN_DIR}/, then execute the posting plan."
EXIT_CODE=$?
set -e

# -----------------------------------------------------------------------------
# Exit code kontrolü
# -----------------------------------------------------------------------------
if [[ "$EXIT_CODE" -ne 0 ]]; then
  ERR_MSG="$(date '+%Y-%m-%d %H:%M:%S') | cdpilot-twitter FAILED | exit_code=${EXIT_CODE} | log=${LOG_FILE}"
  log_err "claude CLI çıkış kodu: ${EXIT_CODE}"
  echo "$ERR_MSG" >> "$LOG_FILE"

  # Webhook alert (opsiyonel — ALERT_WEBHOOK_URL env'de tanımlıysa)
  if [[ -n "${ALERT_WEBHOOK_URL:-}" ]]; then
    log "Alert webhook gönderiliyor: ${ALERT_WEBHOOK_URL}"
    curl -s -X POST \
      -H 'Content-Type: application/json' \
      -d "{\"text\": \"${ERR_MSG}\"}" \
      "$ALERT_WEBHOOK_URL" || true
  fi

  exit 1
fi

# -----------------------------------------------------------------------------
# Log rotation (30 günden eski dosyaları sil)
# -----------------------------------------------------------------------------
log "Eski log dosyaları temizleniyor (>30 gün)..."
find "$LOG_DIR" -name '*.log' -mtime +30 -delete || true

# -----------------------------------------------------------------------------
# Tamamlandı
# -----------------------------------------------------------------------------
log "=== Run tamamlandı (exit: 0) ==="
