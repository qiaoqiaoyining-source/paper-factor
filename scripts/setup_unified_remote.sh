#!/usr/bin/env bash
# One-shot: unify remote E: data on the mount, link into paper-factor (no C: copy).
#
# Prerequisite: sshfs mounted at /mnt/remote_e
#
# Usage:
#   bash scripts/setup_unified_remote.sh
#   bash scripts/setup_unified_remote.sh --execute-code
#   bash scripts/setup_unified_remote.sh --fundamental-limit 5

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXEC_CODE=0
FUND_LIMIT=""
FORCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute-code) EXEC_CODE=1 ;;
    --fundamental-limit) FUND_LIMIT="$2"; shift ;;
    --force) FORCE="--force" ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
  shift
done

if ! mountpoint -q /mnt/remote_e 2>/dev/null; then
  echo "ERROR: /mnt/remote_e not mounted. Run sshfs first."
  exit 1
fi

cd "$ROOT"
source .venv/bin/activate

export PAPER_FACTOR_REMOTE_ROOT="${PAPER_FACTOR_REMOTE_ROOT:-/mnt/remote_e}"
export PAPER_FACTOR_UNIFIED_ROOT="${PAPER_FACTOR_UNIFIED_ROOT:-/mnt/remote_e/_paper_factor_unified}"
export SKIP_MINUTE=1

LIMIT_ARG=()
if [[ -n "$FUND_LIMIT" ]]; then
  LIMIT_ARG=(--limit "$FUND_LIMIT")
fi

python scripts/unify_remote_factors.py market --skip-minute ${FORCE}
python scripts/unify_remote_factors.py fundamental "${LIMIT_ARG[@]}" ${FORCE}

if [[ "$EXEC_CODE" == "1" ]]; then
  python scripts/unify_remote_factors.py literature --execute-code ${FORCE}
else
  python scripts/unify_remote_factors.py literature ${FORCE} || true
fi

python scripts/unify_remote_factors.py link --force

echo
echo "==> Unified layout on E:"
echo "    ${PAPER_FACTOR_UNIFIED_ROOT}/factor_implementation_source_data/daily_pv.h5"
echo "    ${PAPER_FACTOR_UNIFIED_ROOT}/factor_outputs/"
echo
echo "==> Linked into project (symlinks, ~0 C: usage):"
ls -la "$ROOT/git_ignore_folder/factor_implementation_source_data" || true
ls -la "$ROOT/git_ignore_folder/factor_outputs/unified_remote" || true
echo
echo "Next:"
echo "  python -m paper_factor_cli.main profile --limit 5"
echo "  python -m paper_factor_cli.main profile"
