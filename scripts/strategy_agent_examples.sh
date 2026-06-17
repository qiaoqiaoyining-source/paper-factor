#!/usr/bin/env bash
# Strategy agent quick start (WSL). Requires .env LLM keys and mounted E:.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

UNIFIED="${PAPER_FACTOR_UNIFIED_ROOT:-/mnt/remote_e/_paper_factor_unified}"
export PAPER_FACTOR_UNIFIED_ROOT="$UNIFIED"

echo "=== 1) 从需求创建策略并自动优化 ==="
echo "python -m paper_factor_cli.main strategy-agent create \\"
echo "  --goal '小市值多空，控制换手，net Sharpe 尽量为正' \\"
echo "  --template strategy_toolbox/specs/small_cap.yaml \\"
echo "  --max-loops 5"
echo ""
echo "=== 2) 已有 spec，直接优化 ==="
echo "python -m paper_factor_cli.main strategy-agent optimize \\"
echo "  --spec strategy_toolbox/specs/small_cap.yaml \\"
echo "  --goal '换手太高，net Sharpe 为负' \\"
echo "  --max-loops 5"
echo ""
echo "=== 3) 看完 optimization_summary.md 后继续提建议 ==="
echo "python -m paper_factor_cli.main strategy-agent continue \\"
echo "  --session ${UNIFIED}/strategy_runs/<your_agent_dir> \\"
echo "  --feedback '回撤还是偏大，加强平滑，减少因子数' \\"
echo "  --max-loops 3"
echo ""
echo "=== 4) 查看 session 状态 ==="
echo "python -m paper_factor_cli.main strategy-agent status --session ${UNIFIED}/strategy_runs/<your_agent_dir>"
