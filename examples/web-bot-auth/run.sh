#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CDPILOT="${CDPILOT:-node $(cd ../.. && pwd)/bin/cdpilot.js}"
export CDPILOT_PYTHON="${CDPILOT_PYTHON:-/usr/local/bin/python3}"
export CDP_PORT="${CDP_PORT:-59855}"
export CHROME_HEADLESS=1

TMP_DIR="$(mktemp -d)"
export CDPILOT_HOME="${TMP_DIR}/home"
export CDPILOT_PROFILE="${TMP_DIR}/prof"
mkdir -p "$CDPILOT_HOME/bot-auth" "$CDPILOT_PROFILE" "output"
chmod 700 "$CDPILOT_HOME/bot-auth"

# The PUBLIC test key from RFC 9421 Appendix B.1.4 (test-key-ed25519), the one
# Cloudflare's demo site verifies. Never use it for anything real.
RFC9421_TEST_D="n4Ni-HpISpVObnQMW0wOhCKROaIKqKtW_2ZYb2p9KcU"
"${CDPILOT_PYTHON:-python3}" - "$RFC9421_TEST_D" "$CDPILOT_HOME/bot-auth/ed25519.key" << 'PY'
import base64, sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
d = base64.urlsafe_b64decode(sys.argv[1] + "=")
key = Ed25519PrivateKey.from_private_bytes(d)
open(sys.argv[2], "wb").write(key.private_bytes(serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
PY
chmod 600 "$CDPILOT_HOME/bot-auth/ed25519.key"

cat << 'EOF' > "$CDPILOT_HOME/bot-auth/config.json"
{
  "agent_url": "https://http-message-signatures-example.research.cloudflare.com",
  "agent_format": "legacy"
}
EOF
chmod 600 "$CDPILOT_HOME/bot-auth/config.json"

trap '$CDPILOT stop >/dev/null 2>&1 || true' EXIT

RAW_LOG="${TMP_DIR}/raw_output.txt"

{
  echo "$ cdpilot bot-auth status"
  $CDPILOT bot-auth status 2>&1

  echo "$ cdpilot bot-auth directory --headers --authority example.com"
  $CDPILOT bot-auth directory --headers --authority example.com 2>&1

  echo "$ cdpilot launch --bot-auth"
  $CDPILOT launch --bot-auth 2>&1

  echo "$ cdpilot go https://http-message-signatures-example.research.cloudflare.com/"
  $CDPILOT go https://http-message-signatures-example.research.cloudflare.com/ 2>&1

  echo "$ cdpilot content"
  $CDPILOT content 2>&1

  echo "$ cdpilot shot output/screenshot.png"
  $CDPILOT shot output/screenshot.png 2>&1

  echo "$ cdpilot stop"
  $CDPILOT stop 2>&1
} > "$RAW_LOG"

sed -e "s|${HOME}|~|g" -e "s|/private/tmp/[^/]*|<tmp>|g" -e "s|/tmp/[^/]*|<tmp>|g" "$RAW_LOG" > output/transcript.txt
cat output/transcript.txt
