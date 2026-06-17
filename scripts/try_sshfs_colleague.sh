#!/usr/bin/env bash
# One-shot: colleague's sshfs recipe (pc@192.168.1.254:/E:) with password 123456.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REMOTE_USER="${REMOTE_USER:-pc}"
export REMOTE_HOST="${REMOTE_HOST:-192.168.1.13}"
export REMOTE_PATH="${REMOTE_PATH:-/E:}"
export REMOTE_PASS="${REMOTE_PASS:-123456}"
export MOUNT_POINT="${MOUNT_POINT:-/mnt/remote_e}"
exec bash "${ROOT}/scripts/mount_remote_e_and_sync_data.sh" try
