#!/usr/bin/env bash
# Copy desktop Barra CSV bundle into paper-factor workspace.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-/mnt/c/Users/DELL/Desktop/Barra模型}"
DEST="${ROOT}/git_ignore_folder/barra_model"

if [[ ! -d "$SRC" ]]; then
  echo "Source not found: $SRC"
  echo "Usage: bash scripts/setup_barra_model.sh [/path/to/Barra模型]"
  exit 1
fi

mkdir -p "$DEST"
echo "==> Copy Barra model CSV files"
echo "    from: $SRC"
echo "    to:   $DEST"
cp -f "$SRC"/*.csv "$DEST/" 2>/dev/null || true
ls -lh "$DEST"
echo "Done. Set PAPER_FACTOR_BARRA_DIR=$DEST if using a custom path."
