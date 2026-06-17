"""Load factor profiles and filter by user spec."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from rdagent.scenarios.qlib.strategy.spec import StrategySpec

from rdagent.scenarios.qlib.paths import profile_root as unified_profile_root

DEFAULT_PROFILE_ROOT = unified_profile_root()


def load_profiles_index(profile_root: Path | None = None) -> dict[str, Any]:
    root = profile_root or DEFAULT_PROFILE_ROOT
    index_path = root / "profiles_index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"Missing profiles index: {index_path}")
    return json.loads(index_path.read_text(encoding="utf-8"))


def load_profile(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _passes_filters(entry: dict[str, Any], profile: dict[str, Any], spec: StrategySpec) -> bool:
    name = str(entry.get("factor_name") or profile.get("factor_name") or "")
    tags = set(profile.get("tags") or entry.get("tags") or [])
    source = str(profile.get("source_type") or entry.get("source_type") or "")

    if spec.factor_source_types and source not in spec.factor_source_types:
        return False

    if spec.include_factors:
        if name not in spec.include_factors:
            return False
    elif spec.include_tags:
        for t in spec.include_tags:
            if t not in tags:
                return False

    if name in spec.exclude_factors:
        return False
    for t in spec.exclude_tags:
        if t in tags:
            return False

    # Agent/user explicitly picked factors — skip quality/style gates until profiles are complete.
    if spec.include_factors:
        return True

    ev = profile.get("evaluation") or {}
    if spec.min_icir is not None:
        icir = ev.get("icir_pearson")
        if icir is None or abs(float(icir)) < spec.min_icir:
            return False

    preset = spec.style_preset()
    avoid = preset.get("avoid_barra_styles") or []
    if avoid:
        style_exp = profile.get("style_exposure") or {}
        dom = {d.get("style") for d in (style_exp.get("dominant_barra_styles") or []) if isinstance(d, dict)}
        dom |= {k for k, v in (style_exp.get("style_beta_mean") or {}).items() if v and abs(float(v)) > 0.05}
        if dom & set(avoid):
            return False

    return True


def _score_factor(entry: dict[str, Any], profile: dict[str, Any], spec: StrategySpec) -> float:
    ev = profile.get("evaluation") or {}
    icir = abs(float(ev.get("icir_pearson") or 0.0))
    sharpe = abs(float(ev.get("ls_sharpe_annualized") or 0.0))
    score = icir * 2.0 + sharpe * 0.5

    preset = spec.style_preset()
    prefer = set(preset.get("prefer_barra_styles") or [])
    style_exp = profile.get("style_exposure") or {}
    for item in style_exp.get("dominant_barra_styles") or []:
        if isinstance(item, dict) and item.get("style") in prefer:
            score += 0.3

    tags = set(profile.get("tags") or [])
    if "fundamental" in tags and spec.style in {"csi300_enh"}:
        score += 0.2
    if spec.style == "small_cap" and "barra:SIZE" not in tags:
        score += 0.1

    return score


def select_factors(spec: StrategySpec, profile_root: Path | None = None) -> list[dict[str, Any]]:
    index = load_profiles_index(profile_root)
    root = Path(index.get("profile_root") or profile_root or DEFAULT_PROFILE_ROOT)
    selected: list[tuple[float, dict[str, Any]]] = []

    for entry in index.get("factors") or []:
        profile_path = Path(str(entry.get("profile_path") or ""))
        if not profile_path.exists():
            profile_path = root / profile_path.name
        if not profile_path.exists():
            continue
        profile = load_profile(profile_path)
        if not _passes_filters(entry, profile, spec):
            continue
        score = _score_factor(entry, profile, spec)
        parquet = (profile.get("data") or {}).get("values_parquet")
        if not parquet:
            continue
        selected.append(
            (
                score,
                {
                    "factor_name": profile.get("factor_name") or entry.get("factor_name"),
                    "profile_path": str(profile_path),
                    "parquet_path": str(parquet),
                    "score": score,
                    "icir_pearson": (profile.get("evaluation") or {}).get("icir_pearson"),
                    "tags": profile.get("tags"),
                    "documentation": profile.get("documentation"),
                    "style_exposure": profile.get("style_exposure"),
                },
            )
        )

    selected.sort(key=lambda x: x[0], reverse=True)
    cap = spec.max_factors if not spec.include_factors else len(selected)
    return [item for _, item in selected[:cap]]
