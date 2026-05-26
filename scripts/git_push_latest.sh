#!/usr/bin/env bash
# Commit and push paper-factor changes to origin (your fork).
# Usage: bash scripts/git_push_latest.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "==> git status"
git status -sb

files=(
  paper_factor_cli/main.py
  rdagent/scenarios/qlib/developer/barra_analysis.py
  rdagent/scenarios/qlib/developer/barra_data.py
  rdagent/scenarios/qlib/developer/barra_attribution.py
  rdagent/app/qlib_rd_loop/factor_portfolio_analyze.py
  scripts/setup_barra_model.sh
  scripts/convert_remote_data.py
  scripts/mount_remote_e_and_sync_data.sh
  scripts/pull_smb_share.sh
  scripts/sync_todesk_e_drive.sh
  scripts/git_push_latest.sh
)

echo "==> staging"
for f in "${files[@]}"; do
  if [[ -f "$f" ]]; then
    git add -- "$f"
    echo "  + $f"
  fi
done

if git diff --cached --quiet; then
  echo "Nothing to commit (already up to date?)."
  exit 0
fi

git commit -m "$(cat <<'EOF'
Add full Barra return/risk attribution and post-start analyze hook.

- Barra exposure diagnostics plus factor/specific return decomposition
- Load factor returns, covariance, SPRET, SRISK from barra_model CSVs
- analyze CLI and automatic post-analyze after start
- Remote data mount/SMB helper scripts
EOF
)"

echo "==> push origin main"
git push -u origin main

echo "==> done"
git status -sb
git log -1 --oneline
