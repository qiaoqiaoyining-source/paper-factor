"""Rule-based strategy diagnostics for the agent loop (flags, not fixes)."""

from __future__ import annotations

from typing import Any

from rdagent.scenarios.qlib.strategy.spec import StrategySpec


ISSUE_CODES = {
    "HIGH_TURNOVER",
    "HIGH_DRAWDOWN",
    "COST_DRAG",
    "GROSS_POSITIVE_NET_NEGATIVE",
    "CONSTRAINT_VIOLATION",
    "LOW_SHARPE",
    "LOW_RETURN",
    "FACTOR_WEIGHT_CONCENTRATION",
}


def _selected_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    sel = payload.get("selection") or {}
    if sel.get("selected_result"):
        return sel["selected_result"]
    results = sel.get("results") or payload.get("sweep_results") or []
    ok = [r for r in results if r.get("metrics", {}).get("status") == "ok"]
    if not ok:
        return results[0] if results else None
    return max(ok, key=lambda r: r.get("score") or -1e9)


def diagnose_strategy_run(payload: dict[str, Any], spec: StrategySpec) -> dict[str, Any]:
    """Build structured diagnosis from a strategy_result.json payload."""
    result = _selected_result(payload) or {}
    metrics = result.get("metrics") or {}
    issues: list[dict[str, Any]] = []

    turnover = metrics.get("turnover_mean")
    mdd = metrics.get("max_drawdown")
    sharpe = metrics.get("sharpe_annualized")
    ann = metrics.get("annualized_return_approx")
    gross_sharpe = metrics.get("gross_sharpe_annualized")
    gross_cum = metrics.get("gross_cumulative_return")
    cum = metrics.get("cumulative_return")
    cost_drag = metrics.get("cost_drag_total")
    meets = result.get("meets_constraints", False)

    if spec.max_turnover is not None and turnover is not None and turnover > spec.max_turnover:
        issues.append(
            {
                "code": "HIGH_TURNOVER",
                "severity": "high",
                "detail": f"turnover_mean={turnover:.3f} > max_turnover={spec.max_turnover}",
                "metrics": {"turnover_mean": turnover, "max_turnover": spec.max_turnover},
            }
        )
    elif turnover is not None and turnover > 1.0:
        issues.append(
            {
                "code": "HIGH_TURNOVER",
                "severity": "medium",
                "detail": f"turnover_mean={turnover:.3f} is very high (>1.0 daily proxy)",
                "metrics": {"turnover_mean": turnover},
            }
        )

    if spec.max_drawdown is not None and mdd is not None and mdd < -abs(spec.max_drawdown):
        issues.append(
            {
                "code": "HIGH_DRAWDOWN",
                "severity": "high",
                "detail": f"max_drawdown={mdd:.3f} worse than limit {-abs(spec.max_drawdown):.3f}",
                "metrics": {"max_drawdown": mdd, "max_drawdown_limit": spec.max_drawdown},
            }
        )

    if spec.min_sharpe is not None and sharpe is not None and sharpe < spec.min_sharpe:
        issues.append(
            {
                "code": "LOW_SHARPE",
                "severity": "high",
                "detail": f"sharpe={sharpe:.3f} < min_sharpe={spec.min_sharpe}",
                "metrics": {"sharpe_annualized": sharpe, "min_sharpe": spec.min_sharpe},
            }
        )

    if spec.min_annual_return is not None and ann is not None and ann < spec.min_annual_return:
        issues.append(
            {
                "code": "LOW_RETURN",
                "severity": "medium",
                "detail": f"annualized_return={ann:.3f} < min={spec.min_annual_return}",
                "metrics": {"annualized_return_approx": ann},
            }
        )

    if gross_cum is not None and cum is not None and gross_cum > 0.05 and cum < 0:
        issues.append(
            {
                "code": "GROSS_POSITIVE_NET_NEGATIVE",
                "severity": "high",
                "detail": f"gross_cum={gross_cum:.3f} but net_cum={cum:.3f}; trading costs dominate",
                "metrics": {
                    "gross_cumulative_return": gross_cum,
                    "cumulative_return": cum,
                    "cost_drag_total": cost_drag,
                },
            }
        )

    if cost_drag is not None and cost_drag > 0.1:
        issues.append(
            {
                "code": "COST_DRAG",
                "severity": "medium",
                "detail": f"cost_drag_total={cost_drag:.3f} from turnover × one_way_cost",
                "metrics": {
                    "cost_drag_total": cost_drag,
                    "friction_cost_drag_mean": metrics.get("friction_cost_drag_mean"),
                    "one_way_cost": spec.one_way_cost,
                },
            }
        )

    if not meets and metrics.get("status") == "ok":
        issues.append(
            {
                "code": "CONSTRAINT_VIOLATION",
                "severity": "high",
                "detail": "Strategy metrics do not meet spec constraints",
                "metrics": {"meets_constraints": False},
            }
        )

    weights = result.get("factor_weights") or {}
    if isinstance(weights, dict) and weights:
        vals = [abs(float(v)) for v in weights.values() if v is not None]
        if vals:
            total = sum(vals) or 1.0
            top_share = max(vals) / total
            if top_share > 0.45:
                top_name = max(weights, key=lambda k: abs(float(weights[k] or 0)))
                issues.append(
                    {
                        "code": "FACTOR_WEIGHT_CONCENTRATION",
                        "severity": "medium",
                        "detail": f"factor '{top_name}' weight share {top_share:.1%} — signal may be unstable",
                        "metrics": {"top_factor": top_name, "top_weight_share": top_share},
                    }
                )

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda x: severity_rank.get(x.get("severity", "low"), 9))

    return {
        "status": "ok" if metrics.get("status") == "ok" else "empty",
        "method_id": result.get("method_id") or (payload.get("selection") or {}).get("selected_method"),
        "meets_constraints": meets,
        "metrics_summary": {
            "sharpe_annualized": sharpe,
            "gross_sharpe_annualized": gross_sharpe,
            "annualized_return_approx": ann,
            "max_drawdown": mdd,
            "turnover_mean": turnover,
            "cumulative_return": cum,
            "gross_cumulative_return": gross_cum,
            "cost_drag_total": cost_drag,
            "score": result.get("score"),
        },
        "issues": issues,
        "n_issues": len(issues),
        "factor_weights": weights,
    }
