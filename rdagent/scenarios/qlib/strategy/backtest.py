"""Portfolio backtest metrics from combined signal."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from rdagent.scenarios.qlib.strategy.trading_friction import (
    TradingFrictionConfig,
    signal_to_long_short_returns,
)

__all__ = [
    "TradingFrictionConfig",
    "signal_to_long_short_returns",
    "compute_performance_metrics",
    "meets_constraints",
    "score_against_spec",
]


def compute_performance_metrics(
    daily_returns: pd.Series,
    *,
    turnover_mean: float | None = None,
    gross_daily: pd.Series | None = None,
    friction_meta: dict[str, Any] | None = None,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    r = pd.to_numeric(daily_returns, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if r.empty:
        return {"status": "empty", "n_days": 0}

    mean = float(r.mean())
    std = float(r.std(ddof=1)) if len(r) > 1 else float("nan")
    sharpe = float(mean / std * math.sqrt(periods_per_year)) if std and std > 0 else float("nan")
    wealth = float(np.prod(1.0 + r.values) - 1.0)
    n = len(r)
    ann = float((1.0 + wealth) ** (periods_per_year / n) - 1.0) if n > 0 and wealth > -1 else float("nan")
    cum = (1.0 + r).cumprod()
    mdd = float((cum / cum.cummax() - 1.0).min())

    out: dict[str, Any] = {
        "status": "ok",
        "n_days": int(n),
        "daily_mean": mean,
        "sharpe_annualized": sharpe,
        "cumulative_return": wealth,
        "annualized_return_approx": ann,
        "max_drawdown": mdd,
        "turnover_mean": turnover_mean,
    }

    if gross_daily is not None and not gross_daily.empty:
        g = pd.to_numeric(gross_daily, errors="coerce").dropna()
        if not g.empty:
            g_wealth = float(np.prod(1.0 + g.values) - 1.0)
            out["gross_cumulative_return"] = g_wealth
            out["gross_sharpe_annualized"] = (
                float(g.mean() / g.std(ddof=1) * math.sqrt(periods_per_year)) if g.std() > 0 else None
            )
            out["cost_drag_total"] = g_wealth - wealth

    if friction_meta:
        out.update({f"friction_{k}": v for k, v in friction_meta.items() if k != "friction_note"})
        if friction_meta.get("friction_note"):
            out["friction_note"] = friction_meta["friction_note"]

    return out


def meets_constraints(metrics: dict[str, Any], spec) -> bool:
    if metrics.get("status") != "ok":
        return False
    if spec.min_sharpe is not None and (metrics.get("sharpe_annualized") or -999) < spec.min_sharpe:
        return False
    if spec.min_annual_return is not None and (metrics.get("annualized_return_approx") or -999) < spec.min_annual_return:
        return False
    if spec.max_drawdown is not None and (metrics.get("max_drawdown") or 0) < -abs(spec.max_drawdown):
        return False
    if spec.max_turnover is not None and (metrics.get("turnover_mean") or 999) > spec.max_turnover:
        return False
    return True


def score_against_spec(metrics: dict[str, Any], spec) -> float:
    if metrics.get("status") != "ok":
        return -1e9
    sharpe = float(metrics.get("sharpe_annualized") or 0.0)
    ann = float(metrics.get("annualized_return_approx") or 0.0)
    mdd = abs(float(metrics.get("max_drawdown") or 0.0))
    to = float(metrics.get("turnover_mean") or 0.5)
    score = sharpe * 2.0 + ann - mdd * 2.0 - to * 0.5
    if meets_constraints(metrics, spec):
        score += 5.0
    return score
