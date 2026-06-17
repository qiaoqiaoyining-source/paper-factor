"""Systematic factor_slice × method × style benchmark grid."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from rdagent.scenarios.qlib.paths import profile_root, strategy_knowledge_root
from rdagent.scenarios.qlib.strategy.profile_loader import load_profile, load_profiles_index
from rdagent.scenarios.qlib.strategy.registry import get_all_methods
from rdagent.scenarios.qlib.strategy.runner import run_method_sweep
from rdagent.scenarios.qlib.strategy.spec import StrategySpec
from rdagent.scenarios.qlib.strategy_knowledge.store import append_record, rebuild_matrix_summary


def _load_taxonomy_slices() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parent / "taxonomy.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("factor_slices") or [])


def resolve_factor_slice(*, tags: list[str], source_type: str) -> str:
    tag_set = {str(t).lower() for t in tags}
    source = str(source_type or "").lower()
    for item in _load_taxonomy_slices():
        sid = str(item.get("id") or "")
        match_tags = {str(t).lower() for t in (item.get("match_tags") or [])}
        match_sources = [str(s).lower() for s in (item.get("match_source_types") or [])]
        if match_sources and source not in match_sources:
            continue
        if match_tags and not (tag_set & match_tags):
            continue
        if match_tags or match_sources:
            return sid
    if "literature" in source:
        return "literature:general"
    return "mixed:general"


def bucket_profiles(
    *,
    profile_root_path: Path | None = None,
    max_per_bucket: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Group factor profiles into taxonomy slices."""
    index = load_profiles_index(profile_root_path or profile_root())
    root = Path(index.get("profile_root") or profile_root_path or profile_root())
    buckets: dict[str, list[dict[str, Any]]] = {}

    for entry in index.get("factors") or []:
        profile_path = Path(str(entry.get("profile_path") or ""))
        if not profile_path.exists():
            profile_path = root / profile_path.name
        if not profile_path.exists():
            continue
        profile = load_profile(profile_path)
        tags = list(profile.get("tags") or entry.get("tags") or [])
        source = str(profile.get("source_type") or entry.get("source_type") or "")
        slice_id = resolve_factor_slice(tags=tags, source_type=source)
        parquet = (profile.get("data") or {}).get("values_parquet")
        if not parquet:
            continue
        item = {
            "factor_name": profile.get("factor_name") or entry.get("factor_name"),
            "profile_path": str(profile_path),
            "parquet_path": str(parquet),
            "tags": tags,
            "source_type": source,
            "icir_pearson": (profile.get("evaluation") or {}).get("icir_pearson"),
        }
        buckets.setdefault(slice_id, []).append(item)

    for sid in list(buckets.keys()):
        items = buckets[sid]
        items.sort(key=lambda x: abs(float(x.get("icir_pearson") or 0)), reverse=True)
        buckets[sid] = items[:max_per_bucket]
    return buckets


def run_benchmark_grid(
    *,
    styles: list[str] | None = None,
    method_ids: list[str] | None = None,
    slice_ids: list[str] | None = None,
    max_per_bucket: int = 15,
    max_factors_in_run: int = 15,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Run factor_slice × style × method grid; persist records to E: strategy_knowledge/.
    """
    styles = styles or ["small_cap", "csi300_enh", "neutral"]
    all_methods = get_all_methods()
    method_ids = method_ids or list(all_methods.keys())
    buckets = bucket_profiles(max_per_bucket=max_per_bucket)

    if slice_ids:
        buckets = {k: v for k, v in buckets.items() if k in slice_ids}

    plan: list[dict[str, Any]] = []
    for slice_id, factors in buckets.items():
        if not factors:
            continue
        for style in styles:
            for mid in method_ids:
                plan.append({"factor_slice": slice_id, "style": style, "method_id": mid, "n_factors": len(factors)})

    if dry_run:
        return {"status": "dry_run", "planned_runs": len(plan), "buckets": {k: len(v) for k, v in buckets.items()}}

    kb_root = strategy_knowledge_root()
    kb_root.mkdir(parents=True, exist_ok=True)
    completed = 0
    errors = 0

    for slice_id, factors in buckets.items():
        if not factors:
            continue
        factor_rows = [
            {
                "factor_name": f["factor_name"],
                "profile_path": f["profile_path"],
                "parquet_path": f["parquet_path"],
                "score": abs(float(f.get("icir_pearson") or 0)),
                "icir_pearson": f.get("icir_pearson"),
                "tags": f.get("tags"),
                "documentation": {},
                "style_exposure": {},
            }
            for f in factors[:max_factors_in_run]
        ]

        for style in styles:
            for mid in method_ids:
                spec = StrategySpec(
                    name=f"grid_{slice_id.replace(':', '_')}_{style}_{mid}",
                    style=style,
                    mode="single",
                    method=mid,
                    max_factors=max_factors_in_run,
                    min_icir=0.0,
                )
                try:
                    results = run_method_sweep(spec, factors=factor_rows, method_ids=[mid])
                    result = results[0] if results else {}
                    record = {
                        "source": "benchmark_grid",
                        "factor_slice": slice_id,
                        "style": style,
                        "method_id": mid,
                        "n_factors": len(factor_rows),
                        "metrics": result.get("metrics") or {},
                        "meets_constraints": result.get("meets_constraints"),
                        "factor_names": result.get("factor_names") or [],
                        "status": result.get("status", "ok"),
                    }
                    append_record(record, root=kb_root)
                    completed += 1
                    sharpe = (record.get("metrics") or {}).get("sharpe_annualized")
                    print(f"grid OK {slice_id} | {style} | {mid} sharpe={sharpe}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    append_record(
                        {
                            "source": "benchmark_grid",
                            "factor_slice": slice_id,
                            "style": style,
                            "method_id": mid,
                            "status": "error",
                            "error": str(exc),
                        },
                        root=kb_root,
                    )
                    print(f"grid ERR {slice_id} | {style} | {mid}: {exc}", flush=True)

    summary = rebuild_matrix_summary(kb_root)
    return {
        "status": "completed",
        "completed_runs": completed,
        "errors": errors,
        "planned_runs": len(plan),
        "knowledge_root": str(kb_root),
        "matrix_summary_path": str(kb_root / "matrix_summary.json"),
        "slice_count": len(buckets),
        "record_count": summary.get("record_count"),
    }
