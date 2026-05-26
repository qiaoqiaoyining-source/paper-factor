#!/usr/bin/env bash
# Copy ToDesk-downloaded E: drive dump into /mnt/remote_e and run init conversion.
#
# 1) Use ToDesk file transfer to copy entire E:\ to Windows, e.g.:
#      C:\Users\DELL\Downloads\remote_e\
# 2) Run:
#      bash scripts/sync_todesk_e_drive.sh
#
# Expected under SOURCE:
#   market_daily_daily_new/
#   market_minute_daily_new/
#   基本面因子/
#   dailyData.parquet
#   数据说明.txt

set -euo pipefail

SOURCE="${1:-/mnt/c/Users/DELL/Downloads/remote_e}"
MOUNT_POINT="${MOUNT_POINT:-/mnt/remote_e}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d "$SOURCE" ]]; then
  echo "Source not found: $SOURCE"
  echo "Usage: bash scripts/sync_todesk_e_drive.sh [/mnt/c/Users/DELL/Downloads/remote_e]"
  exit 1
fi

sudo mkdir -p "$MOUNT_POINT"
echo "==> Sync $SOURCE -> $MOUNT_POINT"
rsync -a --info=progress2 "$SOURCE/" "$MOUNT_POINT/" || cp -a "$SOURCE/." "$MOUNT_POINT/"

echo "==> Remote E layout:"
ls -la "$MOUNT_POINT"

cd "$ROOT"
source .venv/bin/activate
python scripts/convert_remote_data.py "$MOUNT_POINT"
python -m paper_factor_cli.main init

echo "==> Done. Verify:"
ls -lh "$ROOT/git_ignore_folder/factor_implementation_source_data/daily_pv.h5"
