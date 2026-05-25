#!/bin/bash
# deploy-srv21.sh — xbot/ kodunu srv21'e push, daemon restart, smoke test.
#
# Önkoşullar:
#  - VPN bağlı (blok2 / 10.0.0.* erişimi)
#  - SSH key srv21'de yetkili
#
# Kullanım:
#   ./deploy-srv21.sh           # full deploy + smoke test
#   ./deploy-srv21.sh diag      # sadece teşhis (claude binary, daemon status)
#   ./deploy-srv21.sh sync      # sadece rsync (restart yok)
#   ./deploy-srv21.sh restart   # sadece daemon restart
#
# Çıktıların hepsi Türkçe — kullanıcı için.

set -e

SRV="srv21"
SRV_PATH="/opt/cdpilot-twitter-bot"
LOCAL_XBOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-full}"

ssh_check() {
    if ! ssh -o ConnectTimeout=5 "$SRV" "echo OK" > /dev/null 2>&1; then
        echo "❌ srv21'e erişilemiyor. VPN bağlı mı? (~/.config/server-manager/vpn/vpn.sh connect blok2)"
        exit 1
    fi
    echo "✅ srv21 erişilebilir"
}

diag() {
    echo ""
    echo "═══ srv21 TEŞHİS ═══"
    echo ""
    echo "[1/5] claude binary kontrolü:"
    ssh "$SRV" 'which claude; ls -la $(which claude 2>/dev/null) 2>/dev/null; file $(which claude 2>/dev/null) 2>/dev/null | head -3' || true

    echo ""
    echo "[2/5] claude versiyon + login:"
    ssh "$SRV" 'claude --version 2>&1 | head -3 || echo "claude çalışmıyor"' || true

    echo ""
    echo "[3/5] Daemon durumu:"
    ssh "$SRV" 'systemctl is-active cdpilot-telegram-daemon 2>&1; systemctl status cdpilot-telegram-daemon --no-pager 2>&1 | head -15' || true

    echo ""
    echo "[4/5] Daemon log (son 20 satır):"
    ssh "$SRV" 'journalctl -u cdpilot-telegram-daemon --no-pager -n 20 2>&1' || true

    echo ""
    echo "[5/5] Pending json son güncelleme:"
    ssh "$SRV" "ls -la $SRV_PATH/telegram-pending.json 2>/dev/null; stat -c '%y' $SRV_PATH/telegram-pending.json 2>/dev/null" || true
    echo ""
}

sync_code() {
    echo ""
    echo "═══ KOD SYNC (--delete YOK — runtime data güvende) ═══"
    echo "Mac:$LOCAL_XBOT/ → $SRV:$SRV_PATH/"
    # CRITICAL: --delete YASAK. srv21'de Mac'te olmayan kritik dosyalar var:
    # twikit-venv/, cookies/, state/, posted/, queue/, drafts/, *.env, logs/
    # 2026-05-25'te --delete tüm bunları sildi → tam recovery 30dk sürdü.
    rsync -avz \
        --exclude='__pycache__' \
        --exclude='.pytest_cache' \
        --exclude='*.pyc' \
        --exclude='tests/' \
        "$LOCAL_XBOT/" "$SRV:$SRV_PATH/"
    echo "✅ Sync tamam (eski runtime data korundu)"
}

restart_daemon() {
    echo ""
    echo "═══ DAEMON RESTART ═══"
    ssh "$SRV" "systemctl restart cdpilot-telegram-daemon && sleep 2 && systemctl is-active cdpilot-telegram-daemon"
    echo "✅ Daemon ayakta"
}

smoke_strategy() {
    echo ""
    echo "═══ SMOKE — STRATEJİ KARTI ═══"
    echo "Test stratejisi srv21'den manuel tetikleniyor..."
    ssh "$SRV" "cd $SRV_PATH && CDPILOT_STRATEGIST_FORCE=1 ./twikit-venv/bin/python ops/daily_strategist.py 2>&1 | tail -10"
}

case "$MODE" in
    diag)
        ssh_check
        diag
        ;;
    sync)
        ssh_check
        sync_code
        ;;
    restart)
        ssh_check
        restart_daemon
        ;;
    full|*)
        ssh_check
        diag
        sync_code
        restart_daemon
        smoke_strategy
        echo ""
        echo "✅ Deploy + smoke tamam. Telegram'a strateji kartı geldi mi kontrol et."
        ;;
esac
