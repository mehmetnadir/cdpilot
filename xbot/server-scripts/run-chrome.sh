#!/usr/bin/env bash
# Server-side: Chrome'u Xvfb içinde foreground çalıştır
# systemd-friendly wrapper

LOG=/opt/cdpilot-twitter-bot/logs/chrome.log
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1

echo "[$(date)] === run-chrome.sh starting ==="

# Eski process'leri öldür (varsa)
pkill -f google-chrome
pkill -f Xvfb
sleep 1

echo "[$(date)] launching..."

exec xvfb-run -a --server-args="-screen 0 1280x800x24" \
  /usr/bin/google-chrome \
    --remote-debugging-port=9222 \
    --user-data-dir=/opt/cdpilot-twitter-bot/profile \
    --no-sandbox \
    --no-first-run \
    --no-default-browser-check \
    --disable-background-timer-throttling \
    --disable-renderer-backgrounding \
    --disable-gpu \
    --disable-software-rasterizer \
    --disable-dev-shm-usage \
    --disable-features=OptimizationGuideModelDownloading,OptimizationHints,OptimizationHintsFetching,OnDeviceModel,VideoCapture,MediaRouter,Translate \
    --disable-audio-output \
    --disable-audio-input \
    --disable-sync \
    --disable-component-update \
    --disable-domain-reliability \
    --disable-breakpad \
    --disable-crash-reporter \
    --no-pings \
    --metrics-recording-only \
    --mute-audio \
    --window-size=1280,800
