#!/usr/bin/env bash
set -euo pipefail
cd /root/paper-factor
source .venv/bin/activate
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a

SPEC="/mnt/remote_e/_paper_factor_unified/strategy_knowledge/paper_strategies/基本面动量FIR策略.yaml"
LOG="log/p0_backtest_run.log"
mkdir -p log

echo "========== $(date -Is) alignment check ==========" | tee "$LOG"
python <<'PY' | tee -a "$LOG"
from rdagent.scenarios.qlib.strategy.data import load_market_panel, load_forward_returns, build_factor_matrix, apply_universe_mask
from rdagent.scenarios.qlib.strategy.spec import load_strategy_spec
from rdagent.scenarios.qlib.strategy.profile_loader import select_factors
from pathlib import Path

spec_path = Path("/mnt/remote_e/_paper_factor_unified/strategy_knowledge/paper_strategies/基本面动量FIR策略.yaml")
spec = load_strategy_spec(spec_path)
factors = select_factors(spec)
market = load_market_panel(spec.data_type)
label = load_forward_returns(spec.data_type)
panel = apply_universe_mask(build_factor_matrix(factors), spec, market)
aligned = label.reindex(panel.index)
print("method", spec.method, "n_factors", len(factors))
print("aligned nn", int(aligned.notna().sum()), "of", len(aligned))
print("common index", len(panel.index.intersection(label.index)))
PY

echo "========== $(date -Is) backtest ==========" | tee -a "$LOG"
python -m factor_strategy_agent_cli.main strategy --spec "$SPEC" --no-sync-toolbox 2>&1 | tee -a "$LOG"

echo "========== $(date -Is) done ==========" | tee -a "$LOG"
