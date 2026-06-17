"""Registry of all strategy combination methods (Method 2 toolbox)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rdagent.scenarios.qlib.strategy.methods import (
    ConstrainedLinearOptimizerMethod,
    CrossSectionOLSComboMethod,
    CrossSectionWalkForwardMethod,
    GradientBoostMethod,
    GRUMethod,
    ICWeightedLinearMethod,
    LassoComboMethod,
    LSTMMethod,
    RandomForestMethod,
    RankAverageMethod,
    RidgeComboMethod,
    StrategyMethod,
)

METHOD_REGISTRY: dict[str, StrategyMethod] = {}

# Legacy paper recipe method ids → generic engine (params live in toolbox recipe)
METHOD_ID_ALIASES: dict[str, tuple[str, dict[str, Any]]] = {
    "fir_multivariate_regression": (
        "cross_section_walk_forward",
        {"combination": "multivariate", "resample": "monthly", "ma_windows": [0, 1, 4, 8]},
    ),
    "fir_forecast_combination": (
        "cross_section_walk_forward",
        {"combination": "per_factor_equal", "resample": "monthly", "ma_windows": [0, 1, 4, 8]},
    ),
}


def resolve_method_id(method_id: str) -> str:
    return METHOD_ID_ALIASES.get(method_id, (method_id, {}))[0]


def resolve_method_params(method_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(params or {})
    if method_id in METHOD_ID_ALIASES:
        _, defaults = METHOD_ID_ALIASES[method_id]
        for k, v in defaults.items():
            merged.setdefault(k, v)
    return merged


@dataclass
class MethodMeta:
    id: str
    description: str
    method_type: str  # linear | ml | dl | ensemble
    min_factors: int = 2
    requires_torch: bool = False
    prefer_tags: list[str] = field(default_factory=list)
    avoid_tags: list[str] = field(default_factory=list)
    typical_use: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "method_type": self.method_type,
            "min_factors": self.min_factors,
            "requires_torch": self.requires_torch,
            "prefer_tags": self.prefer_tags,
            "avoid_tags": self.avoid_tags,
            "typical_use": self.typical_use,
        }


METHOD_META: dict[str, MethodMeta] = {
    "rank_average": MethodMeta(
        "rank_average",
        "Cross-sectional rank average",
        "linear",
        prefer_tags=["literature"],
        typical_use="多因子等权秩平均，稳健基线",
    ),
    "ic_weighted_linear": MethodMeta(
        "ic_weighted_linear",
        "ICIR-weighted linear combo",
        "linear",
        prefer_tags=["fundamental", "value"],
        typical_use="基本面因子 IC 加权",
    ),
    "constrained_linear_opt": MethodMeta(
        "constrained_linear_opt",
        "Constrained max-Sharpe weights",
        "linear",
        prefer_tags=["fundamental"],
        typical_use="有约束的线性配权",
    ),
    "ridge_regression": MethodMeta("ridge_regression", "Ridge combo", "ml", typical_use="因子共线性较强时"),
    "lasso_regression": MethodMeta(
        "lasso_regression",
        "Lasso sparse selection",
        "ml",
        prefer_tags=["fundamental"],
        typical_use="稀疏因子选择",
    ),
    "gradient_boosting": MethodMeta("gradient_boosting", "GBDT combo", "ml", typical_use="非线性组合"),
    "random_forest": MethodMeta("random_forest", "Random forest combo", "ml"),
    "lstm": MethodMeta("lstm", "LSTM", "dl", requires_torch=True, min_factors=5),
    "gru": MethodMeta("gru", "GRU", "dl", requires_torch=True, min_factors=5),
    "cross_section_walk_forward": MethodMeta(
        "cross_section_walk_forward",
        "Walk-forward cross-section OLS with configurable MA lags",
        "linear",
        prefer_tags=["fundamental"],
        typical_use="研报复现：参数由 toolbox paper_strategies/*.recipe.json 定义",
    ),
    "cross_section_ols_combo": MethodMeta(
        "cross_section_ols_combo",
        "Pooled cross-section OLS combo",
        "linear",
        typical_use="横截面 OLS 线性组合",
    ),
}


def _register(method: StrategyMethod) -> StrategyMethod:
    METHOD_REGISTRY[method.id] = method
    return method


def get_all_methods() -> dict[str, StrategyMethod]:
    if not METHOD_REGISTRY:
        for cls in (
            RankAverageMethod,
            ICWeightedLinearMethod,
            ConstrainedLinearOptimizerMethod,
            CrossSectionWalkForwardMethod,
            CrossSectionOLSComboMethod,
            RidgeComboMethod,
            LassoComboMethod,
            GradientBoostMethod,
            RandomForestMethod,
            LSTMMethod,
            GRUMethod,
        ):
            _register(cls())
    return METHOD_REGISTRY


def get_method_meta(method_id: str) -> MethodMeta | None:
    resolved = resolve_method_id(method_id)
    return METHOD_META.get(resolved) or METHOD_META.get(method_id)


def list_method_catalog() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in get_all_methods().values():
        row = {"id": m.id, "description": m.description}
        meta = METHOD_META.get(m.id)
        if meta:
            row.update({k: str(v) for k, v in meta.to_dict().items() if k not in row})
        out.append(row)
    return out


def list_method_catalog_extended() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for m in get_all_methods().values():
        meta = METHOD_META.get(m.id)
        catalog.append(meta.to_dict() if meta else {"id": m.id, "description": m.description})
    return catalog


def get_methods(method_ids: list[str] | None = None) -> list[StrategyMethod]:
    all_m = get_all_methods()
    if not method_ids:
        return list(all_m.values())
    out: list[StrategyMethod] = []
    seen: set[str] = set()
    for mid in method_ids:
        resolved = resolve_method_id(mid)
        if resolved in all_m and resolved not in seen:
            out.append(all_m[resolved])
            seen.add(resolved)
    return out
