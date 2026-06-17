"""Tests for strategy factor matching agent."""

from __future__ import annotations

from rdagent.scenarios.qlib.strategy.spec import StrategySpec
from rdagent.scenarios.qlib.strategy_ingest.factor_matcher import (
    apply_factor_match,
    extract_paper_factor_hints,
    prefilter_candidates,
    summarize_profile_for_matching,
)
from rdagent.scenarios.qlib.strategy.profile_loader import _passes_filters


def test_extract_paper_factor_hints_from_fir_description() -> None:
    extracted = {
        "intent": "FIR fundamental momentum",
        "factor_selection": {
            "description": "六个基本面因子 ROE ROA EPS APE CPA GPA，L=0,1,4,8",
        },
    }
    hints = extract_paper_factor_hints(extracted)
    for token in ("ROE", "ROA", "EPS", "APE", "CPA", "GPA"):
        assert token in hints


def test_summarize_profile_includes_documentation_fields() -> None:
    profile = {
        "factor_name": "盈利因子1",
        "source_type": "fundamental_remote",
        "tags": ["fundamental", "theme:净资产收益率(ROE)"],
        "documentation": {
            "factor_description": "净资产收益率",
            "english_name": "roe_ttm",
            "formula": "净利润/净资产",
        },
        "evaluation": {"icir_pearson": 0.04},
    }
    summary = summarize_profile_for_matching({}, profile)
    assert summary["factor_name"] == "盈利因子1"
    assert "净资产" in summary["factor_description"]
    assert summary["english_name"] == "roe_ttm"


def test_prefilter_candidates_ranks_roe_profile_first() -> None:
    extracted = {
        "factor_selection": {"description": "需要 ROE 和 EPS 因子"},
    }
    profiles = [
        {"factor_name": "无关因子", "source_type": "literature_remote", "tags": [], "factor_description": "volume"},
        {
            "factor_name": "盈利因子1",
            "source_type": "fundamental_remote",
            "tags": ["fundamental", "theme:净资产收益率(ROE)"],
            "factor_description": "净资产收益率 ROE",
            "english_name": "roe",
        },
        {
            "factor_name": "盈利因子2",
            "source_type": "fundamental_remote",
            "tags": ["fundamental", "theme:每股收益(EPS)"],
            "factor_description": "每股收益 EPS",
        },
    ]
    top = prefilter_candidates(extracted, profiles, max_candidates=2)
    names = [p["factor_name"] for p in top]
    assert "盈利因子1" in names
    assert "盈利因子2" in names


def test_apply_factor_match_sets_include_factors_and_clears_tags() -> None:
    spec = StrategySpec(
        name="test",
        include_tags=["fundamental", "value", "profitability"],
    )
    updated = apply_factor_match(
        spec,
        {
            "include_factors": ["盈利因子1", "盈利因子2"],
            "include_tags": ["profitability"],
            "factor_source_types": ["fundamental_remote"],
        },
    )
    assert updated.include_factors == ["盈利因子1", "盈利因子2"]
    assert updated.include_tags == []


def test_profile_loader_skips_include_tags_when_include_factors_set() -> None:
    spec = StrategySpec(include_factors=["盈利因子1"], include_tags=["profitability"])
    profile = {"factor_name": "盈利因子1", "tags": ["fundamental"], "evaluation": {"icir_pearson": 0.05}}
    entry = {"factor_name": "盈利因子1", "source_type": "fundamental_remote"}
    assert _passes_filters(entry, profile, spec) is True

    spec_bad = StrategySpec(include_factors=["盈利因子1"], include_tags=["nonexistent_tag"])
    assert _passes_filters(entry, profile, spec_bad) is True


def test_profile_loader_skips_min_icir_and_barra_when_include_factors_set() -> None:
    spec = StrategySpec(
        include_factors=["盈利因子10"],
        style="small_cap",
        min_icir=0.02,
    )
    profile = {
        "factor_name": "盈利因子10",
        "tags": ["fundamental", "barra:SIZE"],
        "evaluation": {},
        "style_exposure": {
            "dominant_barra_styles": [{"style": "SIZE"}],
        },
    }
    entry = {"factor_name": "盈利因子10", "source_type": "fundamental_remote"}
    assert _passes_filters(entry, profile, spec) is True


def test_apply_factor_match_clears_min_icir() -> None:
    spec = StrategySpec(name="test", min_icir=0.02)
    updated = apply_factor_match(spec, {"include_factors": ["盈利因子1"]})
    assert updated.min_icir is None
