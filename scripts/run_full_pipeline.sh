#!/usr/bin/env bash
# Full remote unify + full profile evaluation (background-safe, logs to file).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT}/log"
LOG_FILE="${LOG_DIR}/full_pipeline.log"
mkdir -p "$LOG_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "========== $(date -Is) full pipeline start =========="
echo "PID=$$" > "${LOG_DIR}/full_pipeline.pid"

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

echo "==> Step 1/2: unify all (market skip if exists, full fundamental, literature, link)"
python scripts/unify_remote_factors.py market --skip-minute || true
python scripts/unify_remote_factors.py fundamental --force
python scripts/unify_remote_factors.py literature --force || true
python scripts/unify_remote_factors.py link --force

echo "==> unify counts:"
find "${PAPER_FACTOR_UNIFIED_ROOT}/factor_outputs/fundamental" -name '*.parquet' 2>/dev/null | wc -l | xargs echo "  fundamental parquet:"
find "${PAPER_FACTOR_UNIFIED_ROOT}/factor_outputs/literature" -name '*.meta.json' 2>/dev/null | wc -l | xargs echo "  literature meta:"

echo "==> Step 2/2: full profile (IC + Barra, overwrite)"
python -m paper_factor_cli.main profile --force

echo "==> profile count:"
find "${PAPER_FACTOR_UNIFIED_ROOT}/factor_profiles" -name '*.profile.json' 2>/dev/null | wc -l | xargs echo "  profiles:"
echo "========== $(date -Is) full pipeline done =========="
