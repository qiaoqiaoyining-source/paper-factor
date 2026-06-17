"""Unified E: drive paths for factor_strategy_agent."""

from __future__ import annotations

import os
from pathlib import Path


def _env_path(*keys: str, default: str) -> Path:
    for key in keys:
        raw = os.environ.get(key)
        if raw and str(raw).strip():
            return Path(str(raw).strip())
    return Path(default)


def unified_root() -> Path:
    """Remote unified data root on E: (factor profiles, toolbox, knowledge, runs)."""
    return _env_path(
        "FACTOR_STRATEGY_AGENT_UNIFIED_ROOT",
        "PAPER_FACTOR_UNIFIED_ROOT",
        default="/mnt/remote_e/_paper_factor_unified",
    )


def profile_root() -> Path:
    return _env_path(
        "FACTOR_STRATEGY_AGENT_PROFILE_ROOT",
        "PAPER_FACTOR_PROFILE_ROOT",
        default=str(unified_root() / "factor_profiles"),
    )


def toolbox_root() -> Path:
    return unified_root() / "strategy_toolbox"


def strategy_knowledge_root() -> Path:
    """Empirical KB: factor_type × method × style experiment records."""
    return unified_root() / "strategy_knowledge"


def strategy_runs_root() -> Path:
    return unified_root() / "strategy_runs"


def paper_strategies_root() -> Path:
    return strategy_knowledge_root() / "paper_strategies"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def repo_toolbox_root() -> Path:
    return repo_root() / "strategy_toolbox"


def repo_agent_knowledge_root() -> Path:
    return repo_toolbox_root() / "knowledge"


def resolve_agent_knowledge_root() -> Path:
    """Agent PLAYBOOK/knobs: prefer E: strategy_toolbox/knowledge, else repo copy."""
    env = os.environ.get("STRATEGY_KNOWLEDGE_ROOT")
    if env:
        return Path(env)
    remote = toolbox_root() / "knowledge"
    if remote.exists():
        return remote
    return repo_agent_knowledge_root()
