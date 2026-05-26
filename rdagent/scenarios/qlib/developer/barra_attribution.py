"""Full Barra return & risk attribution for factor-implied long-short portfolios."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rdagent.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
from rdagent.components.coder.factor_coder.eva_utils import _get_daily_label_from_data_folder
from rdagent.scenarios.qlib.developer.barra_analysis import (
    STYLE_FACTORS,
    _load_exposure_subset,
    _normalize_factor_series,
)
from rdagent.scenarios.qlib.developer.barra_data import (
    aligned_attribution_factors,
    factor_return_columns,
    get_barra_paths,
    load_covariance_for_dates,
    load_factor_returns,
    load_specific_return_subset,
    load_specific_risk_subset,
    split_style_industry,
)


def _build_long_short_weights(
    factor_series: pd.Series,
    *,
    top_frac: float = 0.2,
    bottom_frac: float = 0.2,
) -> pd.Series:
    """Dollar-neutral weights per day from factor ranks."""
    weights: list[pd.Series] = []
    for dt in factor_series.index.get_level_values("datetime").unique():
        slab = factor_series.loc[dt]
        if isinstance(slab, pd.DataFrame):
            slab = slab.iloc[:, 0]
        g = pd.to_numeric(slab, errors="coerce").dropna()
        if len(g) < 10:
            continue
        rank = g.rank(pct=True, method="average")
        top = rank >= (1.0 - top_frac)
        bot = rank <= bottom_frac
        n_top = int(top.sum())
        n_bot = int(bot.sum())
        if n_top == 0 or n_bot == 0:
            continue
        w = pd.Series(0.0, index=g.index, dtype=float)
        w.loc[top] = 0.5 / n_top
        w.loc[bot] = -0.5 / n_bot
        w.index = pd.MultiIndex.from_product([[dt], w.index], names=["datetime", "instrument"])
        weights.append(w)
    if not weights:
        return pd.Series(dtype=float)
    return pd.concat(weights).sort_index()


def _portfolio_exposure_by_day(
    weights: pd.Series,
    exposure: pd.DataFrame,
    factors: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for dt in weights.index.get_level_values("datetime").unique():
        w = weights.loc[dt]
        if isinstance(w, pd.DataFrame):
            w = w.iloc[:, 0]
        try:
            exp = exposure.loc[dt, factors]
        except KeyError:
            continue
        if isinstance(exp, pd.Series):
            continue
        aligned = exp.reindex(w.index).fillna(0.0)
        w_vec = w.reindex(aligned.index).fillna(0.0)
        if w_vec.abs().sum() <= 0:
            continue
        h = w_vec @ aligned
        row = {"datetime": pd.Timestamp(dt)}
        row.update({k: float(h[k]) for k in factors if k in h.index})
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).set_index("datetime").sort_index()
    return out


def analyze_factor_barra_attribution(
    factor_df: pd.DataFrame,
    *,
    barra_dir: Path | None = None,
    model: str = "trading",
    data_type: str = "All",
    top_frac: float = 0.2,
    bottom_frac: float = 0.2,
) -> dict[str, Any]:
    """
    Barra return decomposition:
      portfolio_return ≈ sum_k(h_k * f_k) + sum_i(w_i * SPRET_i) + residual

    Risk decomposition (relative shares):
      factor_risk ≈ h' F h , specific_risk ≈ sum_i (w_i * SRISK_i)^2
    """
    paths = get_barra_paths(barra_dir=barra_dir, model=model)
    for p in (paths.factor_return, paths.exposure, paths.specific_return):
        if not p.exists():
            return {
                "status": "unavailable",
                "reason": f"Missing Barra file: {p}",
                "barra_model": model,
            }

    factor_series = _normalize_factor_series(factor_df)
    secids = set(factor_series.index.get_level_values("instrument").astype(str))
    trade_dates = {
        pd.Timestamp(dt).strftime("%Y%m%d") for dt in factor_series.index.get_level_values("datetime").unique()
    }

    return_cols = factor_return_columns(paths.factor_return)
    exposure_raw = _load_exposure_subset(paths.exposure, secids, trade_dates)
    if exposure_raw.empty:
        return {
            "status": "unavailable",
            "reason": "No overlapping Barra exposure.",
            "barra_model": model,
        }

    factors = aligned_attribution_factors(list(exposure_raw.columns), return_cols)
    if not factors:
        return {
            "status": "unavailable",
            "reason": "No common factors between exposure and factor-return tables.",
            "barra_model": model,
        }

    exposure = exposure_raw[factors]
    style_factors, industry_factors = split_style_industry(factors)

    weights = _build_long_short_weights(
        factor_series,
        top_frac=top_frac,
        bottom_frac=bottom_frac,
    )
    if weights.empty:
        return {
            "status": "unavailable",
            "reason": "Could not build long-short weights from factor.",
            "barra_model": model,
        }

    h_by_day = _portfolio_exposure_by_day(weights, exposure, factors)
    if h_by_day.empty:
        return {
            "status": "unavailable",
            "reason": "Portfolio Barra exposures empty after alignment.",
            "barra_model": model,
        }

    f_returns = load_factor_returns(str(paths.factor_return))
    f_returns.index = f_returns.index.astype(str)
    f_returns = f_returns.reindex(columns=factors)

    spret = load_specific_return_subset(paths.specific_return, secids, trade_dates)
    srisk = load_specific_risk_subset(paths.specific_risk, secids, trade_dates)

    data_folder = (
        Path(FACTOR_COSTEER_SETTINGS.data_folder_debug)
        if data_type == "Debug"
        else Path(FACTOR_COSTEER_SETTINGS.data_folder)
    )
    label = _get_daily_label_from_data_folder(data_folder)

    daily_rows: list[dict[str, Any]] = []
    for dt in h_by_day.index:
        td = pd.Timestamp(dt).strftime("%Y%m%d")
        if td not in f_returns.index:
            continue
        h = h_by_day.loc[dt, factors].astype(float)
        f = f_returns.loc[td, factors].astype(float)
        factor_contrib = float((h * f).sum())

        style_contrib = float((h[style_factors] * f[style_factors]).sum()) if style_factors else 0.0
        industry_contrib = (
            float((h[industry_factors] * f[industry_factors]).sum()) if industry_factors else 0.0
        )

        try:
            w = weights.loc[dt]
            if isinstance(w, pd.DataFrame):
                w = w.iloc[:, 0]
        except KeyError:
            continue

        try:
            sp = spret.loc[dt].reindex(w.index)
            specific_contrib = float((w * sp).sum())
        except KeyError:
            specific_contrib = float("nan")

        try:
            lab = label.loc[dt].reindex(w.index)
            port_ret = float((w * lab).sum())
        except KeyError:
            port_ret = float("nan")

        explained = factor_contrib + (specific_contrib if pd.notna(specific_contrib) else 0.0)
        residual = (
            port_ret - explained if pd.notna(port_ret) and pd.notna(explained) else float("nan")
        )

        daily_rows.append(
            {
                "date": str(pd.Timestamp(dt).date()),
                "portfolio_return": port_ret,
                "factor_return_contrib": factor_contrib,
                "style_return_contrib": style_contrib,
                "industry_return_contrib": industry_contrib,
                "specific_return_contrib": specific_contrib,
                "residual_return": residual,
            }
        )

    if not daily_rows:
        return {
            "status": "unavailable",
            "reason": "No overlapping dates between portfolio, factor returns, and labels.",
            "barra_model": model,
        }

    daily = pd.DataFrame(daily_rows)
    attrib_dates = {pd.Timestamp(r["date"]).strftime("%Y%m%d") for r in daily_rows}
    cov_by_date = load_covariance_for_dates(paths.covariance, attrib_dates)

    # Risk attribution: average exposure, covariance on last available date in overlap
    h_mean = h_by_day[factors].mean()
    risk_date = sorted(cov_by_date.keys())[-1] if cov_by_date else None
    factor_risk = None
    specific_risk_var = None
    if risk_date and risk_date in cov_by_date:
        F = cov_by_date[risk_date].reindex(index=factors, columns=factors).fillna(0.0)
        h_vec = h_mean.reindex(factors).fillna(0.0).values
        factor_risk = float(h_vec @ F.values @ h_vec)

    # SRISK is typically annualized % — convert to decimal variance scale for relative split
    srisk_rows: list[float] = []
    for dt in h_by_day.index:
        try:
            w = weights.loc[dt]
            if isinstance(w, pd.DataFrame):
                w = w.iloc[:, 0]
            sk = srisk.loc[dt].reindex(w.index)
            srisk_rows.append(float(np.nansum((w.fillna(0.0).values ** 2) * (sk.fillna(0.0).values / 100.0) ** 2)))
        except KeyError:
            continue
    if srisk_rows:
        specific_risk_var = float(np.nanmean(srisk_rows))

    total_risk = None
    factor_risk_share = None
    specific_risk_share = None
    if factor_risk is not None and specific_risk_var is not None:
        total_risk = factor_risk + specific_risk_var
        if total_risk > 0:
            factor_risk_share = factor_risk / total_risk
            specific_risk_share = specific_risk_var / total_risk

    # Cumulative return attribution
    def _cum(col: str) -> float | None:
        if col not in daily.columns:
            return None
        s = pd.to_numeric(daily[col], errors="coerce").fillna(0.0)
        return float((1.0 + s).prod() - 1.0)

    factor_pnl_breakdown: dict[str, float] = {}
    for fac in factors:
        daily_fac: list[float] = []
        for dt in h_by_day.index:
            td = pd.Timestamp(dt).strftime("%Y%m%d")
            if td not in f_returns.index:
                continue
            daily_fac.append(float(h_by_day.loc[dt, fac] * f_returns.loc[td, fac]))
        if daily_fac:
            factor_pnl_breakdown[fac] = float(np.mean(daily_fac))

    top_factor_contribs = sorted(
        factor_pnl_breakdown.items(),
        key=lambda x: abs(x[1]),
        reverse=True,
    )[:10]

    return {
        "status": "ok",
        "barra_model": model,
        "attribution_days": len(daily),
        "factors_used": len(factors),
        "style_factor_count": len(style_factors),
        "industry_factor_count": len(industry_factors),
        "mean_daily_portfolio_return": float(pd.to_numeric(daily["portfolio_return"], errors="coerce").mean()),
        "mean_daily_factor_contrib": float(pd.to_numeric(daily["factor_return_contrib"], errors="coerce").mean()),
        "mean_daily_style_contrib": float(pd.to_numeric(daily["style_return_contrib"], errors="coerce").mean()),
        "mean_daily_industry_contrib": float(pd.to_numeric(daily["industry_return_contrib"], errors="coerce").mean()),
        "mean_daily_specific_contrib": float(pd.to_numeric(daily["specific_return_contrib"], errors="coerce").mean()),
        "mean_daily_residual": float(pd.to_numeric(daily["residual_return"], errors="coerce").mean()),
        "cumulative_portfolio_return": _cum("portfolio_return"),
        "cumulative_factor_contrib": _cum("factor_return_contrib"),
        "cumulative_specific_contrib": _cum("specific_return_contrib"),
        "cumulative_residual": _cum("residual_return"),
        "factor_contrib_share": (
            float(daily["factor_return_contrib"].sum() / daily["portfolio_return"].sum())
            if daily["portfolio_return"].abs().sum() > 1e-12
            else None
        ),
        "specific_contrib_share": (
            float(daily["specific_return_contrib"].sum() / daily["portfolio_return"].sum())
            if daily["portfolio_return"].abs().sum() > 1e-12
            else None
        ),
        "risk_attribution": {
            "covariance_date": risk_date,
            "factor_risk_hFh": factor_risk,
            "specific_risk_variance_proxy": specific_risk_var,
            "factor_risk_share": factor_risk_share,
            "specific_risk_share": specific_risk_share,
            "notes": (
                "Return: long-short portfolio from factor ranks; "
                "factor part = sum_k h_k(t)*f_k(t); specific = sum_i w_i(t)*SPRET_i(t). "
                "Risk: relative split using h_bar' F h_bar and sum w_i^2*(SRISK_i/100)^2."
            ),
        },
        "top_factor_return_contributors": [
            {"factor": k, "mean_daily_contrib": v} for k, v in top_factor_contribs
        ],
        "daily_attribution_sample": daily.head(5).to_dict(orient="records"),
    }


def attribution_summary_markdown(attrib: dict[str, Any]) -> str:
    if attrib.get("status") != "ok":
        return f"Barra attribution unavailable: {attrib.get('reason', 'unknown')}"
    risk = attrib.get("risk_attribution") or {}
    lines = [
        "## Barra return attribution (long-short portfolio)",
        f"- Days: {attrib.get('attribution_days')}",
        f"- Mean daily portfolio return: {attrib.get('mean_daily_portfolio_return')}",
        f"- Mean daily factor contrib: {attrib.get('mean_daily_factor_contrib')}",
        f"  - style: {attrib.get('mean_daily_style_contrib')}",
        f"  - industry: {attrib.get('mean_daily_industry_contrib')}",
        f"- Mean daily specific contrib: {attrib.get('mean_daily_specific_contrib')}",
        f"- Mean daily residual: {attrib.get('mean_daily_residual')}",
        f"- Cumulative portfolio return: {attrib.get('cumulative_portfolio_return')}",
        f"- Cumulative factor / specific / residual: "
        f"{attrib.get('cumulative_factor_contrib')} / "
        f"{attrib.get('cumulative_specific_contrib')} / "
        f"{attrib.get('cumulative_residual')}",
        "",
        "## Barra risk attribution (relative)",
        f"- Covariance date: {risk.get('covariance_date')}",
        f"- Factor risk share (h'Fh): {risk.get('factor_risk_share')}",
        f"- Specific risk share: {risk.get('specific_risk_share')}",
        "",
        "Top factor return contributors (mean daily):",
    ]
    for item in attrib.get("top_factor_return_contributors") or []:
        lines.append(f"- {item['factor']}: {item['mean_daily_contrib']}")
    return "\n".join(lines)
