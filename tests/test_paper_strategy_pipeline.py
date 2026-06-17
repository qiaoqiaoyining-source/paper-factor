"""Tests for paper strategy template mapping and recipe store."""

from __future__ import annotations

from pathlib import Path

import pytest

from rdagent.scenarios.qlib.strategy.paper_strategy.recipe import PaperStrategyRecipe, recipe_to_strategy_spec, slugify
from rdagent.scenarios.qlib.strategy.paper_strategy.template_loader import load_paper_strategy_templates
from rdagent.scenarios.qlib.strategy.paper_strategy.template_mapper import build_recipe_from_extract, map_extract_to_template
from rdagent.scenarios.qlib.strategy.registry import get_all_methods, resolve_method_id


def test_slugify_chinese_name():
    assert slugify("基本面动量策略") == "基本面动量策略"


def test_templates_loaded_from_toolbox_yaml():
    templates = load_paper_strategy_templates()
    assert "fundamental_momentum_fir_multivariate" in templates
    assert templates["fundamental_momentum_fir_multivariate"]["method_id"] == "cross_section_walk_forward"


def test_map_fir_multivariate_from_extract():
    extracted = {
        "strategy_name": "基本面动量策略",
        "combination": {
            "description": "基本面隐含收益率 FIR 多元横截面回归，MA 滞后 L=0,1,4,8",
            "novelty": "new_method",
            "method_id": None,
        },
        "portfolio": {"style": "neutral", "rebalance": "monthly", "top_frac": 0.2},
    }
    template_id, method_id, params, meta = map_extract_to_template(extracted)
    assert template_id == "fundamental_momentum_fir_multivariate"
    assert method_id == "cross_section_walk_forward"
    assert params.get("ma_windows") == [0, 1, 4, 8]
    assert params.get("combination") == "multivariate"
    assert meta.get("notes")


def test_map_fir_forecast_combination():
    extracted = {
        "strategy_name": "FIR combo",
        "combination": {"description": "FIR 预测组合法 单因子回归后等权"},
    }
    template_id, method_id, params, _ = map_extract_to_template(extracted)
    assert template_id == "fundamental_momentum_fir_forecast_combo"
    assert method_id == "cross_section_walk_forward"
    assert params.get("combination") == "per_factor_equal"


def test_build_recipe_and_spec():
    extracted = {
        "strategy_name": "基本面动量策略",
        "combination": {"description": "FIR 多元回归"},
        "portfolio": {"rebalance": "monthly"},
    }
    template_id, method_id, params, meta = map_extract_to_template(extracted)
    recipe = build_recipe_from_extract(
        extracted,
        report_path="/tmp/paper.pdf",
        template_id=template_id,
        method_id=method_id,
        params=params,
        mapping_meta=meta,
    )
    assert isinstance(recipe, PaperStrategyRecipe)
    assert recipe.method_id == "cross_section_walk_forward"
    assert recipe.template_id == "fundamental_momentum_fir_multivariate"
    assert recipe.rebalance_period == 20
    spec = recipe_to_strategy_spec(recipe, include_factors=["盈利因子3"])
    assert spec.method == "cross_section_walk_forward"
    assert spec.method_params.get("combination") == "multivariate"
    assert spec.include_factors == ["盈利因子3"]
    assert spec.paper_strategy_id == recipe.recipe_id


def test_generic_walk_forward_registered():
    methods = get_all_methods()
    assert "cross_section_walk_forward" in methods
    assert "cross_section_ols_combo" in methods
    assert "fir_multivariate_regression" not in methods


def test_legacy_method_id_resolves():
    assert resolve_method_id("fir_multivariate_regression") == "cross_section_walk_forward"
