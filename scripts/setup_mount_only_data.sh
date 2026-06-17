#!/usr/bin/env bash
# Mount remote E: and use data from the mount (no local copy on C:).
#
# 1) Converts parquet -> daily_pv.h5 ON THE REMOTE E: drive (cache dir)
# 2) Symlinks paper-factor data dirs to that cache (tiny local footprint)
#
# Prerequisite: network access to data server (SSH 22 or SMB 445).
#
# Usage:
#   export REMOTE_PASS='your_windows_password'
#   bash scripts/setup_mount_only_data.sh try
#   bash scripts/setup_mount_only_data.sh mount
#   bash scripts/setup_mount_only_data.sh build    # convert on remote + symlink
#   bash scripts/setup_mount_only_data.sh umount
#
# Env:
#   REMOTE_CACHE=/mnt/remote_e/_paper_factor_cache   # written on remote E:
#   SKIP_MINUTE=1                                    # skip huge minute parquet

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOUNT_POINT="${MOUNT_POINT:-/mnt/remote_e}"
REMOTE_CACHE="${REMOTE_CACHE:-${MOUNT_POINT}/_paper_factor_cache}"
REMOTE_DEBUG="${REMOTE_DEBUG:-${MOUNT_POINT}/_paper_factor_cache_debug}"
LOCAL_FULL="${ROOT}/git_ignore_folder/factor_implementation_source_data"
LOCAL_DEBUG="${ROOT}/git_ignore_folder/factor_implementation_source_data_debug"
MOUNT_SCRIPT="${ROOT}/scripts/mount_remote_e_and_sync_data.sh"

cmd="${1:-try}"
shift || true

_link_data_dir() {
  local local_path="$1" remote_path="$2"
  mkdir -p "$(dirname "$local_path")"
  if [[ -L "$local_path" ]]; then
    rm -f "$local_path"
  elif [[ -d "$local_path" && ! -L "$local_path" ]]; then
    echo "ERROR: $local_path exists and is not a symlink."
    echo "Run: bash scripts/cleanup_local_heavy_data.sh --apply"
    exit 1
  fi
  ln -sf "$remote_path" "$local_path"
  echo "Linked: $local_path -> $remote_path"
}

_do_build() {
  if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Not mounted. Run: bash scripts/setup_mount_only_data.sh mount"
    exit 1
  fi
  mkdir -p "$REMOTE_CACHE" "$REMOTE_DEBUG"

  cd "$ROOT"
  source .venv/bin/activate
  export SKIP_MINUTE="${SKIP_MINUTE:-1}"
  export PAPER_FACTOR_DATA_ROOT="$REMOTE_CACHE"
  export PAPER_FACTOR_DATA_DEBUG_ROOT="$REMOTE_DEBUG"

  echo "==> Converting on remote mount (not on C:): $REMOTE_CACHE"
  python scripts/convert_remote_data.py "$MOUNT_POINT"
  python -m paper_factor_cli.main init

  _link_data_dir "$LOCAL_FULL" "$REMOTE_CACHE"
  _link_data_dir "$LOCAL_DEBUG" "$REMOTE_DEBUG"

  echo
  echo "==> Verify (reads from mount):"
  ls -lh "$LOCAL_FULL/daily_pv.h5"
  ls "$LOCAL_FULL/因子汇总.xlsx" 2>/dev/null || true
  echo
  echo "Add to .env (optional, explicit paths):"
  echo "  FACTOR_CoSTEER_data_folder=${LOCAL_FULL}"
  echo "  FACTOR_CoSTEER_data_folder_debug=${LOCAL_DEBUG}"
  echo
  echo "Before each run session, mount first:"
  echo "  bash scripts/setup_mount_only_data.sh mount"
  echo "Then:"
  echo "  python -m paper_factor_cli.main start"
}

case "$cmd" in
  try)
    bash "$MOUNT_SCRIPT" try
    ;;
  mount)
    if bash "$MOUNT_SCRIPT" mount; then
      :
    else
      echo "sshfs failed; trying SMB..."
      bash "$MOUNT_SCRIPT" mount-smb
    fi
    bash "$MOUNT_SCRIPT" explore
    ;;
  build)
    _do_build
    ;;
  umount)
    bash "$MOUNT_SCRIPT" umount
    ;;
  *)
    echo "Usage: try | mount | build | umount"
    exit 1
    ;;
esac
