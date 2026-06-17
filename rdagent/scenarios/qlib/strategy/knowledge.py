"""Strategy knowledge base: playbooks, tunable knobs, lessons learned."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from rdagent.scenarios.qlib.paths import resolve_agent_knowledge_root, toolbox_root


def resolve_knowledge_root() -> Path:
    """Agent PLAYBOOK/knobs root (E: strategy_toolbox/knowledge preferred)."""
    return resolve_agent_knowledge_root()


def load_knobs(path: Path | None = None) -> dict[str, Any]:
    root = path or resolve_knowledge_root()
    knobs_path = root / "knobs.json"
    if not knobs_path.exists():
        return {"knobs": [], "version": 0}
    return json.loads(knobs_path.read_text(encoding="utf-8"))


def load_playbook(path: Path | None = None) -> str:
    root = path or resolve_knowledge_root()
    md = root / "PLAYBOOK.md"
    if md.exists():
        return md.read_text(encoding="utf-8")
    return ""


def load_recent_lessons(path: Path | None = None, limit: int = 8) -> list[dict[str, Any]]:
    root = path or resolve_knowledge_root()
    lessons_path = root / "lessons_learned.jsonl"
    if not lessons_path.exists():
        return []
    lines = [ln.strip() for ln in lessons_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out: list[dict[str, Any]] = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def append_lesson(lesson: dict[str, Any], path: Path | None = None) -> Path:
    root = path or resolve_knowledge_root()
    root.mkdir(parents=True, exist_ok=True)
    lessons_path = root / "lessons_learned.jsonl"
    row = {"recorded_at": datetime.now().isoformat(timespec="seconds"), **lesson}
    with lessons_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return lessons_path


def allowed_patch_keys(knobs_doc: dict[str, Any] | None = None) -> set[str]:
    doc = knobs_doc or load_knobs()
    return {item["key"] for item in doc.get("knobs") or [] if item.get("key")}


def validate_spec_patch(patch: dict[str, Any], knobs_doc: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    """Filter patch to allowed keys and basic type/range checks from knobs.json."""
    doc = knobs_doc or load_knobs()
    allowed = {item["key"]: item for item in doc.get("knobs") or [] if item.get("key")}
    clean: dict[str, Any] = {}
    warnings: list[str] = []

    for key, value in (patch or {}).items():
        if key not in allowed:
            warnings.append(f"ignored unknown knob: {key}")
            continue
        meta = allowed[key]
        if "enum" in meta and value not in meta["enum"]:
            warnings.append(f"ignored {key}={value!r}; not in enum {meta['enum']}")
            continue
        if meta.get("type") == "list":
            if not isinstance(value, list):
                warnings.append(f"ignored {key}; expected list")
                continue
            clean[key] = value
            continue
        if isinstance(value, (int, float)) and meta.get("type") in {"int", "float"}:
            lo, hi = meta.get("min"), meta.get("max")
            if lo is not None and value < lo:
                warnings.append(f"clamped {key} from {value} to min {lo}")
                value = lo
            if hi is not None and value > hi:
                warnings.append(f"clamped {key} from {value} to max {hi}")
                value = hi
        if meta.get("type") == "int" and isinstance(value, float):
            value = int(value)
        clean[key] = value
    return clean, warnings


def build_agent_context(
    *,
    user_goal: str = "",
    spec_dict: dict | None = None,
    factor_tags: list[str] | None = None,
    source_type: str | None = None,
    style: str | None = None,
    use_empirical_kb: bool = True,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "user_goal": user_goal,
        "playbook_excerpt": load_playbook()[:12000],
        "knobs": load_knobs(),
        "recent_lessons": load_recent_lessons(),
        "current_spec": spec_dict or {},
        "toolbox_root": str(toolbox_root()),
    }
    if use_empirical_kb:
        try:
            from rdagent.scenarios.qlib.strategy_knowledge.query import build_planner_context

            ctx["empirical_kb"] = build_planner_context(
                factor_tags=factor_tags,
                source_type=source_type,
                style=style or (spec_dict or {}).get("style") or "neutral",
                user_goal=user_goal,
            )
        except Exception as exc:  # noqa: BLE001
            ctx["empirical_kb"] = {"error": str(exc)}
    return ctx
