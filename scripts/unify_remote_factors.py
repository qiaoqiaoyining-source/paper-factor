#!/usr/bin/env python3
"""
Unify remote E: drive factor sources into paper-factor layout on the mount (not C:).

Sources:
  - /mnt/remote_e/market_daily_daily_new  -> daily_pv.h5 (for IC labels)
  - /mnt/remote_e/基本面因子/**/*.csv       -> factor parquet + meta.json
  - /mnt/remote_e/paper_factors/**/*.meta.json (+ optional .code.py execution)

Output (default on remote E:, zero C: usage after symlinks):
  {UNIFIED_ROOT}/
    factor_implementation_source_data/daily_pv.h5
    factor_implementation_source_data_debug/daily_pv.h5
    factor_outputs/fundamental/{category}/{name}.parquet|.meta.json
    factor_outputs/literature/{report}/{name}.parquet|.meta.json
    catalog.json

Usage:
  python scripts/unify_remote_factors.py --help
  python scripts/unify_remote_factors.py all
  python scripts/unify_remote_factors.py market --skip-minute
  python scripts/unify_remote_factors.py fundamental --limit 3
  python scripts/unify_remote_factors.py literature --execute-code
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REMOTE_ROOT = Path(os.environ.get("PAPER_FACTOR_REMOTE_ROOT", "/mnt/remote_e"))
UNIFIED_ROOT = Path(os.environ.get("PAPER_FACTOR_UNIFIED_ROOT", str(REMOTE_ROOT / "_paper_factor_unified")))
MARKET_DIR = UNIFIED_ROOT / "factor_implementation_source_data"
MARKET_DEBUG_DIR = UNIFIED_ROOT / "factor_implementation_source_data_debug"
FACTOR_OUT = UNIFIED_ROOT / "factor_outputs"
PROFILE_ROOT = Path(os.environ.get("PAPER_FACTOR_PROFILE_ROOT", str(UNIFIED_ROOT / "factor_profiles")))
CATALOG_PATH = UNIFIED_ROOT / "catalog.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_instrument(code: str) -> str:
    s = str(code).strip()
    if not s or s.lower() in {"nan", "none", "trade_date", "date"}:
        return s
    if "." in s and len(s) >= 8:
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


def _factor_frame_to_standard(df: pd.DataFrame, factor_name: str) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("empty factor dataframe")
    out = df.copy()
    if not isinstance(out.index, pd.MultiIndex) or out.index.nlevels != 2:
        raise ValueError("factor must use MultiIndex (datetime, instrument)")
    out.index.names = ["datetime", "instrument"]
    col = str(out.columns[0])
    if col != factor_name:
        out = out.rename(columns={col: factor_name})
    out = out[[factor_name]]
    out[factor_name] = pd.to_numeric(out[factor_name], errors="coerce")
    out = out.sort_index()
    return out


def wide_table_to_factor(path: Path, factor_name: str) -> pd.DataFrame:
    raw = pd.read_csv(path, low_memory=False)
    date_col = next((c for c in ("trade_date", "date", "datetime") if c in raw.columns), None)
    if date_col is None:
        raise ValueError(f"no date column in {path}")
    raw[date_col] = pd.to_datetime(raw[date_col].astype(str), errors="coerce")
    id_cols = [date_col]
    value_cols = [c for c in raw.columns if c not in id_cols]
    long = raw.melt(id_vars=id_cols, value_vars=value_cols, var_name="instrument", value_name=factor_name)
    long["instrument"] = long["instrument"].map(normalize_instrument)
    long = long.dropna(subset=[date_col, "instrument", factor_name])
    long = long.rename(columns={date_col: "datetime"})
    long = long.set_index(["datetime", "instrument"]).sort_index()
    return _factor_frame_to_standard(long, factor_name)


def read_tabular_factor(path: Path, factor_name: str) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return wide_table_to_factor(path, factor_name)
    if suffix in {".xlsx", ".xls"}:
        raw = pd.read_excel(path)
        tmp = path.with_suffix(".csv.tmp")
        try:
            raw.to_csv(tmp, index=False)
            return wide_table_to_factor(tmp, factor_name)
        finally:
            tmp.unlink(missing_ok=True)
    raise ValueError(f"unsupported factor file: {path}")


def write_factor_export(
    df: pd.DataFrame,
    *,
    export_dir: Path,
    factor_name: str,
    meta_extra: dict[str, Any],
) -> tuple[Path, Path]:
    export_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = export_dir / f"{factor_name}.parquet"
    meta_path = export_dir / f"{factor_name}.meta.json"
    df.to_parquet(parquet_path, engine="pyarrow")
    col = df.columns[0]
    meta = {
        "factor_name": factor_name,
        "display_name": factor_name,
        "accepted": True,
        "source_type": meta_extra.get("source_type", "remote_unified"),
        "source_category": meta_extra.get("source_category"),
        "source_report_title": meta_extra.get("source_report_title"),
        "source_path": meta_extra.get("source_path"),
        "rows": int(len(df)),
        "non_null": int(pd.to_numeric(df[col], errors="coerce").notna().sum()),
        "latest_path": str(parquet_path),
        "metadata_path": str(meta_path),
        "updated_at": _now_iso(),
    }
    meta.update({k: v for k, v in meta_extra.items() if k not in meta})
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return parquet_path, meta_path


def ensure_market_data(*, skip_minute: bool = True, force: bool = False) -> dict[str, Any]:
    daily_path = MARKET_DIR / "daily_pv.h5"
    if daily_path.exists() and not force:
        return {"status": "skipped", "daily_pv": str(daily_path)}

    os.environ.setdefault("PAPER_FACTOR_DATA_ROOT", str(MARKET_DIR))
    os.environ.setdefault("PAPER_FACTOR_DATA_DEBUG_ROOT", str(MARKET_DEBUG_DIR))
    if skip_minute:
        os.environ["SKIP_MINUTE"] = "1"

    import scripts.convert_remote_data as convert_mod  # noqa: WPS433

    argv_bak = sys.argv
    sys.argv = ["convert_remote_data.py", str(REMOTE_ROOT)]
    try:
        rc = convert_mod.main()
    finally:
        sys.argv = argv_bak
    if rc != 0:
        raise RuntimeError("market convert failed")

    for d in (MARKET_DIR, MARKET_DEBUG_DIR):
        minute_path = d / "minute_pv.h5"
        daily_path = d / "daily_pv.h5"
        if not minute_path.exists() and daily_path.exists():
            stub = pd.read_hdf(daily_path, key="data").iloc[: min(500, len(pd.read_hdf(daily_path, key="data")))]
            stub.to_hdf(minute_path, key="data")

    # copy schema/readme if present on remote
    for name in ("因子汇总.xlsx", "factor_field_schema.xlsx", "数据说明.txt"):
        src = REMOTE_ROOT / name
        if src.exists():
            import shutil

            shutil.copy2(src, MARKET_DIR / name)

    return {"status": "ok", "daily_pv": str(daily_path), "debug": str(MARKET_DEBUG_DIR / "daily_pv.h5")}


def sync_fundamental(*, limit: int | None = None, force: bool = False) -> list[dict[str, Any]]:
    src_root = REMOTE_ROOT / "基本面因子"
    if not src_root.exists():
        raise FileNotFoundError(f"missing {src_root}")

    results: list[dict[str, Any]] = []
    skip_names = {"因子汇总.xlsx", "factor_field_schema.xlsx"}
    files = sorted(
        p
        for p in src_root.rglob("*")
        if p.suffix.lower() in {".csv", ".xlsx", ".xls"}
        and p.is_file()
        and p.name not in skip_names
    )
    if limit is not None:
        files = files[:limit]

    for path in files:
        category = path.parent.name if path.parent != src_root else "root"
        factor_name = path.stem
        export_dir = FACTOR_OUT / "fundamental" / category
        parquet_path = export_dir / f"{factor_name}.parquet"
        if parquet_path.exists() and not force:
            results.append({"factor_name": factor_name, "status": "skipped", "path": str(parquet_path)})
            continue
        try:
            df = read_tabular_factor(path, factor_name)
            pq, meta = write_factor_export(
                df,
                export_dir=export_dir,
                factor_name=factor_name,
                meta_extra={
                    "source_type": "fundamental_remote",
                    "source_category": category,
                    "source_path": str(path),
                },
            )
            results.append({"factor_name": factor_name, "status": "ok", "parquet": str(pq), "meta": str(meta)})
            print(f"OK fundamental {category}/{factor_name} rows={len(df)}")
        except Exception as exc:  # noqa: BLE001
            results.append({"factor_name": factor_name, "status": "error", "error": str(exc), "path": str(path)})
            print(f"ERR fundamental {path}: {exc}")
    return results


def _run_literature_code(code_path: Path, market_dir: Path) -> pd.DataFrame:
    with tempfile.TemporaryDirectory(prefix="pf_factor_") as tmp:
        env = os.environ.copy()
        env["FACTOR_DATA_DIR"] = str(market_dir)
        env["RDAGENT_FACTOR_DATA_DIR"] = str(market_dir)
        proc = subprocess.run(
            [sys.executable, str(code_path)],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("PAPER_FACTOR_CODE_TIMEOUT", "900")),
        )
        result_h5 = Path(tmp) / "result.h5"
        if result_h5.exists():
            df = pd.read_hdf(result_h5, key="data")
            return _factor_frame_to_standard(df, str(df.columns[0]))
        raise RuntimeError(
            f"code failed for {code_path.name}: exit={proc.returncode}\n"
            f"stdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
        )


def _find_meta_for_parquet(parquet_path: Path) -> dict[str, Any]:
    for suffix in (".meta.json", ".json"):
        meta_path = parquet_path.with_suffix(suffix)
        if meta_path.exists() and meta_path.suffix == ".json" and meta_path.name.endswith(".code.json"):
            continue
        if meta_path.exists():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
            except Exception:  # noqa: BLE001
                pass
    code_path = parquet_path.with_suffix(".code.py")
    if not code_path.exists():
        alt = parquet_path.parent / f"{parquet_path.stem}.code.py"
        if alt.exists():
            code_path = alt
    return {
        "factor_name": parquet_path.stem,
        "display_name": parquet_path.stem,
        "source_type": "literature_remote",
        "code_path": str(code_path) if code_path.exists() else None,
    }


def _group_key_for_parquet(src_root: Path, parquet_path: Path) -> str:
    rel = parquet_path.relative_to(src_root)
    parts = list(rel.parts)
    if len(parts) == 1:
        return "root"
    if len(parts) == 2:
        return parts[0]
    return str(Path(*parts[:-1]))


def sync_literature(*, execute_code: bool = False, force: bool = False) -> list[dict[str, Any]]:
    """Index existing paper_factors parquet on E: (no copy). Writes small meta.json only."""
    src_root = REMOTE_ROOT / "paper_factors"
    if not src_root.exists():
        raise FileNotFoundError(f"missing {src_root}")

    market_dir = MARKET_DIR
    results: list[dict[str, Any]] = []
    parquet_files = sorted(src_root.rglob("*.parquet"))
    if not parquet_files:
        print(f"WARN: no parquet found under {src_root} (check mount / path)")

    for src_parquet in parquet_files:
        group = _group_key_for_parquet(src_root, src_parquet)
        factor_name = src_parquet.stem
        export_dir = FACTOR_OUT / "literature" / group.replace("/", "__")
        out_meta_path = export_dir / f"{factor_name}.meta.json"

        if out_meta_path.exists() and not force:
            results.append({"factor_name": factor_name, "status": "skipped", "group": group})
            continue

        meta = _find_meta_for_parquet(src_parquet)
        factor_name = str(meta.get("factor_name") or factor_name)

        df: pd.DataFrame | None = None
        if src_parquet.exists():
            try:
                df = pd.read_parquet(src_parquet)
                df = _factor_frame_to_standard(df, factor_name)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {"factor_name": factor_name, "status": "error", "error": str(exc), "parquet": str(src_parquet)}
                )
                print(f"ERR read parquet {src_parquet}: {exc}")
                continue
        elif execute_code:
            if not (market_dir / "daily_pv.h5").exists():
                raise FileNotFoundError(f"run market first: {market_dir / 'daily_pv.h5'}")
            code_path = Path(meta.get("code_path") or src_parquet.with_suffix(".code.py"))
            if not code_path.exists():
                results.append({"factor_name": factor_name, "status": "missing_code"})
                continue
            df = _run_literature_code(code_path, market_dir)
        else:
            results.append({"factor_name": factor_name, "status": "missing_parquet", "path": str(src_parquet)})
            continue

        merged_meta = dict(meta)
        merged_meta.update(
            {
                "factor_name": factor_name,
                "display_name": meta.get("display_name") or factor_name,
                "accepted": True,
                "source_type": "literature_remote",
                "source_group": group,
                "source_report_title": meta.get("source_report_title") or group,
                "source_path": str(src_parquet),
                "latest_path": str(src_parquet.resolve()),
                "metadata_path": str(out_meta_path),
                "rows": int(len(df)),
                "non_null": int(pd.to_numeric(df.iloc[:, 0], errors="coerce").notna().sum()),
                "updated_at": _now_iso(),
            }
        )
        export_dir.mkdir(parents=True, exist_ok=True)
        out_meta_path.write_text(json.dumps(merged_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(
            {
                "factor_name": factor_name,
                "status": "indexed",
                "group": group,
                "parquet": str(src_parquet),
                "meta": str(out_meta_path),
            }
        )
        print(f"OK index literature [{group}] {factor_name} -> {src_parquet}")
    return results


def write_catalog(*, market: dict[str, Any], fundamental: list[dict], literature: list[dict]) -> None:
    catalog = {
        "updated_at": _now_iso(),
        "remote_root": str(REMOTE_ROOT),
        "unified_root": str(UNIFIED_ROOT),
        "market": market,
        "fundamental": fundamental,
        "literature": literature,
    }
    UNIFIED_ROOT.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote catalog: {CATALOG_PATH}")


def link_into_project(project_root: Path, *, force: bool = False) -> None:
    import shutil

    gi = project_root / "git_ignore_folder"
    targets = {
        gi / "factor_implementation_source_data": MARKET_DIR,
        gi / "factor_implementation_source_data_debug": MARKET_DEBUG_DIR,
        gi / "factor_outputs" / "unified_remote": FACTOR_OUT,
        gi / "factor_outputs" / "paper_factors_raw": REMOTE_ROOT / "paper_factors",
        gi / "factor_profiles": PROFILE_ROOT,
    }
    for local_path, remote_path in targets.items():
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if local_path.is_symlink():
            local_path.unlink()
        elif local_path.exists():
            if force:
                if local_path.is_dir():
                    shutil.rmtree(local_path)
                else:
                    local_path.unlink()
            else:
                raise RuntimeError(
                    f"local path exists: {local_path}. Remove it or rerun with: "
                    f"python scripts/unify_remote_factors.py link --force"
                )
        local_path.symlink_to(remote_path)
        print(f"Linked {local_path} -> {remote_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Unify remote factors for paper-factor analyze.")
    parser.add_argument(
        "command",
        choices=("all", "market", "fundamental", "literature", "link"),
        help="what to run",
    )
    parser.add_argument("--force", action="store_true", help="overwrite existing outputs")
    parser.add_argument("--skip-minute", action="store_true", default=True)
    parser.add_argument("--limit", type=int, default=None, help="limit fundamental files (debug)")
    parser.add_argument(
        "--execute-code",
        action="store_true",
        help="run paper_factors *.code.py when parquet missing (slow)",
    )
    parser.add_argument("--project-root", type=Path, default=ROOT)
    args = parser.parse_args()

    if not REMOTE_ROOT.exists():
        print(f"Remote root not mounted: {REMOTE_ROOT}", file=sys.stderr)
        return 1

    UNIFIED_ROOT.mkdir(parents=True, exist_ok=True)
    market_info: dict[str, Any] = {}
    fundamental_info: list[dict[str, Any]] = []
    literature_info: list[dict[str, Any]] = []

    if args.command in {"all", "market"}:
        market_info = ensure_market_data(skip_minute=args.skip_minute, force=args.force)
    if args.command in {"all", "fundamental"}:
        fundamental_info = sync_fundamental(limit=args.limit, force=args.force)
    if args.command in {"all", "literature"}:
        literature_info = sync_literature(execute_code=args.execute_code, force=args.force)
    if args.command in {"all", "market", "fundamental", "literature"}:
        write_catalog(market=market_info, fundamental=fundamental_info, literature=literature_info)
    if args.command in {"all", "link"}:
        link_into_project(args.project_root, force=args.force)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
