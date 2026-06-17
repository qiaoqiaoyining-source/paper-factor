"""Paper strategy recipe schema — portable strategy definition for toolbox + KB."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rdagent.scenarios.qlib.strategy.spec import StrategySpec

_REBALANCE_DAYS = {"daily": 1, "weekly": 5, "monthly": 20}


def slugify(text: str, *, max_len: int = 48) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", str(text).strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:max_len] or "paper_strategy").lower()


@dataclass
class PaperStrategyRecipe:
    """Executable paper strategy stored in toolbox."""

    recipe_id: str
    display_name: str
    method_id: str
    template_id: str
    params: dict[str, Any] = field(default_factory=dict)
    style: str = "neutral"
    top_frac: float = 0.2
    bottom_frac: float = 0.2
    rebalance_period: int = 20
    train_frac: float = 0.7
    max_factors: int = 30
    source_report: str = ""
    source_report_title: str = ""
    combination_description: str = ""
    intent: str = ""
    applicability_tags: list[str] = field(default_factory=list)
    mapping_notes: list[str] = field(default_factory=list)
    matcher: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperStrategyRecipe:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


def recipe_to_strategy_spec(
    recipe: PaperStrategyRecipe,
    *,
    include_factors: list[str] | None = None,
    factor_source_types: list[str] | None = None,
) -> StrategySpec:
    from rdagent.scenarios.qlib.strategy.registry import resolve_method_id, resolve_method_params

    method_id = resolve_method_id(recipe.method_id)
    params = resolve_method_params(recipe.method_id, recipe.params)
    return StrategySpec(
        name=recipe.display_name,
        style=recipe.style,
        mode="single",
        method=method_id,
        method_params=params,
        top_frac=recipe.top_frac,
        bottom_frac=recipe.bottom_frac,
        rebalance_period=recipe.rebalance_period,
        train_frac=recipe.train_frac,
        max_factors=recipe.max_factors,
        min_icir=None,
        include_factors=list(include_factors or []),
        include_tags=[],
        factor_source_types=list(factor_source_types or ["fundamental_remote", "literature_remote"]),
        paper_strategy_id=recipe.recipe_id,
        paper_strategy_recipe_path="",
        source_report_path=recipe.source_report,
    )


def portfolio_from_extracted(extracted: dict[str, Any]) -> dict[str, Any]:
    portfolio = extracted.get("portfolio") or {}
    style = str(portfolio.get("style") or "neutral")
    if style not in {"small_cap", "csi300_enh", "air_index_enh", "neutral"}:
        style = "neutral"
    rebalance = str(portfolio.get("rebalance") or "monthly").lower()
    return {
        "style": style,
        "top_frac": float(portfolio.get("top_frac") or 0.2),
        "bottom_frac": float(portfolio.get("bottom_frac") or 0.2),
        "rebalance_period": _REBALANCE_DAYS.get(rebalance, 20),
    }


def dump_recipe(recipe: PaperStrategyRecipe, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recipe.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_recipe(path: Path | str) -> PaperStrategyRecipe:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return PaperStrategyRecipe.from_dict(data)
