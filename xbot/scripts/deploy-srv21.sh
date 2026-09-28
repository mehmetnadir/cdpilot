#!/bin/bash
# deploy-srv21.sh — xbot/ kodunu srv21'e push, ntfy smoke test.
#
# 2026-09-28: Telegram onay daemon'u (cdpilot-telegram-daemon) emekli. Bu betik
# artık onu yeniden BAŞLATMAZ; bildirimler ntfy'den (ops/_notify.py).
#
# Önkoşullar:
#  - VPN bağlı (blok2 / 10.0.0.* erişimi)
#  - SSH key srv21'de yetkili
#
# Kullanım:
#   ./deploy-srv21.sh           # full deploy + smoke test
#   ./deploy-srv21.sh diag      # sadece teşhis (claude binary, zamanlayıcılar)
#   ./deploy-srv21.sh sync      # sadece rsync
#   ./deploy-srv21.sh smoke     # yalnız ntfy test bildirimi (cdpilot-x, Click'li)
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
    echo "[3/5] Zamanlayıcılar:"
    ssh "$SRV" 'systemctl list-timers --all --no-pager 2>&1 | grep -E "cdpilot-(cycle|poster|sentinel)"' || true

    echo ""
    echo "[4/5] Telegram daemon (emekli olmalı: inactive/disabled):"
    ssh "$SRV" 'systemctl is-active cdpilot-telegram-daemon 2>&1; systemctl is-enabled cdpilot-telegram-daemon 2>&1' || true

    echo ""
    echo "[5/5] ntfy rutin sınırlayıcı durumu:"
    ssh "$SRV" "ls -la $SRV_PATH/state/ntfy-routine.json 2>/dev/null || echo 'henüz yok'" || true
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

smoke_ntfy() {
    echo ""
    echo "═══ SMOKE — ntfy (cdpilot-x, Click → X profili) ═══"
    ssh "$SRV" "cd $SRV_PATH/ops && /usr/bin/python3 -c 'import _notify,sys; ok=_notify._http_publish(_notify.build_payload(\"Deploy testi\", \"cdpilot xbot ntfy yolu çalışıyor — dokununca profil açılır.\", url=_notify.profile_url(_notify.HANDLE))); print(\"ntfy JSON API:\", ok); sys.exit(0 if ok else 1)'"
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
    smoke)
        ssh_check
        smoke_ntfy
        ;;
    full|*)
        ssh_check
        diag
        sync_code
        smoke_ntfy
        echo ""
        echo "✅ Deploy + smoke tamam. Telefonda cdpilot-x kanalına 'Deploy testi' geldi mi bak."
        ;;
esac
