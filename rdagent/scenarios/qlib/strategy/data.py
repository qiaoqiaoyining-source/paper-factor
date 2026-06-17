"""Market data, labels, universe filters for strategy backtest."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from rdagent.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
from rdagent.components.coder.factor_coder.eva_utils import _get_daily_label_from_data_folder
from rdagent.scenarios.qlib.strategy.spec import StrategySpec


def normalize_instrument(code: str) -> str:
    """Unify market/label/factor codes to padded exchange suffix (e.g. 1 → 000001.SZ)."""
    s = str(code).strip()
    if not s or s.lower() in {"nan", "none", "trade_date", "date"}:
        return s
    if "." in s and len(s) >= 8:
        parts = s.rsplit(".", 1)
        if len(parts) == 2 and parts[1].upper() in {"SZ", "SH", "BJ", "XSHE", "XSHG"}:
            suffix = parts[1].upper()
            if suffix == "XSHE":
                suffix = "SZ"
            elif suffix == "XSHG":
                suffix = "SH"
            digits = re.sub(r"\D", "", parts[0]).zfill(6)
            return f"{digits}.{suffix}"
        return s.upper()
    digits = re.sub(r"\D", "", s)
    if not digits:
        return s
    digits = digits.zfill(6)
    if digits.startswith(("60", "68", "90")):
        return f"{digits}.SH"
    if digits.startswith(("00", "30", "20", "43", "83", "87", "92")):
        return f"{digits}.SZ"
    if digits.startswith(("8", "4")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def normalize_multiindex_instruments(index: pd.MultiIndex) -> pd.MultiIndex:
    if list(index.names) != ["datetime", "instrument"]:
        return index
    inst = pd.Index(normalize_instrument(x) for x in index.get_level_values("instrument"))
    return pd.MultiIndex.from_arrays([index.get_level_values("datetime"), inst], names=index.names)


def _normalize_series_index(s: pd.Series) -> pd.Series:
    if isinstance(s.index, pd.MultiIndex):
        s = s.copy()
        s.index = normalize_multiindex_instruments(s.index)
    return s.sort_index()


def _normalize_frame_index(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.index, pd.MultiIndex):
        df = df.copy()
        df.index = normalize_multiindex_instruments(df.index)
    return df.sort_index()


def resolve_data_folder(data_type: str = "All") -> Path:
    if data_type == "Debug":
        return Path(FACTOR_COSTEER_SETTINGS.data_folder_debug)
    return Path(FACTOR_COSTEER_SETTINGS.data_folder)


def load_market_panel(data_type: str = "All") -> pd.DataFrame:
    folder = resolve_data_folder(data_type)
    path = folder / "daily_pv.h5"
    return _normalize_frame_index(pd.read_hdf(path, key="data"))


def load_forward_returns(data_type: str = "All") -> pd.Series:
    folder = resolve_data_folder(data_type)
    return _normalize_series_index(_get_daily_label_from_data_folder(folder))


def load_factor_series(parquet_path: str | Path, factor_name: str | None = None) -> pd.Series:
    df = pd.read_parquet(parquet_path)
    if isinstance(df, pd.Series):
        s = pd.to_numeric(df, errors="coerce")
    else:
        col = factor_name if factor_name and factor_name in df.columns else df.columns[0]
        s = pd.to_numeric(df[col], errors="coerce")
    s.name = str(factor_name or s.name or "factor")
    if not isinstance(s.index, pd.MultiIndex):
        raise ValueError(f"Factor must use MultiIndex (datetime, instrument): {parquet_path}")
    return _normalize_series_index(s)


def build_factor_matrix(factors: list[dict], *, max_dates: int | None = None) -> pd.DataFrame:
    """Wide panel: MultiIndex (datetime, instrument) x factor columns."""
    frames: list[pd.Series] = []
    for f in factors:
        name = str(f["factor_name"])
        s = load_factor_series(f["parquet_path"], name)
        s = s.rename(name)
        frames.append(s)
    if not frames:
        raise ValueError("No factor series loaded")
    panel = pd.concat(frames, axis=1)
    if max_dates:
        dates = panel.index.get_level_values("datetime").unique().sort_values()
        if len(dates) > max_dates:
            keep = dates[-max_dates:]
            panel = panel.loc[pd.IndexSlice[keep, :], :]
    return panel.sort_index()


def apply_universe_mask(panel: pd.DataFrame, spec: StrategySpec, market: pd.DataFrame) -> pd.DataFrame:
    preset = spec.style_preset()
    universe = preset.get("universe", "all")
    if universe == "all":
        return panel

    mv_col = next((c for c in ("$total_mv", "$circ_mv", "$market_cap") if c in market.columns), None)
    dates = panel.index.get_level_values("datetime").unique().sort_values()
    keep_idx: list[tuple] = []

    for dt in dates:
        try:
            day_panel = panel.loc[dt]
            day_mkt = market.loc[dt]
        except KeyError:
            continue
        if isinstance(day_panel, pd.Series):
            continue
        inst = day_panel.index.intersection(day_mkt.index)
        if len(inst) == 0:
            continue
        if mv_col and universe in {"small_cap_bottom30", "large_cap_top300"}:
            mv = pd.to_numeric(day_mkt.loc[inst, mv_col], errors="coerce")
            valid = mv.dropna()
            if valid.empty:
                keep_idx.extend([(dt, i) for i in inst])
                continue
            if universe == "small_cap_bottom30":
                cutoff = valid.quantile(0.30)
                chosen = valid[valid <= cutoff].index
            else:
                chosen = valid.nlargest(min(300, len(valid))).index
            keep_idx.extend([(dt, i) for i in chosen])
        else:
            keep_idx.extend([(dt, i) for i in inst])

    if not keep_idx:
        return panel
    idx = pd.MultiIndex.from_tuples(keep_idx, names=["datetime", "instrument"])
    return panel.reindex(idx)


def cs_zscore(panel: pd.DataFrame) -> pd.DataFrame:
    def _z(g: pd.DataFrame) -> pd.DataFrame:
        return g.sub(g.mean()).div(g.std().replace(0, np.nan))

    return panel.groupby(level="datetime", group_keys=False).apply(_z)


def train_test_split_dates(dates: pd.DatetimeIndex, train_frac: float) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    dates = dates.sort_values()
    n = len(dates)
    split = max(1, int(n * train_frac))
    return dates[:split], dates[split:]
