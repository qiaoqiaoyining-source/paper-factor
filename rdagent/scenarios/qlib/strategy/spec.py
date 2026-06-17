"""User strategy requirements: style, risk targets, method mode."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "small_cap": {
        "description": "小市值：偏小盘、低 SIZE 暴露",
        "universe": "small_cap_bottom30",
        "prefer_barra_styles": ["MIDCAP"],
        "avoid_barra_styles": ["SIZE"],
        "size_exposure_max": 0.3,
    },
    "csi300_enh": {
        "description": "沪深300指增：大盘蓝筹池 + 低跟踪误差倾向",
        "universe": "large_cap_top300",
        "prefer_barra_styles": ["BTOP", "EARNYILD"],
        "benchmark_beta_target": 1.0,
    },
    "air_index_enh": {
        "description": "空气指增：低 Beta、市场中性倾向",
        "universe": "all",
        "prefer_barra_styles": ["RESVOL", "MOMENTUM"],
        "avoid_barra_styles": ["BETA"],
        "beta_exposure_max": 0.15,
    },
    "neutral": {
        "description": "全市场多空，无风格预设",
        "universe": "all",
    },
}


@dataclass
class StrategySpec:
    name: str = "custom_strategy"
    style: str = "neutral"
    mode: str = "auto"  # auto | sweep | single
    method: str | None = None  # when mode=single

    min_sharpe: float | None = None
    min_annual_return: float | None = None
    max_drawdown: float | None = None
    max_turnover: float | None = None
    min_icir: float | None = None

    top_frac: float = 0.2
    bottom_frac: float = 0.2
    max_factors: int = 30
    train_frac: float = 0.7

    factor_source_types: list[str] = field(default_factory=lambda: ["literature_remote", "fundamental_remote"])
    include_tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)
    include_factors: list[str] = field(default_factory=list)
    exclude_factors: list[str] = field(default_factory=list)

    methods: list[str] = field(default_factory=list)  # empty = all registered
    output_dir: str | None = None
    data_type: str = "All"

    # Trading frictions (commission + slippage bundled)
    one_way_cost: float = 0.002  # 千二单边；0.0025 = 千二点五
    apply_limit_filter: bool = True
    limit_up_pct: float = 0.095
    limit_down_pct: float = -0.095
    apply_suspended_filter: bool = True

    # Agent-tunable execution knobs (generic primitives; values chosen by strategy agent loop)
    signal_smooth_days: int = 0  # rolling mean per instrument; 0 = off
    hold_buffer_frac: float = 0.0  # cohort hysteresis; e.g. 0.05 keeps names slightly longer
    rebalance_period: int = 1  # trade every N days; 1 = daily

    # Paper strategy toolbox linkage
    method_params: dict[str, Any] = field(default_factory=dict)
    paper_strategy_id: str | None = None
    paper_strategy_recipe_path: str | None = None
    source_report_path: str | None = None

    def friction_config(self) -> "TradingFrictionConfig":
        from rdagent.scenarios.qlib.strategy.trading_friction import TradingFrictionConfig

        return TradingFrictionConfig(
            one_way_cost=self.one_way_cost,
            apply_limit_filter=self.apply_limit_filter,
            limit_up_pct=self.limit_up_pct,
            limit_down_pct=self.limit_down_pct,
            apply_suspended_filter=self.apply_suspended_filter,
        )

    def style_preset(self) -> dict[str, Any]:
        return STYLE_PRESETS.get(self.style, STYLE_PRESETS["neutral"])

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["style_preset"] = self.style_preset()
        return d


def load_strategy_spec(path: Path | str) -> StrategySpec:
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) if path.suffix.lower() in {".yaml", ".yml"} else json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid spec file: {path}")
    known = {f.name for f in StrategySpec.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    kwargs = {k: v for k, v in data.items() if k in known}
    return StrategySpec(**kwargs)


def dump_strategy_spec(spec: StrategySpec, path: Path | str) -> None:
    path = Path(path)
    data = asdict(spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".yaml", ".yml"}:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_spec_patch(spec: StrategySpec, patch: dict[str, Any]) -> StrategySpec:
    """Return a new StrategySpec with validated patch fields merged."""
    if not patch:
        return spec
    known = {f.name for f in StrategySpec.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    base = asdict(spec)
    for key, value in patch.items():
        if key not in known:
            continue
        base[key] = value
    return StrategySpec(**base)
