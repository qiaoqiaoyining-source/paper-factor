#!/usr/bin/env bash
# Remove local copies of company data to free C: / WSL disk.
# Does NOT touch .env, papers/inbox PDFs, or factor_outputs (exported factors).
#
# Usage:
#   bash scripts/cleanup_local_heavy_data.sh          # dry-run (print only)
#   bash scripts/cleanup_local_heavy_data.sh --apply  # actually delete

set -euo pipefail

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WIN_USER="${WIN_USER:-DELL}"

_paths=(
  "/mnt/c/Users/${WIN_USER}/Downloads/remote_e"
  "/mnt/remote_e"
  "${ROOT}/git_ignore_folder/factor_implementation_source_data"
  "${ROOT}/git_ignore_folder/factor_implementation_source_data_debug"
)

_rm() {
  local p="$1"
  if [[ -L "$p" ]]; then
    echo "  symlink: $p -> $(readlink "$p")"
    if [[ "$APPLY" == "1" ]]; then
      rm -f "$p"
    fi
    return
  fi
  if [[ -e "$p" ]]; then
    du -sh "$p" 2>/dev/null || true
    if [[ "$APPLY" == "1" ]]; then
      rm -rf "$p"
      echo "  deleted: $p"
    fi
  else
    echo "  (missing) $p"
  fi
}

echo "==> Targets to remove (local data copies only)"
for p in "${_paths[@]}"; do
  echo "--- $p"
  _rm "$p"
done

echo
if [[ "$APPLY" == "0" ]]; then
  echo "Dry-run only. To delete, run:"
  echo "  bash scripts/cleanup_local_heavy_data.sh --apply"
  echo
  echo "Also delete in Windows Explorer (if present):"
  echo "  C:\\Users\\${WIN_USER}\\Downloads\\remote_e"
  echo "  Empty Recycle Bin after deleting."
else
  echo "Done. Check free space:"
  df -h / /mnt/c 2>/dev/null || df -h /
fi
