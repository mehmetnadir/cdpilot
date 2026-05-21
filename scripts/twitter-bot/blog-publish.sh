#!/usr/bin/env bash
# blog-publish.sh — wrapper for cdpilot blog publish
# Usage: ./blog-publish.sh <tweet-url|day-NNN>

set -euo pipefail

CDPILOT_DIR="/Users/nadir/01dev/cdpilot"
SITE_DIR="/Users/nadir/01dev/cdpilot-site"
BLOG_DIR="$SITE_DIR/content/blog"

GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
  echo "Usage: $(basename "$0") <tweet-url|day-NNN>"
  echo ""
  echo "Examples:"
  echo "  $(basename "$0") day-001"
  echo "  $(basename "$0") day-025"
  echo "  $(basename "$0") https://x.com/user/status/1234567890"
  echo ""
  echo "On success: writes blog post, git commits to cdpilot-site (no push)."
  exit 0
}

if [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
  usage
fi

if [[ -z "${1:-}" ]]; then
  echo -e "${RED}Error: source argument required.${NC}" >&2
  usage
fi

SOURCE="$1"

echo -e "${CYAN}Publishing blog post from: $SOURCE${NC}"

# Run cdpilot blog publish
node "$CDPILOT_DIR/bin/cdpilot.js" blog publish "$SOURCE"

# Find the most recently written blog post
LATEST_FILE=$(ls -t "$BLOG_DIR"/*.md 2>/dev/null | head -n 1)
if [[ -z "$LATEST_FILE" ]]; then
  echo -e "${RED}Error: no blog post file found in $BLOG_DIR${NC}" >&2
  exit 1
fi

FILENAME=$(basename "$LATEST_FILE")
SLUG="${FILENAME%.*}"

echo ""
echo -e "${GREEN}File: $LATEST_FILE${NC}"
echo -e "${CYAN}Preview URL: https://cdpilot.ndr.ist/blog/$SLUG${NC}"

# Commit to cdpilot-site (no push — manual approval required)
cd "$SITE_DIR"
git add content/blog/
git commit -m "content(blog): add $SLUG from $SOURCE"

echo ""
echo -e "${GREEN}Committed to cdpilot-site.${NC}"
echo "To publish: cd $SITE_DIR && git push"
