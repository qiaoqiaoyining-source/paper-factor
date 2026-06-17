#!/usr/bin/env bash
# Resume after fundamental finished: literature + link + full profile.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT}/log"
LOG_FILE="${LOG_DIR}/full_pipeline_resume.log"
mkdir -p "$LOG_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "========== $(date -Is) resume pipeline start =========="

if ! mountpoint -q /mnt/remote_e 2>/dev/null; then
  echo "ERROR: /mnt/remote_e not mounted"
  exit 1
fi

cd "$ROOT"
source .venv/bin/activate

export PAPER_FACTOR_REMOTE_ROOT="${PAPER_FACTOR_REMOTE_ROOT:-/mnt/remote_e}"
export PAPER_FACTOR_UNIFIED_ROOT="${PAPER_FACTOR_UNIFIED_ROOT:-/mnt/remote_e/_paper_factor_unified}"
export PAPER_FACTOR_OUTPUTS_DIR="${PAPER_FACTOR_OUTPUTS_DIR:-${ROOT}/git_ignore_folder/factor_outputs}"
export SKIP_MINUTE=1
export PYTHONUNBUFFERED=1

echo "==> literature index"
python scripts/unify_remote_factors.py literature --force

echo "==> link symlinks"
python scripts/unify_remote_factors.py link --force

echo "==> full profile (IC + Barra)"
python -m paper_factor_cli.main profile --force

echo "==> counts:"
find "${PAPER_FACTOR_UNIFIED_ROOT}/factor_outputs/fundamental" -name '*.parquet' 2>/dev/null | wc -l | xargs echo "  fundamental parquet:"
find "${PAPER_FACTOR_UNIFIED_ROOT}/factor_outputs/literature" -name '*.meta.json' 2>/dev/null | wc -l | xargs echo "  literature meta:"
find "${PAPER_FACTOR_UNIFIED_ROOT}/factor_profiles" -name '*.profile.json' 2>/dev/null | wc -l | xargs echo "  profiles:"
echo "========== $(date -Is) resume pipeline done =========="
