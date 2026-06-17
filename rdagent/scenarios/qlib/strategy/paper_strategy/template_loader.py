"""Load paper strategy templates from strategy_toolbox (repo + E: mirror)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from rdagent.scenarios.qlib.paths import repo_toolbox_root, toolbox_root


def _template_dirs() -> list[Path]:
    dirs: list[Path] = []
    for root in (toolbox_root() / "templates", repo_toolbox_root() / "templates"):
        if root.exists():
            dirs.append(root)
    if not dirs:
        dirs.append(repo_toolbox_root() / "templates")
    return dirs


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid template YAML: {path}")
    return data


@lru_cache(maxsize=1)
def load_paper_strategy_templates() -> dict[str, dict[str, Any]]:
    """template_id → template dict (method_id, default_params, keywords, …)."""
    templates: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()

    for tdir in _template_dirs():
        index_path = tdir / "index.json"
        files: list[Path] = []
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            for name in index.get("templates") or []:
                files.append(tdir / str(name))
        else:
            files = sorted(tdir.glob("*.yaml"))

        for path in files:
            if not path.exists() or path.name == "index.json":
                continue
            meta = _load_yaml(path)
            tid = str(meta.get("template_id") or path.stem)
            if tid in seen:
                continue
            seen.add(tid)
            templates[tid] = meta

    return templates


def list_templates_for_llm() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tid, meta in load_paper_strategy_templates().items():
        out.append(
            {
                "template_id": tid,
                "method_id": meta.get("method_id"),
                "description": meta.get("description") or meta.get("display_name") or tid,
                "default_params": meta.get("default_params") or {},
            }
        )
    return out


def template_catalog_text() -> str:
    lines: list[str] = []
    for tid, meta in load_paper_strategy_templates().items():
        method = meta.get("method_id")
        desc = meta.get("description") or meta.get("display_name") or tid
        lines.append(f"- {tid}: {desc} (method={method})")
    return "\n".join(lines)


def get_template(template_id: str) -> dict[str, Any] | None:
    return load_paper_strategy_templates().get(template_id)


def method_ids_in_catalog() -> set[str]:
    return {str(m.get("method_id")) for m in load_paper_strategy_templates().values() if m.get("method_id")}
