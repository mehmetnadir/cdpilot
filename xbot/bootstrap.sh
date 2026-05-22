#!/usr/bin/env bash
# cdpilot Twitter Bot — Bootstrap
# Tek seferlik kurulum: ~/cdpilot-twitter-data ağacını ve iskelet dosyaları oluşturur.
# Idempotent: tekrar çalıştırılabilir, mevcut dosyaların üzerine yazmaz.

set -e

DATA_DIR="$HOME/cdpilot-twitter-data"
TODAY=$(date +%Y-%m-%d)

echo "→ cdpilot Twitter Bot Bootstrap"
echo "  Data dir: $DATA_DIR"
echo

# 1. Dizin yapısı
mkdir -p "$DATA_DIR"/{queue,logs,alerts,analytics,discoveries,backups}
echo "✓ Directories created"

# 2. launch-date.txt
LAUNCH_FILE="$DATA_DIR/launch-date.txt"
if [ ! -f "$LAUNCH_FILE" ]; then
  echo "$TODAY" > "$LAUNCH_FILE"
  echo "✓ launch-date.txt → $TODAY (Day 1 starts today)"
else
  echo "↺ launch-date.txt exists → $(cat "$LAUNCH_FILE")"
fi

# 3. learnings.md
LEARN_FILE="$DATA_DIR/learnings.md"
if [ ! -f "$LEARN_FILE" ]; then
  cat > "$LEARN_FILE" <<'EOF'
# Learnings — cdpilot Twitter

Cowork sabah session'ı her gün dünün analytics'inden çıkarımları buraya append eder.
Format: `## YYYY-MM-DD Analytics Review` ve altında metrikler.
EOF
  echo "✓ learnings.md initialized"
else
  echo "↺ learnings.md exists"
fi

# 4. daily-log.md
DAILY_FILE="$DATA_DIR/daily-log.md"
if [ ! -f "$DAILY_FILE" ]; then
  cat > "$DAILY_FILE" <<'EOF'
# Daily Log — cdpilot Twitter

Cowork her sabah Step 9'da bu dosyaya günlük özet append eder.
EOF
  echo "✓ daily-log.md initialized"
else
  echo "↺ daily-log.md exists"
fi

# 5. state.json
STATE_FILE="$DATA_DIR/state.json"
if [ ! -f "$STATE_FILE" ]; then
  cat > "$STATE_FILE" <<'EOF'
{
  "last_grok_mention": null,
  "last_comeback_index": null,
  "last_cowork_run": null
}
EOF
  echo "✓ state.json initialized"
else
  echo "↺ state.json exists"
fi

# 6. engagement-targets.md
TARGETS_FILE="$DATA_DIR/engagement-targets.md"
if [ ! -f "$TARGETS_FILE" ]; then
  cat > "$TARGETS_FILE" <<'EOF'
# Engagement Targets — cdpilot Twitter

Niche: CDP / DevTools / browser automation / headless / LLM×automation

## Tier 1 — high signal accounts (günlük etkileşim)
<!-- 5-10 hesap. Her gün en az 1 reply + 1-2 like. Doldur: -->
<!-- - @handle — why — last engaged: YYYY-MM-DD -->

## Tier 2 — medium signal (haftalık etkileşim)
<!-- 20-30 hesap. Rotation ile her gün 2-3'ü ile etkileşim. -->

## Tier 3 — discovery pool (keşif/yeni)
<!-- Trending'den, mention'lardan toplanır. 1 hafta sonra Tier 2'ye terfi veya düşer. -->
EOF
  echo "✓ engagement-targets.md initialized (boş — Tier 1/2/3 hesapları sen ekle)"
else
  echo "↺ engagement-targets.md exists"
fi

# 7. tone-prefs.md
TONE_FILE="$DATA_DIR/tone-prefs.md"
if [ ! -f "$TONE_FILE" ]; then
  cat > "$TONE_FILE" <<'EOF'
# Tone Preferences — cdpilot Twitter

<!-- Ton notları. Örneğin: -->
<!-- - Maker voice, lower-case başlangıç tercih edilir -->
<!-- - Aşırı emoji yok, max 1/post -->
<!-- - "obviously", "literally" gibi filler yasak -->
<!-- - Teknik terimleri Türkçe değil İngilizce bırak -->
EOF
  echo "✓ tone-prefs.md initialized"
else
  echo "↺ tone-prefs.md exists"
fi

# 8. heartbeat
HB_FILE="$DATA_DIR/heartbeat.txt"
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$HB_FILE"
echo "✓ heartbeat written"

echo
echo "─── Bootstrap complete ───"
echo
echo "Sonraki adımlar:"
echo "  1) Cowork app'ten ~/cdpilot-twitter-data klasörünü mount et"
echo "     (Folder picker'da home klasörüne git, cdpilot-twitter-data'yı seç)"
echo
echo "  2) Server tarafı:"
echo "     ssh srv21 'mkdir -p /opt/cdpilot-twitter-bot/{queue,analytics,master-plan}'"
echo "     ssh srv21 'sudo mkdir -p /var/log/cdpilot-twitter && sudo chown \$USER /var/log/cdpilot-twitter'"
echo
echo "  3) Twitter login (browser açık olmalı):"
echo "     cd ~/01dev/cdpilot && python3 src/cdpilot.py agent twitter login"
echo
echo "  4) Cowork session'a dön — 'morning routine'i çalıştır' de"
