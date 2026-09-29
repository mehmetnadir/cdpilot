#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for dir in "$SCRIPT_DIR"/*; do
  if [ -d "$dir" ] && [ -f "$dir/run.sh" ]; then
    echo "========================================"
    echo "Running example: $(basename "$dir")"
    echo "========================================"
    sh "$dir/run.sh"
    echo ""
  fi
done

"${CDPILOT_PYTHON:-python3}" "$SCRIPT_DIR/sync-readmes.py"
echo "All examples completed successfully!"
