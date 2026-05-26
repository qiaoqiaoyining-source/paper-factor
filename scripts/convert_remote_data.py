#!/usr/bin/env python3
"""Convert company E: drive dumps under /mnt/remote_e into paper-factor H5 data."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = Path("/mnt/remote_e")
DEST_FULL = ROOT / "git_ignore_folder" / "factor_implementation_source_data"
DEST_DEBUG = ROOT / "git_ignore_folder" / "factor_implementation_source_data_debug"
FULL_DAYS = 252
FULL_INSTRUMENTS = 5000
DEBUG_DAYS = 60
DEBUG_INSTRUMENTS = 200

DAILY_COLUMN_MAP = {
    "open": "$open",
    "high": "$high",
    "low": "$low",
    "close": "$close",
    "pre_close": "$pre_close",
    "change": "$change",
    "pct_chg": "$pct_chg",
    "vol": "$volume",
    "volume": "$volume",
    "amount": "$amount",
    "adj_factor": "$factor",
    "turnover_rate": "$turnover_rate",
    "turnover_rate_f": "$turnover_rate_f",
    "volume_ratio": "$volume_ratio",
    "pe": "$pe",
    "pe_ttm": "$pe_ttm",
    "pb": "$pb",
    "ps": "$ps",
    "ps_ttm": "$ps_ttm",
    "dv_ratio": "$dv_ratio",
    "dv_ttm": "$dv_ttm",
    "total_share": "$total_share",
    "float_share": "$float_share",
    "free_share": "$free_share",
    "total_mv": "$total_mv",
    "circ_mv": "$circ_mv",
}

MINUTE_COLUMN_MAP = {
    "open": "$open",
    "high": "$high",
    "low": "$low",
    "close": "$close",
    "pre_close": "$pre_close",
    "change": "$change",
    "pct_chg": "$pct_chg",
    "vol": "$volume",
    "volume": "$volume",
    "amount": "$amount",
    "vwap": "$vwap",
}


def _collect_parquet_files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() == ".parquet":
        return [path]
    if not path.is_dir():
        return []
    return sorted(path.rglob("*.parquet"))


def _read_parquet_bundle(path: Path) -> pd.DataFrame:
    files = _collect_parquet_files(path)
    if not files:
        raise FileNotFoundError(f"No parquet under {path}")
    frames = [pd.read_parquet(f) for f in files]
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def _detect_date_col(columns: list[str]) -> str:
    for name in ("trade_date", "date", "datetime", "trading_date"):
        if name in columns:
            return name
    raise ValueError(f"Cannot detect date column in {columns[:30]}")


def _detect_instrument_col(columns: list[str]) -> str:
    for name in ("ts_code", "instrument", "symbol", "code", "stock_code"):
        if name in columns:
            return name
    raise ValueError(f"Cannot detect instrument column in {columns[:30]}")


def _to_factor_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    date_col = _detect_date_col(list(out.columns))
    inst_col = _detect_instrument_col(list(out.columns))
    out["datetime"] = pd.to_datetime(out[date_col].astype(str), errors="coerce")
    out["instrument"] = out[inst_col].astype(str)
    drop_cols = {c for c in ("ts_code", "trade_date", "trade_time", "date", date_col, inst_col) if c in out.columns}
    out = out.drop(columns=list(drop_cols), errors="ignore")
    out = out.dropna(subset=["datetime", "instrument"])
    return out.set_index(["datetime", "instrument"]).sort_index()


def _rename_ohlcv(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    rename = {k: v for k, v in mapping.items() if k in df.columns}
    out = df.rename(columns=rename)
    for col in out.columns:
        if col not in {"datetime", "instrument"} and not str(col).startswith("$"):
            out = out.rename(columns={col: f"${col}"})
    if "$factor" not in out.columns:
        out["$factor"] = 1.0
    if "$turnover_rate" not in out.columns and "$volume" in out.columns:
        volume = pd.to_numeric(out["$volume"], errors="coerce").fillna(0.0)
        scale = volume.groupby(level="datetime").transform("median").replace(0, np.nan)
        out["$turnover_rate"] = (volume / scale).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if "$turnover" not in out.columns and "$turnover_rate" in out.columns:
        out["$turnover"] = out["$turnover_rate"]
    return out


def _load_daily(remote_root: Path) -> pd.DataFrame:
    candidates = [
        remote_root / "market_daily_daily_new",
        remote_root / "dailyData.parquet",
    ]
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            raw = _read_parquet_bundle(candidate)
            indexed = _to_factor_index(raw)
            return _rename_ohlcv(indexed, DAILY_COLUMN_MAP)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"Failed to load daily data from {remote_root}") from last_error


def _load_minute(remote_root: Path) -> pd.DataFrame:
    candidates = [
        remote_root / "market_minute_daily_new",
    ]
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            raw = _read_parquet_bundle(candidate)
            indexed = _to_factor_index(raw)
            return _rename_ohlcv(indexed, MINUTE_COLUMN_MAP)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"Failed to load minute data from {remote_root}") from last_error


def _subset(df: pd.DataFrame, max_days: int, max_instruments: int) -> pd.DataFrame:
    dates = df.index.get_level_values("datetime").unique().sort_values()
    instruments = list(dict.fromkeys(df.index.get_level_values("instrument")))
    chosen_dates = dates[-max_days:]
    chosen_instruments = instruments[:max_instruments]
    out = df.loc[pd.IndexSlice[chosen_dates, chosen_instruments], :].sort_index()
    if out.empty:
        raise ValueError("Subset daily/minute frame is empty after trimming.")
    return out


def _write_h5(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_hdf(path, key="data")


def _copy_fundamental_dir(remote_root: Path, dest: Path) -> None:
    src = remote_root / "基本面因子"
    if not src.exists():
        return
    target = dest / "基本面因子"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src, target)


def main() -> int:
    remote_root = Path(sys.argv[1]) if len(sys.argv) > 1 else REMOTE_ROOT
    if not remote_root.exists():
        print(f"Remote root not found: {remote_root}", file=sys.stderr)
        return 1

    print(f"Loading daily from {remote_root} ...")
    daily_full = _load_daily(remote_root)
    print(f"Daily rows: {len(daily_full):,}; instruments: {daily_full.index.get_level_values('instrument').nunique():,}")

    minute_full: pd.DataFrame | None = None
    try:
        print(f"Loading minute from {remote_root} ...")
        minute_full = _load_minute(remote_root)
        print(f"Minute rows: {len(minute_full):,}")
    except Exception as exc:  # noqa: BLE001
        print(f"Minute data skipped: {exc}")

    daily_debug = _subset(daily_full, DEBUG_DAYS, DEBUG_INSTRUMENTS)
    minute_debug = _subset(minute_full, DEBUG_DAYS, DEBUG_INSTRUMENTS) if minute_full is not None else None

    _write_h5(daily_full, DEST_FULL / "daily_pv.h5")
    _write_h5(daily_debug, DEST_DEBUG / "daily_pv.h5")
    if minute_full is not None:
        _write_h5(minute_full, DEST_FULL / "minute_pv.h5")
        if minute_debug is not None:
            _write_h5(minute_debug, DEST_DEBUG / "minute_pv.h5")

    _copy_fundamental_dir(remote_root, DEST_FULL)
    meta = {
        "source": str(remote_root),
        "converted_at": datetime.now(timezone.utc).isoformat(),
        "daily_rows": int(len(daily_full)),
        "daily_instruments": int(daily_full.index.get_level_values("instrument").nunique()),
        "minute_rows": int(len(minute_full)) if minute_full is not None else 0,
    }
    (DEST_FULL / "remote_data_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    readme = remote_root / "数据说明.txt"
    if readme.exists():
        shutil.copy(readme, DEST_FULL / "数据说明.txt")

    print("Wrote:")
    print(f"  {DEST_FULL / 'daily_pv.h5'}")
    if minute_full is not None:
        print(f"  {DEST_FULL / 'minute_pv.h5'}")
    print(f"  {DEST_DEBUG / 'daily_pv.h5'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
