"""Method 1: rule-based method + factor selection from toolbox."""

from __future__ import annotations

from typing import Any

from rdagent.scenarios.qlib.strategy.backtest import meets_constraints, score_against_spec
from rdagent.scenarios.qlib.strategy.spec import StrategySpec


def select_best_method(
    sweep_results: list[dict[str, Any]],
    spec: StrategySpec,
) -> dict[str, Any]:
    """Pick best method from sweep by score + constraint satisfaction."""
    if not sweep_results:
        return {"status": "empty", "reason": "no sweep results"}

    ranked = sorted(
        sweep_results,
        key=lambda r: score_against_spec(r.get("metrics") or {}, spec),
        reverse=True,
    )
    best = ranked[0]
    feasible = [r for r in ranked if meets_constraints(r.get("metrics") or {}, spec)]

    rationale: list[str] = []
    rationale.append(f"Style preset: {spec.style} — {spec.style_preset().get('description', '')}")
    rationale.append(f"Evaluated {len(sweep_results)} methods on {best.get('n_factors')} factors.")
    if feasible:
        rationale.append(f"{len(feasible)} methods meet your constraints; selected top scorer.")
    else:
        rationale.append("No method fully meets constraints; selected best compromise on validation.")

    top_factors = best.get("factor_weights") or {}
    top_f = sorted(top_factors.items(), key=lambda x: x[1], reverse=True)[:8]
    if top_f:
        rationale.append("Top factor weights: " + ", ".join(f"{k}:{v:.3f}" for k, v in top_f))

    return {
        "status": "ok",
        "selected_method": best.get("method_id"),
        "selected_result": best,
        "alternatives": ranked[1:4],
        "feasible_count": len(feasible),
        "rationale": rationale,
        "user_spec": spec.to_dict(),
    }
