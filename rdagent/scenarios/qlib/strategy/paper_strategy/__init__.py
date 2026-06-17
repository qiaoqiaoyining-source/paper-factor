"""Paper strategy recipes: extract → toolbox → backtest → knowledge base."""

from rdagent.scenarios.qlib.strategy.paper_strategy.pipeline import (
    apply_paper_strategy_to_factors,
    ingest_paper_strategy_report,
)
from rdagent.scenarios.qlib.strategy.paper_strategy.recipe import PaperStrategyRecipe, recipe_to_strategy_spec
from rdagent.scenarios.qlib.strategy.paper_strategy.store import load_paper_strategy, register_paper_strategy

__all__ = [
    "PaperStrategyRecipe",
    "recipe_to_strategy_spec",
    "register_paper_strategy",
    "load_paper_strategy",
    "ingest_paper_strategy_report",
    "apply_paper_strategy_to_factors",
]
