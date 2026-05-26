#!/usr/bin/env bash
# Mount company remote E: drive and copy factor data into paper-factor.
#
# Usage:
#   bash scripts/mount_remote_e_and_sync_data.sh check     # ping + port scan (no mount)
#   bash scripts/mount_remote_e_and_sync_data.sh mount     # sshfs (needs SSH port 22)
#   bash scripts/mount_remote_e_and_sync_data.sh list-shares  # smbclient -L (needs REMOTE_PASS)
#   bash scripts/mount_remote_e_and_sync_data.sh explore
#   bash scripts/mount_remote_e_and_sync_data.sh sync [DIR]
#   bash scripts/mount_remote_e_and_sync_data.sh umount
#
# Env (override defaults):
#   REMOTE_USER=pc  REMOTE_HOST=192.168.1.254
#   REMOTE_PATH=/E:          # sshfs path
#   REMOTE_DOMAIN=           # optional, e.g. WORKGROUP or machine name
#   REMOTE_PASS=...         # optional; if unset you will be prompted (sshfs / smb)
#   MOUNT_POINT=/mnt/remote_e

set -euo pipefail

REMOTE_USER="${REMOTE_USER:-pc}"
REMOTE_HOST="${REMOTE_HOST:-192.168.1.254}"
REMOTE_PATH="${REMOTE_PATH:-/E:}"
SMB_SHARE="${SMB_SHARE:-}"
REMOTE_DOMAIN="${REMOTE_DOMAIN:-}"
MOUNT_POINT="${MOUNT_POINT:-/mnt/remote_e}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_FULL="${ROOT}/git_ignore_folder/factor_implementation_source_data"
DEST_DEBUG="${ROOT}/git_ignore_folder/factor_implementation_source_data_debug"

cmd="${1:-check}"
shift || true

_port_open() {
  local host="$1" port="$2"
  timeout 3 bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" 2>/dev/null
}

_install_sshfs() {
  if ! command -v sshfs >/dev/null 2>&1; then
    echo "==> Installing sshfs..."
    sudo apt-get update -qq
    sudo apt-get install -y sshfs fuse3
  fi
}

_install_cifs() {
  if ! command -v mount.cifs >/dev/null 2>&1; then
    echo "==> Installing cifs-utils..."
    sudo apt-get update -qq
    sudo apt-get install -y cifs-utils
  fi
}

_do_check() {
  echo "==> Target: ${REMOTE_USER}@${REMOTE_HOST}"
  echo "==> Project data destination:"
  echo "    ${DEST_FULL}/"
  echo
  if ping -c 2 -W 2 "$REMOTE_HOST" >/dev/null 2>&1; then
    echo "OK  ping ${REMOTE_HOST}"
    ping -c 2 "$REMOTE_HOST" | tail -2
  else
    echo "FAIL ping ${REMOTE_HOST} — not on same network or server offline."
    exit 1
  fi
  echo
  for p in 22 445 139; do
    if _port_open "$REMOTE_HOST" "$p"; then
      echo "OK  port $p is OPEN"
    else
      echo "--  port $p closed/filtered"
    fi
  done
  echo
  if _port_open "$REMOTE_HOST" 22; then
    echo "sshfs should work: bash scripts/mount_remote_e_and_sync_data.sh mount"
  elif _port_open "$REMOTE_HOST" 445; then
    echo "SSH unavailable; try SMB: bash scripts/mount_remote_e_and_sync_data.sh mount-smb"
    echo "  export REMOTE_PASS='your_windows_password'   # or type when prompted"
  else
    echo "Neither SSH (22) nor SMB (445) is reachable."
    echo "Ask colleague to on the data server:"
    echo "  1) Power on + same LAN; 2) Enable OpenSSH Server OR share E: for SMB"
    echo "Or get the correct IP if 192.168.1.254 is not the data server."
  fi
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo
    echo "Already mounted at ${MOUNT_POINT}"
    ls -la "$MOUNT_POINT" 2>/dev/null | head -10
  fi
}

