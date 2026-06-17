"""Persist empirical strategy knowledge on E: drive."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from rdagent.scenarios.qlib.paths import strategy_knowledge_root


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def records_dir(root: Path | None = None) -> Path:
    d = (root or strategy_knowledge_root()) / "records"
    d.mkdir(parents=True, exist_ok=True)
    return d


def matrix_path(root: Path | None = None) -> Path:
    return (root or strategy_knowledge_root()) / "matrix_summary.json"


def taxonomy_path(root: Path | None = None) -> Path:
    pkg = Path(__file__).resolve().parent / "taxonomy.yaml"
    remote = (root or strategy_knowledge_root()) / "taxonomy.yaml"
    if remote.exists():
        return remote
    return pkg


def load_taxonomy(root: Path | None = None) -> dict[str, Any]:
    path = taxonomy_path(root)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def append_record(record: dict[str, Any], root: Path | None = None) -> Path:
    """Append one experiment record as JSON file."""
    base = records_dir(root)
    rid = record.get("experiment_id") or f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    record = {"recorded_at": _now_iso(), **record, "experiment_id": rid}
    path = base / f"{rid}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_all_records(root: Path | None = None) -> list[dict[str, Any]]:
    base = records_dir(root)
    out: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def rebuild_matrix_summary(root: Path | None = None) -> dict[str, Any]:
    """Aggregate records into factor_slice × style × method matrix."""
    records = load_all_records(root)
    matrix: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    for rec in records:
        slice_id = str(rec.get("factor_slice") or "unknown")
        style = str(rec.get("style") or "neutral")
        method = str(rec.get("method_id") or "unknown")
        matrix[slice_id][style][method].append(rec)

    summary: dict[str, Any] = {
        "updated_at": _now_iso(),
        "record_count": len(records),
        "slices": {},
    }

    for slice_id, styles in matrix.items():
        slice_summary: dict[str, Any] = {"styles": {}}
        for style, methods in styles.items():
            style_summary: dict[str, Any] = {"methods": {}}
            ranked: list[tuple[float, str, dict[str, Any]]] = []
            for method_id, runs in methods.items():
                ok_runs = [r for r in runs if (r.get("metrics") or {}).get("status") != "error"]
                if not ok_runs:
                    style_summary["methods"][method_id] = {"status": "error", "runs": len(runs)}
                    continue
                best = max(ok_runs, key=lambda r: float((r.get("metrics") or {}).get("sharpe_annualized") or -1e9))
                m = best.get("metrics") or {}
                style_summary["methods"][method_id] = {
                    "runs": len(runs),
                    "best_sharpe": m.get("sharpe_annualized"),
                    "best_mdd": m.get("max_drawdown"),
                    "best_turnover": m.get("turnover_mean"),
                    "meets_constraints": best.get("meets_constraints"),
                    "n_factors": best.get("n_factors"),
                }
                sharpe = float(m.get("sharpe_annualized") or -1e9)
                ranked.append((sharpe, method_id, style_summary["methods"][method_id]))
            ranked.sort(key=lambda x: x[0], reverse=True)
            style_summary["best_methods"] = [mid for _, mid, _ in ranked[:3]]
            style_summary["avoid_methods"] = [mid for _, mid, _ in ranked[-2:] if ranked]
            slice_summary["styles"][style] = style_summary
        summary["slices"][slice_id] = slice_summary

    out_path = matrix_path(root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def record_from_strategy_run(
    payload: dict[str, Any],
    *,
    factor_slice: str,
    style: str,
    method_id: str,
    source: str = "strategy_run",
) -> dict[str, Any]:
    sel = payload.get("selection") or {}
    result = sel.get("selected_result") or {}
    if not result and payload.get("sweep_results"):
        for item in payload["sweep_results"]:
            if item.get("method_id") == method_id:
                result = item
                break
    spec_d = payload.get("spec") or {}
    return {
        "source": source,
        "factor_slice": factor_slice,
        "style": style,
        "method_id": method_id,
        "paper_strategy_id": spec_d.get("paper_strategy_id"),
        "paper_strategy_recipe_path": spec_d.get("paper_strategy_recipe_path"),
        "source_report_path": spec_d.get("source_report_path"),
        "metrics": result.get("metrics") or {},
        "meets_constraints": result.get("meets_constraints"),
        "n_factors": payload.get("n_factors") or result.get("n_factors"),
        "factor_names": result.get("factor_names") or [],
        "run_dir": payload.get("output_dir"),
        "spec_name": spec_d.get("name"),
    }
