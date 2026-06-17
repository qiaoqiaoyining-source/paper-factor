"""Map LLM-extracted strategy JSON → toolbox template + generic method."""

from __future__ import annotations

import json
from typing import Any

from rdagent.scenarios.qlib.strategy.paper_strategy.recipe import slugify
from rdagent.scenarios.qlib.strategy.paper_strategy.template_loader import (
    get_template,
    load_paper_strategy_templates,
    method_ids_in_catalog,
)


def _text_blob(extracted: dict[str, Any]) -> str:
    combo = extracted.get("combination") or {}
    parts = [
        str(extracted.get("strategy_name") or ""),
        str(combo.get("description") or ""),
        str(combo.get("method_name") or ""),
        str(combo.get("novelty") or ""),
        json.dumps(combo, ensure_ascii=False),
    ]
    return " ".join(parts).lower()


def map_extract_to_template(extracted: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """
    Rule-based template mapping (no LLM).
    Returns (template_id, method_id, params, mapping_meta).
    """
    templates = load_paper_strategy_templates()
    blob = _text_blob(extracted)
    combo = extracted.get("combination") or {}
    mapping: dict[str, Any] = {"matcher": "rule", "notes": []}

    method_id = combo.get("method_id")
    catalog_methods = method_ids_in_catalog()
    if method_id and method_id in catalog_methods:
        for tid, meta in templates.items():
            if meta.get("method_id") == method_id:
                params = dict(meta.get("default_params") or {})
                mapping["notes"].append(f"direct method_id={method_id}")
                return tid, str(method_id), params, mapping

    best: tuple[int, str, dict[str, Any], str] | None = None
    for tid, meta in templates.items():
        for kw in meta.get("keywords") or []:
            kw_s = str(kw).lower()
            if kw_s in blob and (best is None or len(kw_s) > best[0]):
                best = (len(kw_s), tid, meta, kw_s)
    if best:
        _, tid, meta, kw = best
        mapping["notes"].append(f"keyword match: {kw} → template {tid}")
        return tid, str(meta["method_id"]), dict(meta.get("default_params") or {}), mapping

    alts = combo.get("alternatives") or []
    for alt in alts:
        for tid, meta in templates.items():
            if meta.get("method_id") == alt:
                mapping["notes"].append(f"used alternative {alt}")
                mapping["warnings"] = [f"primary method not in catalog; used {alt}"]
                return tid, str(meta["method_id"]), dict(meta.get("default_params") or {}), mapping

    tid = "cross_section_ols_combo"
    meta = get_template(tid) or {}
    mapping["notes"].append("fallback cross_section_ols_combo")
    mapping["warnings"] = ["no template keyword match; fallback to cross_section_ols_combo"]
    return tid, str(meta.get("method_id") or "cross_section_ols_combo"), dict(meta.get("default_params") or {}), mapping


def build_recipe_from_extract(
    extracted: dict[str, Any],
    *,
    report_path: str,
    template_id: str,
    method_id: str,
    params: dict[str, Any],
    mapping_meta: dict[str, Any],
) -> "PaperStrategyRecipe":
    from rdagent.scenarios.qlib.strategy.paper_strategy.recipe import PaperStrategyRecipe, portfolio_from_extracted

    name = str(extracted.get("strategy_name") or "paper_strategy")
    recipe_id = slugify(f"{name}_{template_id}")
    pf = portfolio_from_extracted(extracted)
    combo = extracted.get("combination") or {}
    template = get_template(template_id) or {}
    return PaperStrategyRecipe(
        recipe_id=recipe_id,
        display_name=str(template.get("display_name") or name),
        method_id=method_id,
        template_id=template_id,
        params=params,
        style=pf["style"],
        top_frac=pf["top_frac"],
        bottom_frac=pf["bottom_frac"],
        rebalance_period=pf["rebalance_period"],
        source_report=report_path,
        source_report_title=name,
        combination_description=str(combo.get("description") or ""),
        intent=str(extracted.get("intent") or combo.get("intent") or ""),
        applicability_tags=list(extracted.get("applicability_tags") or []),
        mapping_notes=list(mapping_meta.get("notes") or []),
        matcher=str(mapping_meta.get("matcher") or "rule"),
    )
