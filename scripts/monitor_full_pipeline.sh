#!/usr/bin/env bash
# Quick status for run_full_pipeline.sh (WSL).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIFIED="${PAPER_FACTOR_UNIFIED_ROOT:-/mnt/remote_e/_paper_factor_unified}"
LOG="${ROOT}/log/full_pipeline.log"

echo "==> mount"; mountpoint /mnt/remote_e || echo "NOT MOUNTED"
echo "==> process"
pgrep -af "run_full_pipeline|unify_remote_factors|paper_factor_cli.main profile" || echo "(none)"
echo "==> counts"
find "${UNIFIED}/factor_outputs/fundamental" -name '*.parquet' 2>/dev/null | wc -l | xargs echo "fundamental parquet:"
find "${UNIFIED}/factor_outputs/literature" -name '*.meta.json' 2>/dev/null | wc -l | xargs echo "literature meta:"
find "${UNIFIED}/factor_profiles" -name '*.profile.json' 2>/dev/null | wc -l | xargs echo "profiles:"
echo "==> log tail"
tail -15 "${LOG}" 2>/dev/null || echo "no log yet"
