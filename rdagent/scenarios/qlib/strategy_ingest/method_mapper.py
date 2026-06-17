"""Map extracted paper strategy JSON to executable StrategySpec."""

from __future__ import annotations

from typing import Any

from rdagent.scenarios.qlib.strategy.registry import get_all_methods
from rdagent.scenarios.qlib.strategy.spec import StrategySpec


_REBALANCE_DAYS = {"daily": 1, "weekly": 5, "monthly": 20}


def map_extracted_to_spec(extracted: dict[str, Any]) -> tuple[StrategySpec, dict[str, Any]]:
    """
    Map LLM-extracted strategy to StrategySpec.
    Returns (spec, mapping_meta) with novelty / fallback info.
    """
    all_methods = get_all_methods()
    combo = extracted.get("combination") or {}
    portfolio = extracted.get("portfolio") or {}
    constraints = extracted.get("constraints") or {}
    factor_sel = extracted.get("factor_selection") or {}

    method_id = combo.get("method_id")
    novelty = str(combo.get("novelty") or "none").lower()
    mapping: dict[str, Any] = {"novelty": novelty, "mapped_method": None, "warnings": []}

    if method_id and method_id in all_methods:
        mapping["mapped_method"] = method_id
        mode = "single"
    elif combo.get("alternatives"):
        for alt in combo["alternatives"]:
            if alt in all_methods:
                method_id = alt
                mapping["mapped_method"] = alt
                mapping["warnings"].append(f"primary method missing; used alternative {alt}")
                mode = "single"
                break
        else:
            mode = "auto"
            mapping["warnings"].append("no method_id matched registry; using mode=auto sweep")
    else:
        mode = "auto"
        if novelty != "none":
            mapping["warnings"].append(f"novelty={novelty} but no registry match; mode=auto")

    style = str(portfolio.get("style") or "neutral")
    if style not in {"small_cap", "csi300_enh", "air_index_enh", "neutral"}:
        style = "neutral"
        mapping["warnings"].append(f"unknown style {portfolio.get('style')}; default neutral")

    rebalance = str(portfolio.get("rebalance") or "daily").lower()
    rebalance_period = _REBALANCE_DAYS.get(rebalance, 1)

    spec = StrategySpec(
        name=str(extracted.get("strategy_name") or "paper_strategy"),
        style=style,
        mode=mode,
        method=method_id if mode == "single" else None,
        top_frac=float(portfolio.get("top_frac") or 0.2),
        bottom_frac=float(portfolio.get("bottom_frac") or 0.2),
        max_factors=int(factor_sel.get("max_factors") or 30),
        min_icir=float(factor_sel["min_icir"]) if factor_sel.get("min_icir") is not None else None,
        include_tags=list(factor_sel.get("include_tags") or []),
        rebalance_period=rebalance_period,
        min_sharpe=float(constraints["min_sharpe"]) if constraints.get("min_sharpe") is not None else None,
        max_drawdown=float(constraints["max_drawdown"]) if constraints.get("max_drawdown") is not None else None,
        max_turnover=float(constraints["max_turnover"]) if constraints.get("max_turnover") is not None else None,
    )
    mapping["applicability_tags"] = extracted.get("applicability_tags") or []
    return spec, mapping


def ingest_report_to_spec(
    report_path: str,
    *,
    match_factors: bool = True,
) -> tuple[StrategySpec, dict[str, Any], dict[str, Any]]:
    from rdagent.scenarios.qlib.strategy.paper_strategy.pipeline import ingest_paper_strategy_report

    return ingest_paper_strategy_report(report_path, match_factors=match_factors)
