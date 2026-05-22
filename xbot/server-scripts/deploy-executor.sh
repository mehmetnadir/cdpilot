#!/usr/bin/env bash
# Deploy queue_executor.py + systemd unit'larını srv21'e yükle ve enable et.
# Per-user systemd kullanır (sudo gerekmez, user session'ında çalışır).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="srv21"
REMOTE_DIR="/opt/cdpilot-twitter-bot"
SYSTEMD_USER_DIR='$HOME/.config/systemd/user'

echo "→ Deploying to ${SERVER}:${REMOTE_DIR}"

# 1. Server'da dizinler ve queue_executor.py
ssh "$SERVER" "mkdir -p ${REMOTE_DIR}/queue ${REMOTE_DIR}/analytics ${REMOTE_DIR}/master-plan && ${SYSTEMD_USER_DIR/\$HOME/$HOME} 2>/dev/null; true"

# 2. queue_executor.py + queue-schema.md
scp "${SCRIPT_DIR}/queue_executor.py" "${SERVER}:${REMOTE_DIR}/queue_executor.py"
scp "${SCRIPT_DIR}/queue-schema.md" "${SERVER}:${REMOTE_DIR}/queue-schema.md"
ssh "$SERVER" "chmod +x ${REMOTE_DIR}/queue_executor.py"

# 3. systemd unit'ları (per-user)
ssh "$SERVER" 'mkdir -p ~/.config/systemd/user'
scp "${SCRIPT_DIR}/cdpilot-twitter-executor.service" "${SERVER}:~/.config/systemd/user/cdpilot-twitter-executor.service"
scp "${SCRIPT_DIR}/cdpilot-twitter-executor.timer" "${SERVER}:~/.config/systemd/user/cdpilot-twitter-executor.timer"

# 4. systemd reload + enable + start
ssh "$SERVER" 'systemctl --user daemon-reload && systemctl --user enable --now cdpilot-twitter-executor.timer'

# 5. Loginctl linger — user logout olsa bile timer çalışsın (sudo gerek)
ssh "$SERVER" 'loginctl enable-linger $USER 2>&1 || echo "(linger requires sudo, skipped — timer durur user logout olunca)"'

echo
echo "✓ Deploy complete"
echo
echo "Doğrulama:"
echo "  ssh ${SERVER} 'systemctl --user status cdpilot-twitter-executor.timer'"
echo "  ssh ${SERVER} 'systemctl --user list-timers | grep cdpilot'"
echo "  ssh ${SERVER} 'journalctl --user -u cdpilot-twitter-executor -n 20'"
