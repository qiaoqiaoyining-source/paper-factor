"""Persist paper strategy recipes to toolbox + knowledge paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rdagent.scenarios.qlib.paths import paper_strategies_root, toolbox_root
from rdagent.scenarios.qlib.strategy.paper_strategy.recipe import PaperStrategyRecipe, dump_recipe, load_recipe


def _index_path(root: Path) -> Path:
    return root / "index.json"


def _load_index(root: Path) -> dict[str, Any]:
    path = _index_path(root)
    if not path.exists():
        return {"recipes": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_index(root: Path, index: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _index_path(root).write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def register_paper_strategy(recipe: PaperStrategyRecipe) -> dict[str, str]:
    """Write recipe to toolbox (canonical). KB keeps extracted artifacts separately."""
    tb_dir = toolbox_root() / "paper_strategies"
    paths: dict[str, str] = {}
    tb_dir.mkdir(parents=True, exist_ok=True)
    path = tb_dir / f"{recipe.recipe_id}.recipe.json"
    dump_recipe(recipe, path)
    paths[str(tb_dir)] = str(path)

    index = _load_index(tb_dir)
    entries = {e.get("recipe_id"): e for e in index.get("recipes") or []}
    entries[recipe.recipe_id] = {
        "recipe_id": recipe.recipe_id,
        "display_name": recipe.display_name,
        "method_id": recipe.method_id,
        "template_id": recipe.template_id,
        "source_report": recipe.source_report,
    }
    index["recipes"] = sorted(entries.values(), key=lambda x: str(x.get("recipe_id")))
    _save_index(tb_dir, index)
    return paths


def load_paper_strategy(recipe_id: str) -> PaperStrategyRecipe:
    for root in (toolbox_root() / "paper_strategies", paper_strategies_root()):
        path = root / f"{recipe_id}.recipe.json"
        if path.exists():
            return load_recipe(path)
    raise FileNotFoundError(f"Paper strategy recipe not found: {recipe_id}")


def list_paper_strategies() -> list[dict[str, Any]]:
    tb_dir = toolbox_root() / "paper_strategies"
    index = _load_index(tb_dir)
    return list(index.get("recipes") or [])
