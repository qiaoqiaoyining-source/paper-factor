"""End-to-end paper strategy ingest and reuse pipeline."""

from __future__ import annotations

from typing import Any

from rdagent.scenarios.qlib.strategy.paper_strategy.recipe import recipe_to_strategy_spec
from rdagent.scenarios.qlib.strategy.paper_strategy.store import load_paper_strategy, register_paper_strategy
from rdagent.scenarios.qlib.strategy.paper_strategy.template_mapper import build_recipe_from_extract, map_extract_to_template
from rdagent.scenarios.qlib.strategy.profile_loader import select_factors
from rdagent.scenarios.qlib.strategy.spec import StrategySpec


def ingest_paper_strategy_report(
    report_path: str,
    *,
    match_factors: bool = True,
) -> tuple[StrategySpec, dict[str, Any], dict[str, Any]]:
    """
    PDF → extract → template map → register toolbox recipe → factor match → StrategySpec.
    """
    from rdagent.scenarios.qlib.strategy_ingest.factor_matcher import (
        apply_factor_match,
        match_strategy_factors,
        persist_factor_match,
    )
    from rdagent.scenarios.qlib.strategy_ingest.method_extractor import extract_strategy_from_report, persist_extracted_strategy

    extracted = extract_strategy_from_report(report_path)
    extract_path = persist_extracted_strategy(extracted)

    template_id, method_id, params, tmap = map_extract_to_template(extracted)
    recipe = build_recipe_from_extract(
        extracted,
        report_path=report_path,
        template_id=template_id,
        method_id=method_id,
        params=params,
        mapping_meta=tmap,
    )
    recipe_paths = register_paper_strategy(recipe)

    spec = recipe_to_strategy_spec(recipe)
    spec.mode = "single"
    from rdagent.scenarios.qlib.strategy.registry import resolve_method_id, resolve_method_params

    spec.method = resolve_method_id(method_id)
    spec.method_params = resolve_method_params(method_id, params)
    spec.paper_strategy_recipe_path = next(iter(recipe_paths.values()), "")
    spec.source_report_path = report_path

    mapping: dict[str, Any] = {
        "extracted_path": str(extract_path),
        "template_id": template_id,
        "mapped_method": method_id,
        "paper_strategy_id": recipe.recipe_id,
        "paper_strategy_recipe_path": spec.paper_strategy_recipe_path,
        "recipe_paths": recipe_paths,
        "template_mapping": tmap,
        "novelty": str((extracted.get("combination") or {}).get("novelty") or "none"),
        "warnings": list(tmap.get("warnings") or []),
        "applicability_tags": extracted.get("applicability_tags") or [],
    }

    if match_factors:
        factor_match = match_strategy_factors(extracted, spec)
        spec = apply_factor_match(spec, factor_match)
        match_path = persist_factor_match(spec.name, factor_match)
        mapping["factor_match"] = factor_match
        mapping["factor_match_path"] = str(match_path)
        if factor_match.get("warnings"):
            mapping["warnings"].extend(factor_match["warnings"])

    mapping["paper_strategy"] = recipe.to_dict()
    return spec, extracted, mapping


def apply_paper_strategy_to_factors(
    recipe_id: str,
    *,
    factor_names: list[str] | None = None,
    factor_slice: str | None = None,
    style: str | None = None,
    max_factors: int | None = None,
    dry_run: bool = True,
    run_backtest: bool = False,
) -> dict[str, Any]:
    """
    Reuse a registered toolbox paper strategy on a different factor set or slice.
    Default dry_run=True: preview factor selection only (no backtest, no KB write).
    When run_backtest=True: backtest + append empirical KB record (factor×strategy cognition).
    """
    from rdagent.scenarios.qlib.strategy.runner import run_strategy_pipeline
    from rdagent.scenarios.qlib.strategy_knowledge.benchmark_grid import bucket_profiles

    recipe = load_paper_strategy(recipe_id)
    spec = recipe_to_strategy_spec(recipe, include_factors=list(factor_names or []))
    if style:
        spec.style = style
    if max_factors is not None:
        spec.max_factors = max_factors
    spec.mode = "single"

    if factor_slice and not factor_names:
        buckets = bucket_profiles(max_per_bucket=max_factors or recipe.max_factors)
        bucket = buckets.get(factor_slice) or []
        spec.include_factors = [str(f["factor_name"]) for f in bucket]
        spec.include_tags = []

    factors = select_factors(spec)
    preview: dict[str, Any] = {
        "recipe_id": recipe_id,
        "paper_strategy_id": recipe.recipe_id,
        "method_id": spec.method,
        "template_id": recipe.template_id,
        "style": spec.style,
        "factor_slice": factor_slice,
        "n_factors": len(factors),
        "factor_names": [f["factor_name"] for f in factors],
        "dry_run": dry_run,
    }
    if dry_run or not run_backtest:
        return preview

    result = run_strategy_pipeline(spec, run_subdir=f"{recipe.recipe_id}_reuse")
    preview["backtest"] = {
        "output_dir": result.get("output_dir"),
        "selection": result.get("selection"),
    }
    preview["dry_run"] = False
    return preview