_do_mount_sshfs() {
  _install_sshfs
  if ! _port_open "$REMOTE_HOST" 22; then
    echo "ERROR: port 22 not open on ${REMOTE_HOST}. sshfs cannot work."
    echo "Run: bash scripts/mount_remote_e_and_sync_data.sh check"
    echo "Try: bash scripts/mount_remote_e_and_sync_data.sh mount-smb"
    exit 1
  fi
  sudo mkdir -p "$MOUNT_POINT"
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Already mounted: $MOUNT_POINT"
    return 0
  fi
  echo "==> sshfs ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH} -> ${MOUNT_POINT}"
  echo "    Type the Windows user password for '${REMOTE_USER}' when prompted (input is hidden)."
  echo "    If it hangs >30s with no prompt, press Ctrl+C and run 'check' again."
  sshfs "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}" "$MOUNT_POINT" \
    -o reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,follow_symlinks
  echo "==> Mount OK: ls ${MOUNT_POINT}"
}

_install_smbclient() {
  if ! command -v smbclient >/dev/null 2>&1; then
    echo "==> Installing smbclient..."
    sudo apt-get update -qq
    sudo apt-get install -y smbclient
  fi
}

_read_remote_pass() {
  if [[ -n "${REMOTE_PASS:-}" ]]; then
    return 0
  fi
  echo "Enter Windows password for user '${REMOTE_USER}':"
  read -rs REMOTE_PASS
  echo
}

_smb_user_variants() {
  local u="$REMOTE_USER"
  if [[ -n "$REMOTE_DOMAIN" ]]; then
    echo "${REMOTE_DOMAIN}/${u}"
  fi
  echo "$u"
  echo ".\\${u}"
  echo "WORKGROUP\\${u}"
}

_do_list_shares() {
  _install_smbclient
  _read_remote_pass
  local user out=1 u
  for u in $(_smb_user_variants); do
    echo "==> smbclient -L //${REMOTE_HOST} -U '${u}'"
    if smbclient -L "//${REMOTE_HOST}" -U "${u}%${REMOTE_PASS}" -m SMB3 2>&1; then
      out=0
    fi
    echo
  done
  if [[ "$out" -ne 0 ]]; then
    echo "Could not list shares (Permission denied / logon failure)."
    echo "123456 may be ToDesk password, not Windows login password — confirm with colleague."
    echo "Also ask colleague to enable OpenSSH Server (port 22) so sshfs works."
  fi
}

_do_mount_smb() {
  _install_cifs
  if ! _port_open "$REMOTE_HOST" 445; then
    echo "ERROR: port 445 not open. SMB mount cannot work."
    exit 1
  fi
  sudo mkdir -p "$MOUNT_POINT"
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Already mounted: $MOUNT_POINT"
    return 0
  fi
  _read_remote_pass
  local shares=()
  if [[ -n "$SMB_SHARE" ]]; then
    shares+=("$SMB_SHARE")
  else
    shares+=(E$ E data factor factor_implementation_source_data)
  fi
  local ok=0 share u cred vers
  for u in $(_smb_user_variants); do
    cred="$(mktemp)"
    chmod 600 "$cred"
    printf 'username=%s\npassword=%s\n' "$u" "$REMOTE_PASS" >"$cred"
    for share in "${shares[@]}"; do
      for vers in 3.0 2.1; do
        echo "==> Trying //${REMOTE_HOST}/${share} user=${u} vers=${vers}"
        if sudo mount -t cifs "//${REMOTE_HOST}/${share}" "$MOUNT_POINT" \
          -o "credentials=${cred},uid=$(id -u),gid=$(id -g),iocharset=utf8,file_mode=0644,dir_mode=0755,vers=${vers},sec=ntlmssp"; then
          ok=1
          rm -f "$cred"
          echo "==> SMB mount OK: ls ${MOUNT_POINT}"
          return 0
        fi
        sudo umount "$MOUNT_POINT" 2>/dev/null || true
      done
    done
    rm -f "$cred"
  done
  echo "SMB mount failed (Permission denied)."
  echo "Run: bash scripts/mount_remote_e_and_sync_data.sh list-shares"
  echo "Colleague sshfs needs OpenSSH on port 22 — currently closed; ask them to enable it."
  exit 1
}

