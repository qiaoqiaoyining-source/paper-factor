#!/usr/bin/env bash
# Download a Windows SMB share without CIFS mount (when mount.cifs returns Permission denied).
#
# Usage:
#   export REMOTE_PASS='123456'
#   bash scripts/pull_smb_share.sh list
#   bash scripts/pull_smb_share.sh ls D
#   bash scripts/pull_smb_share.sh pull D /path/on/share /mnt/remote_e
#
# Env: REMOTE_USER=pc  REMOTE_HOST=192.168.1.254

set -euo pipefail

REMOTE_USER="${REMOTE_USER:-pc}"
REMOTE_HOST="${REMOTE_HOST:-192.168.1.254}"
REMOTE_PASS="${REMOTE_PASS:-}"

cmd="${1:-list}"
shift || true

_install() {
  command -v smbclient >/dev/null 2>&1 || { sudo apt-get update -qq && sudo apt-get install -y smbclient; }
}

_auth() {
  if [[ -z "$REMOTE_PASS" ]]; then
    echo "Set REMOTE_PASS first, e.g. export REMOTE_PASS='123456'"
    exit 1
  fi
  SMB_AUTH="${REMOTE_USER}%${REMOTE_PASS}"
}

_smb() {
  smbclient "//${REMOTE_HOST}/$1" -U "$SMB_AUTH" -m SMB3 "$@"
}

case "$cmd" in
  list)
    _install
    _auth
    smbclient -L "//${REMOTE_HOST}" -U "$SMB_AUTH" -m SMB3
    ;;
  ls)
    share="${1:?share name required, e.g. D or 文件备份}"
    _install
    _auth
    _smb "$share" -c 'ls'
    ;;
  pull)
    share="${1:?share}"
    remote_path="${2:-/}"
    local_dir="${3:-/mnt/remote_e}"
    _install
    _auth
    mkdir -p "$local_dir"
    echo "==> Download //$REMOTE_HOST/$share:$remote_path -> $local_dir"
    _smb "$share" -c "prompt OFF; recurse ON; cd \"${remote_path}\"; mget *" -D "$local_dir" || true
    echo "==> Done. Contents:"
    ls -la "$local_dir" | head -30
    ;;
  *)
    echo "Usage: list | ls SHARE | pull SHARE [REMOTE_PATH] [LOCAL_DIR]"
    exit 1
    ;;
esac
