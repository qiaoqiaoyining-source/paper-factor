"""Paper strategy templates — YAML on strategy_toolbox, not hardcoded per-paper logic."""

from __future__ import annotations

from typing import Any

from rdagent.scenarios.qlib.strategy.paper_strategy.template_loader import (
    get_template,
    list_templates_for_llm,
    load_paper_strategy_templates,
    template_catalog_text,
)

__all__ = [
    "get_template",
    "list_templates_for_llm",
    "load_paper_strategy_templates",
    "template_catalog_text",
]


def __getattr__(name: str) -> Any:
    if name == "PAPER_STRATEGY_TEMPLATES":
        return load_paper_strategy_templates()
    raise AttributeError(name)
