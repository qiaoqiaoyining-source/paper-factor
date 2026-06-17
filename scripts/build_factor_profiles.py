#!/usr/bin/env python3
"""
Build normalized per-factor profile files on remote E: (not C:).

Each factor gets one JSON profile under:
  {PROFILE_ROOT}/{source_type}/{factor_name}.profile.json

Profile includes: tags/style exposure, description/formula (from paper JSON or 因子汇总),
IC/ICIR/turnover metrics, Barra summary, and pointer to factor values parquet on E:.

Usage:
  python scripts/build_factor_profiles.py
  python scripts/build_factor_profiles.py --evaluate-missing
  python scripts/build_factor_profiles.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REMOTE_ROOT = Path(os.environ.get("PAPER_FACTOR_REMOTE_ROOT", "/mnt/remote_e"))
UNIFIED_ROOT = Path(os.environ.get("PAPER_FACTOR_UNIFIED_ROOT", str(REMOTE_ROOT / "_paper_factor_unified")))
FACTOR_OUT = UNIFIED_ROOT / "factor_outputs"
PROFILE_ROOT = Path(os.environ.get("PAPER_FACTOR_PROFILE_ROOT", str(UNIFIED_ROOT / "factor_profiles")))
MARKET_DIR = UNIFIED_ROOT / "factor_implementation_source_data"
PROJECT_FACTOR_OUT = Path(
    os.environ.get("PAPER_FACTOR_OUTPUTS_DIR", str(ROOT / "git_ignore_folder" / "factor_outputs"))
)
ANALYSIS_DIR = PROJECT_FACTOR_OUT / "factor_analysis"

CATEGORY_STYLE_TAGS: dict[str, list[str]] = {
    "盈利": ["fundamental", "profitability", "earnings"],
    "价值": ["fundamental", "value"],
    "成长": ["fundamental", "growth"],
    "质量": ["fundamental", "quality"],
    "杠杆": ["fundamental", "leverage"],
    "运营": ["fundamental", "operating", "efficiency"],
    "现金流": ["fundamental", "cashflow"],
    "股本": ["fundamental", "capital_structure"],
    "其他": ["fundamental", "other"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", name).strip("_") or "factor"


def _load_fundamental_schema() -> dict[str, dict[str, str]]:
    from rdagent.scenarios.qlib.experiment.data_schema import load_factor_field_schema

    for base in (MARKET_DIR, REMOTE_ROOT, UNIFIED_ROOT):
        schema = load_factor_field_schema(base if base.exists() else None)
        if schema:
            return schema
    xlsx_candidates = [
        REMOTE_ROOT / "因子汇总.xlsx",
        REMOTE_ROOT / "基本面因子" / "因子汇总.xlsx",
        MARKET_DIR / "因子汇总.xlsx",
    ]
    for path in xlsx_candidates:
        if path.exists():
            return load_factor_field_schema(path.parent)
    return {}


def _lookup_schema(schema: dict[str, dict[str, str]], factor_name: str) -> dict[str, str]:
    keys = [
        factor_name,
        f"${factor_name}",
        factor_name.replace("因子", ""),
    ]
    for key in keys:
        col = key if key.startswith("$") else f"${key}"
        if col in schema:
            return schema[col]
    for col, info in schema.items():
        short = info.get("short_name", "")
        if short and short in factor_name:
            return info
        bare = col.lstrip("$")
        if bare == factor_name:
            return info
    return {}


def _discover_factor_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    search_roots = [
        FACTOR_OUT,
        PROJECT_FACTOR_OUT,
        REMOTE_ROOT / "paper_factors",
    ]
    for root in search_roots:
        if not root.exists():
            continue
        for meta_path in root.rglob("*.meta.json"):
            if "factor_analysis" in meta_path.parts or "factor_profiles" in meta_path.parts:
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(meta, dict):
                continue
            parquet_path = meta.get("latest_path") or str(meta_path.with_suffix(".parquet"))
            pq = Path(str(parquet_path))
            if not pq.exists():
                alt = meta_path.with_suffix(".parquet")
                if alt.exists():
                    pq = alt
                else:
                    continue
            key = str(pq.resolve())
            if key in seen:
                continue
            seen.add(key)
            source_type = str(meta.get("source_type") or ("fundamental_remote" if "fundamental" in meta_path.parts else "literature_remote"))
            category = meta.get("source_category") or meta_path.parent.name
            records.append(
                {
                    **meta,
                    "parquet_path": str(pq),
                    "metadata_path": str(meta_path),
                    "source_type": source_type,
                    "source_category": category,
                }
            )

        for parquet_path in root.rglob("*.parquet"):
            if "factor_profiles" in parquet_path.parts:
                continue
            key = str(parquet_path.resolve())
            if key in seen:
                continue
            meta_path = parquet_path.with_suffix(".meta.json")
            json_path = parquet_path.with_suffix(".json")
            if meta_path.exists() or json_path.exists():
                continue
            seen.add(key)
            rel_parts = parquet_path.relative_to(root).parts
            group = rel_parts[0] if rel_parts else "unknown"
            records.append(
                {
                    "factor_name": parquet_path.stem,
                    "display_name": parquet_path.stem,
                    "accepted": True,
                    "source_type": "literature_remote" if root.name == "paper_factors" else "legacy_parquet",
                    "source_category": group,
                    "parquet_path": str(parquet_path),
                    "metadata_path": None,
                }
            )
    return records


def _load_analysis(factor_name: str) -> dict[str, Any] | None:
    path = ANALYSIS_DIR / f"{factor_name}.analysis.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _build_tags(
    record: dict[str, Any],
    analysis: dict[str, Any] | None,
    schema_info: dict[str, str],
) -> list[str]:
    tags: list[str] = []
    for key in ("tags",):
        raw = record.get(key)
        if isinstance(raw, list):
            tags.extend(str(t) for t in raw)
        elif isinstance(raw, str) and raw:
            tags.append(raw)

    source_type = str(record.get("source_type") or "")
    if source_type.startswith("fundamental"):
        tags.append("fundamental")
        cat = str(record.get("source_category") or "")
        tags.extend(CATEGORY_STYLE_TAGS.get(cat, ["fundamental"]))
    elif source_type.startswith("literature"):
        tags.extend(["literature", "paper_factor"])

    if schema_info.get("short_name"):
        tags.append(f"theme:{schema_info['short_name']}")

    barra = (analysis or {}).get("barra") or {}
    exp = barra.get("exposure_diagnostics") or {}
    for item in exp.get("dominant_style_loadings") or []:
        style = item.get("style")
        if style:
            tags.append(f"barra:{style}")

    # dedupe preserve order
    out: list[str] = []
    for t in tags:
        if t and t not in out:
            out.append(t)
    return out


def _build_style_exposure(analysis: dict[str, Any] | None) -> dict[str, Any]:
    barra = (analysis or {}).get("barra") or {}
    exp = barra.get("exposure_diagnostics") or {}
    attrib = barra.get("return_risk_attribution") or {}
    return {
        "barra_model": barra.get("barra_model"),
        "status": exp.get("status") or barra.get("status"),
        "dominant_barra_styles": exp.get("dominant_style_loadings") or [],
        "style_beta_mean": exp.get("style_beta_mean") or {},
        "long_short_barra_exposure": exp.get("long_short_style_exposure") or {},
        "mean_daily_style_contrib": attrib.get("mean_daily_style_contrib"),
        "mean_daily_specific_contrib": attrib.get("mean_daily_specific_contrib"),
    }


def _build_documentation(record: dict[str, Any], schema_info: dict[str, str]) -> dict[str, Any]:
    doc = {
        "factor_description": record.get("factor_description"),
        "factor_formulation": record.get("factor_formulation"),
        "variables": record.get("variables"),
        "source_report_title": record.get("source_report_title"),
        "source_report_path": record.get("source_report_path"),
        "source_path": record.get("source_path"),
        "logic_summary": record.get("logic_summary"),
    }
    if schema_info:
        doc.update(
            {
                "short_name": schema_info.get("short_name"),
                "formula": schema_info.get("formula"),
                "data_source": schema_info.get("source"),
                "english_name": schema_info.get("english_name"),
                "note": schema_info.get("note"),
                "schema_factor_name": schema_info.get("factor_name"),
            }
        )
    if not doc.get("formula") and record.get("factor_formulation"):
        doc["formula"] = record.get("factor_formulation")
    if not doc.get("factor_description") and schema_info.get("short_name"):
        doc["factor_description"] = schema_info.get("short_name")
    return {k: v for k, v in doc.items() if v is not None}


def _build_evaluation(analysis: dict[str, Any] | None) -> dict[str, Any]:
    if not analysis:
        return {"status": "not_evaluated"}
    metrics = analysis.get("metrics") or {}
    keys = [
        "ic_mean_pearson",
        "ic_std_pearson",
        "icir_pearson",
        "ic_positive_hit_rate",
        "rank_ic_mean",
        "rank_ic_std",
        "rank_icir",
        "ls_daily_mean",
        "ls_sharpe_annualized",
        "ls_cumulative_return",
        "ls_max_drawdown",
        "top_bottom_turnover_mean",
        "n_calendar_days",
        "n_observations",
        "ic_days",
    ]
    out = {k: metrics.get(k) for k in keys if metrics.get(k) is not None}
    out["ic_scalar"] = analysis.get("ic_scalar")
    out["metrics_feedback"] = analysis.get("metrics_feedback")
    out["status"] = "ok"
    out["analyzed_at"] = analysis.get("analyzed_at")
    return out


def build_profile(
    record: dict[str, Any],
    *,
    schema: dict[str, dict[str, str]],
    analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    factor_name = str(record.get("factor_name") or Path(record["parquet_path"]).stem)
    source_type = str(record.get("source_type") or "unknown")
    category = record.get("source_category")
    schema_info = _lookup_schema(schema, factor_name) if source_type.startswith("fundamental") else {}

    tags = _build_tags(record, analysis, schema_info)
    parquet_path = Path(record["parquet_path"])

    profile = {
        "factor_id": f"{source_type}/{category or 'general'}/{factor_name}",
        "factor_name": factor_name,
        "display_name": record.get("display_name") or factor_name,
        "source_type": source_type,
        "source_category": category,
        "tags": tags,
        "style_exposure": _build_style_exposure(analysis),
        "documentation": _build_documentation(record, schema_info),
        "evaluation": _build_evaluation(analysis),
        "barra_summary_markdown": (analysis or {}).get("barra_summary") or "",
        "data": {
            "values_parquet": str(parquet_path.resolve()),
            "metadata_path": record.get("metadata_path"),
            "rows": record.get("rows"),
            "non_null": record.get("non_null"),
        },
        "updated_at": _now_iso(),
    }
    return profile


def write_profile(profile: dict[str, Any], *, force: bool = False) -> Path:
    source_type = _safe_name(str(profile.get("source_type") or "unknown"))
    factor_name = _safe_name(str(profile.get("factor_name") or "factor"))
    out_dir = PROFILE_ROOT / source_type
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{factor_name}.profile.json"
    if out_path.exists() and not force:
        return out_path

    parquet_src = Path(profile["data"]["values_parquet"])
    out_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

    link_path = out_dir / f"{factor_name}.values.parquet"
    if link_path.is_symlink() or link_path.exists():
        if link_path.is_symlink():
            link_path.unlink()
        elif link_path.is_file() and not force:
            pass
        else:
            link_path.unlink(missing_ok=True)
    if not link_path.exists():
        try:
            link_path.symlink_to(parquet_src)
        except OSError:
            profile["data"]["values_symlink_error"] = "could not symlink; use values_parquet path"

    return out_path


def run_build(
    *,
    evaluate_missing: bool = False,
    limit: int | None = None,
    force: bool = False,
    barra_model: str = "trading",
    data_type: str = "All",
) -> dict[str, Any]:
    if not REMOTE_ROOT.exists():
        raise FileNotFoundError(f"Remote not mounted: {REMOTE_ROOT}")

    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    schema = _load_fundamental_schema()
    records = _discover_factor_records()
    if limit is not None:
        records = records[:limit]

    if evaluate_missing:
        from rdagent.app.qlib_rd_loop.factor_portfolio_analyze import _analyze_single_factor

        barra_dir = ROOT / "git_ignore_folder" / "barra_model"
        for record in records:
            name = str(record.get("factor_name") or Path(record["parquet_path"]).stem)
            if _load_analysis(name) is None:
                print(f"Evaluating {name} ...")
                try:
                    item = _analyze_single_factor(
                        record,
                        data_type=data_type,
                        barra_model=barra_model,
                        barra_dir=barra_dir if barra_dir.exists() else None,
                    )
                    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
                    (ANALYSIS_DIR / f"{name}.analysis.json").write_text(
                        json.dumps(item, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"ERR evaluate {name}: {exc}")

    profiles: list[dict[str, Any]] = []
    for record in records:
        name = str(record.get("factor_name") or Path(record["parquet_path"]).stem)
        analysis = _load_analysis(name)
        profile = build_profile(record, schema=schema, analysis=analysis)
        out_path = write_profile(profile, force=force)
        profiles.append(
            {
                "factor_name": name,
                "profile_path": str(out_path),
                "tags": profile.get("tags"),
                "icir_pearson": (profile.get("evaluation") or {}).get("icir_pearson"),
                "source_type": profile.get("source_type"),
            }
        )
        print(f"Profile: {out_path}")

    index = {
        "updated_at": _now_iso(),
        "profile_root": str(PROFILE_ROOT),
        "count": len(profiles),
        "factors": profiles,
    }
    index_path = PROFILE_ROOT / "profiles_index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Index: {index_path}")
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description="Build per-factor profile JSON on remote E:")
    parser.add_argument("--evaluate-missing", action="store_true", help="run IC/Barra before profiling")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--barra-model", default="trading")
    parser.add_argument("--data-type", default="All")
    args = parser.parse_args()

    try:
        run_build(
            evaluate_missing=args.evaluate_missing,
            limit=args.limit,
            force=args.force,
            barra_model=args.barra_model,
            data_type=args.data_type,
        )
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
