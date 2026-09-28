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

echo "Validating manifest.json..."
npx -y @anthropic-ai/mcpb validate manifest.json

echo "Packing $REPO_ROOT -> $OUT"
npx -y @anthropic-ai/mcpb pack "$REPO_ROOT" "$OUT"

echo "Verifying bundle info..."
npx -y @anthropic-ai/mcpb info "$OUT"

echo "Built $OUT"
