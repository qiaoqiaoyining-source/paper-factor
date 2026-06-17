#!/usr/bin/env bash
set -euo pipefail
cd /root/paper-factor
source .venv/bin/activate
LOG="log/strategy_ingest_full_run.log"
mkdir -p log
echo "========== $(date -Is) full strategy-ingest start ==========" | tee "$LOG"
python -m factor_strategy_agent_cli.main strategy-ingest \
  --report-file "papers/inbox/基本面动量策略在A股实证.pdf" \
  --run 2>&1 | tee -a "$LOG"
echo "========== $(date -Is) done exit=${PIPESTATUS[0]} ==========" | tee -a "$LOG"
exit "${PIPESTATUS[0]}"