_do_umount() {
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    fusermount -u "$MOUNT_POINT" 2>/dev/null || sudo umount "$MOUNT_POINT" 2>/dev/null || true
    echo "Unmounted ${MOUNT_POINT}"
  else
    echo "Not mounted: ${MOUNT_POINT}"
  fi
}

_do_explore() {
  if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Not mounted. Run mount or mount-smb first."
    exit 1
  fi
  echo "==> Top level of ${MOUNT_POINT}"
  ls -la "$MOUNT_POINT" | head -40
  echo
  echo "==> Looking for daily_pv.h5 / factor_implementation_source_data (maxdepth 6)..."
  find "$MOUNT_POINT" -maxdepth 6 \( \
    -iname 'daily_pv.h5' -o \
    -iname 'factor_implementation_source_data' -o \
    -iname 'factor_implementation_source_data_debug' \
    \) 2>/dev/null | head -30
  echo
  echo "==> Other .h5 files (first 20)..."
  find "$MOUNT_POINT" -maxdepth 6 -iname '*.h5' 2>/dev/null | head -20
}

_do_sync() {
  local src="${1:-}"
  if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Not mounted. Run mount or mount-smb first."
    exit 1
  fi
  if [[ -z "$src" ]]; then
    local candidates=()
    while IFS= read -r line; do
      candidates+=("$line")
    done < <(find "$MOUNT_POINT" -maxdepth 6 -type d -name 'factor_implementation_source_data' 2>/dev/null | head -5)
    if [[ ${#candidates[@]} -eq 0 ]]; then
      while IFS= read -r line; do
        candidates+=("$(dirname "$line")")
      done < <(find "$MOUNT_POINT" -maxdepth 6 -type f -name 'daily_pv.h5' 2>/dev/null | head -3)
    fi
    if [[ ${#candidates[@]} -eq 0 ]]; then
      echo "Could not auto-detect data folder under ${MOUNT_POINT}."
      echo "Run explore first, then:"
      echo "  bash scripts/mount_remote_e_and_sync_data.sh sync /mnt/remote_e/YOUR/PATH"
      exit 1
    fi
    src="${candidates[0]}"
    echo "Auto-selected source: $src"
  fi
  if [[ -f "$src" && "$(basename "$src")" == "daily_pv.h5" ]]; then
    src="$(dirname "$src")"
  fi
  if [[ ! -d "$src" ]]; then
    echo "Source not found: $src"
    exit 1
  fi
  mkdir -p "$DEST_FULL" "$DEST_DEBUG"
  echo "==> Copying from $src -> $DEST_FULL"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --info=progress2 "${src}/" "${DEST_FULL}/"
  else
    cp -a "${src}/." "${DEST_FULL}/"
  fi
  if [[ -d "${src%/}/../factor_implementation_source_data_debug" ]]; then
    rsync -a "${src%/}/../factor_implementation_source_data_debug/" "${DEST_DEBUG}/" 2>/dev/null || true
  elif [[ -f "${DEST_FULL}/daily_pv.h5" && ! -f "${DEST_DEBUG}/daily_pv.h5" ]]; then
    echo "==> No debug folder on remote; copying daily_pv.h5 to debug dir."
    cp -f "${DEST_FULL}/daily_pv.h5" "${DEST_DEBUG}/daily_pv.h5"
  fi
  echo "==> Done. Verify:"
  ls -lh "${DEST_FULL}/daily_pv.h5" 2>/dev/null || echo "WARNING: daily_pv.h5 missing after sync"
  echo "Next: cd ${ROOT} && source .venv/bin/activate && python -m paper_factor_cli.main init"
}

case "$cmd" in
  check) _do_check ;;
  mount) _do_mount_sshfs ;;
  mount-smb) _do_mount_smb ;;
  list-shares) _do_list_shares ;;
  umount) _do_umount ;;
  explore) _do_explore ;;
  sync) _do_sync "$@" ;;
  *)
    echo "Usage: check | mount | mount-smb | list-shares | explore | sync [DIR] | umount"
    exit 1
    ;;
esac
