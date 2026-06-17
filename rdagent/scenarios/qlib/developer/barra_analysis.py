"""Barra style / industry exposure analysis for custom alpha factors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rdagent.scenarios.qlib.developer.barra_instrument_map import (
    factor_instrument_to_barra_secid,
    normalize_trade_date,
)

ROOT = Path.cwd()
DEFAULT_BARRA_DIR = ROOT / "git_ignore_folder" / "barra_model"

STYLE_FACTORS = [
    "BETA",
    "MOMENTUM",
    "SIZE",
    "EARNYILD",
    "RESVOL",
    "GROWTH",
    "BTOP",
    "LEVERAGE",
    "LIQUIDTY",
    "MIDCAP",
    "DIVYILD",
    "EARNQLTY",
    "EARNVAR",
    "INVSQLTY",
    "LTREVRSL",
    "PROFIT",
    "ANALSENTI",
    "INDMOM",
    "SEASON",
    "STREVRSL",
]

BARRA_MODEL_FILES = {
    "trading": {
        "exposure": "因子暴露表(Trading Model).csv",
        "factor_return": "因子收益率表(Trading Model).csv",
        "specific_return": "特质收益率表(Trading Model).csv",
        "specific_risk": "特质风险表(Trading Model).csv",
        "covariance": "风险因子协方差矩阵表(Trading Model).csv",
    },
    "long_term_stable": {
        "exposure": "因子暴露表(Long-Term Model).csv",
        "factor_return": "因子收益率表(Long-Term Model).csv",
        "specific_return": "特质收益率表(Long-Term Model).csv",
        "specific_risk": "特质风险表(Long Term Model-Stable).csv",
        "covariance": "风险因子协方差矩阵表(Long Term Model-Stable).csv",
    },
}


def resolve_barra_dir(barra_dir: Path | None = None) -> Path:
    import os

    raw = os.environ.get("PAPER_FACTOR_BARRA_DIR", "").strip()
    if barra_dir is not None:
        return Path(barra_dir)
    if raw:
        return Path(raw)
    return DEFAULT_BARRA_DIR


def list_barra_models(barra_dir: Path | None = None) -> dict[str, dict[str, str]]:
    base = resolve_barra_dir(barra_dir)
    out: dict[str, dict[str, str]] = {}
    for model, files in BARRA_MODEL_FILES.items():
        out[model] = {}
        for key, name in files.items():
            path = base / name
            out[model][key] = str(path) if path.exists() else ""
    return out


def _instrument_to_secid(instrument: str) -> str:
    text = str(instrument).strip().upper()
    if "." not in text:
        return text
    code, suffix = text.rsplit(".", 1)
    if suffix in {"SZ", "XSHE"}:
        return f"{code}.XSHE"
    if suffix in {"SH", "XSHG"}:
        return f"{code}.XSHG"
    return text


def _normalize_factor_series(factor_df: pd.DataFrame) -> pd.Series:
    if isinstance(factor_df, pd.Series):
        series = pd.to_numeric(factor_df, errors="coerce")
    else:
        series = pd.to_numeric(factor_df.iloc[:, 0], errors="coerce")
    if not isinstance(series.index, pd.MultiIndex):
        raise ValueError("Factor dataframe must use MultiIndex [datetime, instrument].")
    names = [str(n).lower() for n in series.index.names]
    if "datetime" not in names or "instrument" not in names:
        raise ValueError(f"Unexpected factor index names: {series.index.names}")
    series = series.copy()
    series.index = series.index.set_names(["datetime", "instrument"])
    dt = pd.to_datetime(series.index.get_level_values("datetime"))
    inst = series.index.get_level_values("instrument").astype(str).map(factor_instrument_to_barra_secid)
    series.index = pd.MultiIndex.from_arrays([dt, inst], names=["datetime", "instrument"])
    series.name = "factor"
    return series.sort_index()


def _load_exposure_subset(
    exposure_path: Path,
    secids: set[str],
    trade_dates: set[str],
) -> pd.DataFrame:
    if not exposure_path.exists():
        raise FileNotFoundError(f"Barra exposure file not found: {exposure_path}")
    usecols = ["secID", "tradeDate", *STYLE_FACTORS]
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(exposure_path, usecols=usecols, chunksize=250_000, low_memory=False):
        chunk["tradeDate"] = chunk["tradeDate"].map(normalize_trade_date)
        chunk["secID"] = chunk["secID"].astype(str)
        filtered = chunk[chunk["secID"].isin(secids) & chunk["tradeDate"].isin(trade_dates)]
        if not filtered.empty:
            chunks.append(filtered)
    if not chunks:
        return pd.DataFrame(columns=usecols)
    out = pd.concat(chunks, ignore_index=True)
    out["datetime"] = pd.to_datetime(out["tradeDate"], format="%Y%m%d", errors="coerce")
    out = out.dropna(subset=["datetime"])
    out = out.rename(columns={"secID": "instrument"})
    out = out.set_index(["datetime", "instrument"]).sort_index()
    for col in STYLE_FACTORS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out[STYLE_FACTORS]


def _daily_ols(y: pd.Series, x: pd.DataFrame) -> dict[str, Any] | None:
    mask = y.notna()
    for col in x.columns:
        mask &= x[col].notna()
    if mask.sum() < max(20, len(x.columns) + 5):
        return None
    yy = y[mask].astype(float).values
    xx = x.loc[mask].astype(float).values
    xx = np.column_stack([np.ones(len(xx)), xx])
    try:
        coef, _, _, _ = np.linalg.lstsq(xx, yy, rcond=None)
    except np.linalg.LinAlgError:
        return None
    pred = xx @ coef
    ss_res = float(np.sum((yy - pred) ** 2))
    ss_tot = float(np.sum((yy - yy.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    betas = {col: float(coef[i + 1]) for i, col in enumerate(x.columns)}
    return {"r2": float(r2), "betas": betas, "n": int(mask.sum())}


def analyze_factor_barra_exposure(
    factor_df: pd.DataFrame,
    *,
    barra_dir: Path | None = None,
    model: str = "trading",
    top_frac: float = 0.2,
    bottom_frac: float = 0.2,
) -> dict[str, Any]:
    """Cross-sectional Barra style regression + long-short exposure profile."""
    base = resolve_barra_dir(barra_dir)
    files = BARRA_MODEL_FILES.get(model, BARRA_MODEL_FILES["trading"])
    exposure_path = base / files["exposure"]
    factor_series = _normalize_factor_series(factor_df)
    secids = set(factor_series.index.get_level_values("instrument").astype(str))
    trade_dates = {
        normalize_trade_date(dt) for dt in factor_series.index.get_level_values("datetime").unique()
    }
    trade_dates = {d for d in trade_dates if d}
    exposure = _load_exposure_subset(exposure_path, secids, trade_dates)
    if exposure.empty:
        sample_secids = sorted(secids)[:5]
        sample_dates = sorted(trade_dates)[:3] + sorted(trade_dates)[-3:]
        return {
            "status": "unavailable",
            "reason": f"No overlapping Barra exposure rows for model={model}.",
            "barra_model": model,
            "exposure_path": str(exposure_path),
            "factor_secid_samples": sample_secids,
            "factor_date_samples": sample_dates,
            "n_factor_secids": len(secids),
            "n_factor_dates": len(trade_dates),
        }

    merged = pd.concat([factor_series, exposure], axis=1, join="inner").dropna(subset=["factor"])
    if merged.empty:
        return {
            "status": "unavailable",
            "reason": "Factor values did not align with Barra exposure after instrument mapping.",
            "barra_model": model,
        }

    daily_stats: list[dict[str, Any]] = []
    ls_exposures: list[pd.Series] = []
    dates = merged.index.get_level_values("datetime").unique().sort_values()
    for dt in dates:
        slab = merged.loc[dt]
        if isinstance(slab, pd.Series):
            continue
        g = slab.dropna(subset=["factor", *STYLE_FACTORS])
        if len(g) < max(30, len(STYLE_FACTORS) + 5):
            continue
        reg = _daily_ols(g["factor"], g[STYLE_FACTORS])
        if reg is not None:
            daily_stats.append({"datetime": str(dt.date()), **reg})

        if len(g) >= 10:
            rank = g["factor"].rank(pct=True, method="average")
            top = g.loc[rank >= (1.0 - top_frac), STYLE_FACTORS].mean()
            bot = g.loc[rank <= bottom_frac, STYLE_FACTORS].mean()
            ls_exposures.append((top - bot).rename(str(dt.date())))

    beta_acc: dict[str, list[float]] = {col: [] for col in STYLE_FACTORS}
    r2_list: list[float] = []
    for item in daily_stats:
        r2_list.append(float(item["r2"]))
        for col, val in item["betas"].items():
            beta_acc[col].append(float(val))

    style_beta_mean = {col: float(np.mean(vals)) if vals else None for col, vals in beta_acc.items()}
    style_beta_abs_mean = {
        col: float(np.mean(np.abs(vals))) if vals else None for col, vals in beta_acc.items()
    }
    ls_profile = (
        pd.DataFrame(ls_exposures).mean(axis=1).to_dict()
        if ls_exposures
        else {col: None for col in STYLE_FACTORS}
    )

    dominant = sorted(
        ((k, v) for k, v in style_beta_abs_mean.items() if v is not None),
        key=lambda x: abs(x[1]),
        reverse=True,
    )[:5]

    return {
        "status": "ok",
        "barra_model": model,
        "exposure_path": str(exposure_path),
        "regression_days": len(daily_stats),
        "mean_r2": float(np.mean(r2_list)) if r2_list else None,
        "median_r2": float(np.median(r2_list)) if r2_list else None,
        "style_beta_mean": style_beta_mean,
        "style_beta_abs_mean": style_beta_abs_mean,
        "long_short_style_exposure": {k: _safe(v) for k, v in ls_profile.items()},
        "dominant_style_loadings": [{"style": k, "abs_mean_beta": _safe(v)} for k, v in dominant],
        "notes": (
            "Daily cross-sectional OLS: factor ~ Barra style exposures. "
            "long_short_style_exposure = mean(style|top)-mean(style|bottom) portfolio proxy."
        ),
    }


def _safe(value: Any) -> float | None:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(val) or np.isinf(val):
        return None
    return val


def barra_summary_markdown(barra: dict[str, Any]) -> str:
    if barra.get("status") != "ok":
        return f"Barra analysis unavailable: {barra.get('reason', 'unknown')}"
    lines = [
        f"Barra model: {barra.get('barra_model')}",
        f"Regression days: {barra.get('regression_days')}",
        f"Mean R²: {barra.get('mean_r2')}",
        "",
        "Top style loadings (|beta| mean):",
    ]
    for item in barra.get("dominant_style_loadings") or []:
        lines.append(f"- {item['style']}: {item['abs_mean_beta']}")
    lines.append("")
    lines.append("Long-short style exposure (top-bottom):")
    for style in STYLE_FACTORS[:8]:
        val = (barra.get("long_short_style_exposure") or {}).get(style)
        if val is not None:
            lines.append(f"- {style}: {val:.4f}")
    return "\n".join(lines)


def save_barra_sidecar(path: Path, payload: dict[str, Any]) -> Path:
    out = path.with_suffix(".barra.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def analyze_factor_barra_full(
    factor_df: pd.DataFrame,
    *,
    barra_dir: Path | None = None,
    model: str = "trading",
    data_type: str = "All",
    top_frac: float = 0.2,
    bottom_frac: float = 0.2,
) -> dict[str, Any]:
    """Style exposure diagnostics + full return/risk Barra attribution."""
    from rdagent.scenarios.qlib.developer.barra_attribution import (
        analyze_factor_barra_attribution,
        attribution_summary_markdown,
    )

    exposure_diag = analyze_factor_barra_exposure(
        factor_df,
        barra_dir=barra_dir,
        model=model,
        top_frac=top_frac,
        bottom_frac=bottom_frac,
    )
    return_attrib = analyze_factor_barra_attribution(
        factor_df,
        barra_dir=barra_dir,
        model=model,
        data_type=data_type,
        top_frac=top_frac,
        bottom_frac=bottom_frac,
    )
    return {
        "status": "ok" if exposure_diag.get("status") == "ok" or return_attrib.get("status") == "ok" else "partial",
        "barra_model": model,
        "exposure_diagnostics": exposure_diag,
        "return_risk_attribution": return_attrib,
        "summary_markdown": "\n\n".join(
            [
                barra_summary_markdown(exposure_diag),
                attribution_summary_markdown(return_attrib),
            ]
        ),
    }
