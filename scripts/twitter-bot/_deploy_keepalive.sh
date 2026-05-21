#!/usr/bin/env bash
# Server'a keep-alive + snapshot service'lerini deploy et
set +e

chmod +x /opt/cdpilot-twitter-bot/keep-alive.sh
chmod +x /opt/cdpilot-twitter-bot/snapshot-cookies.sh
mkdir -p /opt/cdpilot-twitter-bot/{alerts,backups,logs}

systemctl --user daemon-reload
systemctl --user enable --now cdpilot-keep-alive.timer
systemctl --user enable --now cdpilot-snapshot.timer
sleep 2

echo "--- timers ---"
systemctl --user list-timers --no-pager | grep cdpilot | head -10
echo "--- keep-alive trigger ---"
systemctl --user start cdpilot-keep-alive.service
sleep 6
tail -5 /opt/cdpilot-twitter-bot/logs/keep-alive.log
echo "--- snapshot trigger ---"
systemctl --user start cdpilot-snapshot.service
sleep 4
tail -5 /opt/cdpilot-twitter-bot/logs/snapshot.log
