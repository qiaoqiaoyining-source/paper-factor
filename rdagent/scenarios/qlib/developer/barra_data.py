"""Load Barra CSV bundles (exposure, factor returns, covariance, specific return/risk)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import pandas as pd

from rdagent.scenarios.qlib.developer.barra_analysis import (
    BARRA_MODEL_FILES,
    STYLE_FACTORS,
    resolve_barra_dir,
)  # noqa: F401  BARRA_MODEL_FILES used in get_barra_paths

_META_COLS = {"tradeDate", "updateTime", "factorID", "factorName"}


@dataclass(frozen=True)
class BarraModelPaths:
    exposure: Path
    factor_return: Path
    specific_return: Path
    specific_risk: Path
    covariance: Path


def get_barra_paths(*, barra_dir: Path | None = None, model: str = "trading") -> BarraModelPaths:
    base = resolve_barra_dir(barra_dir)
    files = BARRA_MODEL_FILES.get(model, BARRA_MODEL_FILES["trading"])
    return BarraModelPaths(
        exposure=base / files["exposure"],
        factor_return=base / files["factor_return"],
        specific_return=base / files["specific_return"],
        specific_risk=base / files["specific_risk"],
        covariance=base / files["covariance"],
    )


def factor_return_columns(path: Path) -> list[str]:
    header = pd.read_csv(path, nrows=0)
    return [c for c in header.columns if c not in _META_COLS]


@lru_cache(maxsize=4)
def load_factor_returns(path_str: str) -> pd.DataFrame:
    path = Path(path_str)
    df = pd.read_csv(path, low_memory=False)
    df["tradeDate"] = df["tradeDate"].astype(str)
    df = df.set_index("tradeDate").sort_index()
    cols = [c for c in df.columns if c not in _META_COLS]
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[cols]


def load_covariance_for_dates(path: Path, trade_dates: Iterable[str]) -> dict[str, pd.DataFrame]:
    """Return {tradeDate: covariance matrix DataFrame indexed by factorName}."""
    needed = set(trade_dates)
    mats: dict[str, pd.DataFrame] = {}
    header = pd.read_csv(path, nrows=0)
    cov_factor_cols = [c for c in header.columns if c not in _META_COLS]
    usecols = ["tradeDate", "factorName", *cov_factor_cols]

    for chunk in pd.read_csv(path, usecols=usecols, chunksize=100_000, low_memory=False):
        chunk["tradeDate"] = chunk["tradeDate"].astype(str)
        chunk = chunk[chunk["tradeDate"].isin(needed)]
        if chunk.empty:
            continue
        for dt, day in chunk.groupby("tradeDate"):
            if dt in mats:
                continue
            names = day["factorName"].astype(str).tolist()
            mat = day.set_index("factorName")[cov_factor_cols].apply(pd.to_numeric, errors="coerce")
            mat = mat.reindex(index=names, columns=names)
            mats[dt] = mat
        if len(mats) >= len(needed):
            break
    return mats


def load_specific_return_subset(path: Path, secids: set[str], trade_dates: set[str]) -> pd.Series:
    if not path.exists():
        return pd.Series(dtype=float)
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path,
        usecols=["secID", "tradeDate", "SPRET"],
        chunksize=250_000,
        low_memory=False,
    ):
        chunk["tradeDate"] = chunk["tradeDate"].astype(str)
        chunk["secID"] = chunk["secID"].astype(str)
        filt = chunk[chunk["secID"].isin(secids) & chunk["tradeDate"].isin(trade_dates)]
        if not filt.empty:
            chunks.append(filt)
    if not chunks:
        return pd.Series(dtype=float)
    out = pd.concat(chunks, ignore_index=True)
    out["datetime"] = pd.to_datetime(out["tradeDate"], format="%Y%m%d", errors="coerce")
    out = out.dropna(subset=["datetime"])
    out = out.rename(columns={"secID": "instrument"})
    series = pd.to_numeric(out["SPRET"], errors="coerce")
    series.index = pd.MultiIndex.from_arrays(
        [out["datetime"], out["instrument"].astype(str)],
        names=["datetime", "instrument"],
    )
    return series.sort_index()


def load_specific_risk_subset(path: Path, secids: set[str], trade_dates: set[str]) -> pd.Series:
    if not path.exists():
        return pd.Series(dtype=float)
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path,
        usecols=["secID", "tradeDate", "SRISK"],
        chunksize=250_000,
        low_memory=False,
    ):
        chunk["tradeDate"] = chunk["tradeDate"].astype(str)
        chunk["secID"] = chunk["secID"].astype(str)
        filt = chunk[chunk["secID"].isin(secids) & chunk["tradeDate"].isin(trade_dates)]
        if not filt.empty:
            chunks.append(filt)
    if not chunks:
        return pd.Series(dtype=float)
    out = pd.concat(chunks, ignore_index=True)
    out["datetime"] = pd.to_datetime(out["tradeDate"], format="%Y%m%d", errors="coerce")
    out = out.dropna(subset=["datetime"])
    out = out.rename(columns={"secID": "instrument"})
    series = pd.to_numeric(out["SRISK"], errors="coerce")
    series.index = pd.MultiIndex.from_arrays(
        [out["datetime"], out["instrument"].astype(str)],
        names=["datetime", "instrument"],
    )
    return series.sort_index()


def aligned_attribution_factors(exposure_cols: list[str], return_cols: list[str]) -> list[str]:
    """Factors present in both exposure and factor-return tables."""
    exp = set(exposure_cols)
    return [c for c in return_cols if c in exp]


def split_style_industry(factors: list[str]) -> tuple[list[str], list[str]]:
    style = [f for f in factors if f in STYLE_FACTORS]
    industry = [f for f in factors if f not in STYLE_FACTORS and f != "COUNTRY"]
    return style, industry
