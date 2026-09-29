#!/usr/bin/env bash
# Builds cdpilot.mcpb (MCP Bundle) from the repo root using the official
# mcpb CLI (https://github.com/modelcontextprotocol/mcpb). The bundle ships
# the same runtime files npm does (bin/, src/cdpilot.py, README.md, LICENSE)
# — see manifest.json (server.entry_point) and .mcpbignore.
#
# Usage: scripts/build-mcpb.sh [output-path]
# Output defaults to cdpilot.mcpb at the repo root (git-ignored; not committed).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$REPO_ROOT/cdpilot.mcpb}"

cd "$REPO_ROOT"
case "$OUT" in /*) ;; *) OUT="$REPO_ROOT/$OUT" ;; esac

echo "Validating manifest.json..."
npx -y @anthropic-ai/mcpb validate manifest.json

# Pack a staged copy holding exactly the shipped files: `mcpb pack` of the repo
# root also takes untracked local files (node_modules/, content/, editor state).
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/src"
cp -R bin "$STAGE/bin"
cp src/cdpilot.py "$STAGE/src/cdpilot.py"
cp README.md LICENSE manifest.json package.json .mcpbignore "$STAGE/"

echo "Packing $REPO_ROOT -> $OUT"
(cd "$STAGE" && npx -y @anthropic-ai/mcpb pack . "$OUT")

echo "Verifying bundle info..."
npx -y @anthropic-ai/mcpb info "$OUT"

echo "Built $OUT"
