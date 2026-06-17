"""Query empirical strategy knowledge for agents and planners."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rdagent.scenarios.qlib.strategy_knowledge.store import load_all_records, matrix_path, rebuild_matrix_summary
from rdagent.scenarios.qlib.paths import strategy_knowledge_root


def load_matrix_summary(*, rebuild: bool = False, root: Path | None = None) -> dict[str, Any]:
    kb_root = root or strategy_knowledge_root()
    path = matrix_path(kb_root)
    if rebuild or not path.exists():
        return rebuild_matrix_summary(kb_root)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return rebuild_matrix_summary(kb_root)


def query_methods(
    *,
    factor_slice: str,
    style: str = "neutral",
    top_k: int = 5,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return best methods for a factor slice + style from empirical KB."""
    matrix = load_matrix_summary(root=root)
    slice_data = (matrix.get("slices") or {}).get(factor_slice) or {}
    style_data = (slice_data.get("styles") or {}).get(style) or {}
    methods = style_data.get("methods") or {}
    ranked: list[tuple[float, str, dict[str, Any]]] = []
    for mid, info in methods.items():
        if info.get("status") == "error":
            continue
        sharpe = float(info.get("best_sharpe") or -1e9)
        ranked.append((sharpe, mid, info))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return {
        "factor_slice": factor_slice,
        "style": style,
        "best_methods": [{"method_id": mid, **info} for _, mid, info in ranked[:top_k]],
        "avoid_methods": style_data.get("avoid_methods") or [],
        "record_count": matrix.get("record_count", 0),
    }


def build_planner_context(
    *,
    factor_tags: list[str] | None = None,
    source_type: str | None = None,
    style: str = "neutral",
    user_goal: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """Context blob for strategy agent: empirical KB + tag-matched slice."""
    from rdagent.scenarios.qlib.strategy_knowledge.benchmark_grid import resolve_factor_slice

    slice_id = resolve_factor_slice(tags=factor_tags or [], source_type=source_type or "")
    empirical = query_methods(factor_slice=slice_id, style=style, root=root)
    recent = load_all_records(root)[-5:]
    return {
        "user_goal": user_goal,
        "factor_slice": slice_id,
        "style": style,
        "factor_tags": factor_tags or [],
        "source_type": source_type,
        "empirical_kb": empirical,
        "recent_experiments": [
            {
                "factor_slice": r.get("factor_slice"),
                "style": r.get("style"),
                "method_id": r.get("method_id"),
                "sharpe": (r.get("metrics") or {}).get("sharpe_annualized"),
            }
            for r in recent
        ],
    }
