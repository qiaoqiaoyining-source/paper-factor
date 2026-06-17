"""Run strategy sweep (Method 2) and auto-select (Method 1)."""

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from rdagent.scenarios.qlib.strategy.backtest import (
    compute_performance_metrics,
    meets_constraints,
    score_against_spec,
    signal_to_long_short_returns,
)
from rdagent.scenarios.qlib.strategy.data import (
    apply_universe_mask,
    build_factor_matrix,
    load_forward_returns,
    load_market_panel,
    train_test_split_dates,
)
from rdagent.scenarios.qlib.strategy.methods import MethodContext
from rdagent.scenarios.qlib.strategy.profile_loader import select_factors
from rdagent.scenarios.qlib.strategy.registry import get_methods, list_method_catalog, list_method_catalog_extended
from rdagent.scenarios.qlib.strategy.selector import select_best_method
from rdagent.scenarios.qlib.strategy.signal_preprocess import preprocess_signal
from rdagent.scenarios.qlib.paths import repo_toolbox_root, strategy_runs_root, toolbox_root as e_toolbox_root
from rdagent.scenarios.qlib.strategy.spec import StrategySpec


def default_output_root() -> Path:
    return strategy_runs_root()


def default_toolbox_root() -> Path:
    return e_toolbox_root()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evaluate_method_on_test(
    signal: pd.Series,
    label: pd.Series,
    spec: StrategySpec,
    train_frac: float,
    market: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], pd.Series]:
    dates = signal.index.get_level_values("datetime").unique()
    _, test_dates = train_test_split_dates(dates, train_frac)
    sig_test = signal.loc[pd.IndexSlice[test_dates, :]]
    sig_test = preprocess_signal(sig_test, spec)
    lab_test = label.reindex(sig_test.index)
    mkt_test = market.loc[pd.IndexSlice[test_dates, :]] if market is not None else None
    net, gross, meta = signal_to_long_short_returns(
        sig_test,
        lab_test,
        top_frac=spec.top_frac,
        bottom_frac=spec.bottom_frac,
        hold_buffer_frac=spec.hold_buffer_frac,
        rebalance_period=spec.rebalance_period,
        market=mkt_test,
        friction=spec.friction_config(),
    )
    metrics = compute_performance_metrics(
        net,
        turnover_mean=meta.get("turnover_mean"),
        gross_daily=gross,
        friction_meta=meta,
    )
    return metrics, net


def run_method_sweep(
    spec: StrategySpec,
    *,
    factors: list[dict[str, Any]] | None = None,
    method_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    factors = factors or select_factors(spec)
    if not factors:
        raise ValueError("No factors selected; relax min_icir or style filters")

    market = load_market_panel(spec.data_type)
    label = load_forward_returns(spec.data_type)
    panel = build_factor_matrix(factors)
    panel = apply_universe_mask(panel, spec, market)

    ctx = MethodContext(
        panel=panel,
        label=label,
        factors=factors,
        train_frac=spec.train_frac,
        extra=dict(spec.method_params or {}),
    )
    methods = get_methods(method_ids or spec.methods or None)
    results: list[dict[str, Any]] = []

    for method in methods:
        try:
            out = method.fit_predict(ctx)
            metrics, daily = _evaluate_method_on_test(out.signal, label, spec, spec.train_frac, market=market)
            results.append(
                {
                    "method_id": out.method_id,
                    "description": method.description,
                    "metrics": metrics,
                    "meets_constraints": meets_constraints(metrics, spec),
                    "score": score_against_spec(metrics, spec),
                    "factor_weights": out.weights,
                    "method_meta": out.meta,
                    "n_factors": len(factors),
                    "factor_names": [f["factor_name"] for f in factors],
                    "daily_returns_sample": daily.tail(5).tolist() if len(daily) else [],
                }
            )
            print(f"OK method {out.method_id} sharpe={metrics.get('sharpe_annualized')} mdd={metrics.get('max_drawdown')}")
        except Exception as exc:  # noqa: BLE001
            print(f"ERR method {method.id}: {exc}")
            results.append(
                {
                    "method_id": method.id,
                    "status": "error",
                    "error": str(exc),
                    "traceback": traceback.format_exc()[-800:],
                }
            )
    return results


def run_strategy_pipeline(spec: StrategySpec, *, run_subdir: str | None = None) -> dict[str, Any]:
    out_root = Path(spec.output_dir) if spec.output_dir else default_output_root()
    if run_subdir:
        run_dir = out_root / run_subdir
    else:
        run_dir = out_root / f"{spec.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    factors = select_factors(spec)
    (run_dir / "selected_factors.json").write_text(
        json.dumps(factors, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    catalog = list_method_catalog_extended()
    (run_dir / "method_catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if spec.mode == "single" and spec.method:
        sweep = run_method_sweep(spec, factors=factors, method_ids=[spec.method])
        selection = {"status": "single", "selected_method": spec.method, "selected_result": sweep[0] if sweep else None}
    elif spec.mode == "sweep":
        sweep = run_method_sweep(spec, factors=factors)
        selection = {"status": "sweep_only", "results": sweep}
    else:
        sweep = run_method_sweep(spec, factors=factors)
        selection = select_best_method(sweep, spec)

    payload = {
        "updated_at": _now_iso(),
        "spec": spec.to_dict(),
        "n_factors": len(factors),
        "sweep_results": sweep,
        "selection": selection,
        "output_dir": str(run_dir),
    }
    (run_dir / "strategy_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    toolbox = default_toolbox_root()
    toolbox.mkdir(parents=True, exist_ok=True)
    (toolbox / "method_catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    (toolbox / "latest_run.json").write_text(
        json.dumps({"run_dir": str(run_dir), "selection": selection, "updated_at": _now_iso()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _persist_knowledge_record(payload, spec, factors)

    print(f"Wrote strategy run: {run_dir}")
    if selection.get("selected_method"):
        print(f"Selected method: {selection['selected_method']}")
    return payload


def _persist_knowledge_record(payload: dict[str, Any], spec: StrategySpec, factors: list[dict[str, Any]]) -> None:
    """Write empirical KB record after each strategy run."""
    try:
        from rdagent.scenarios.qlib.strategy_knowledge.benchmark_grid import resolve_factor_slice
        from rdagent.scenarios.qlib.strategy_knowledge.store import append_record, rebuild_matrix_summary, record_from_strategy_run

        tags: list[str] = []
        for f in factors:
            tags.extend(f.get("tags") or [])
        slice_id = resolve_factor_slice(tags=tags, source_type=str(spec.factor_source_types[0] if spec.factor_source_types else ""))
        method_id = (payload.get("selection") or {}).get("selected_method") or spec.method or "sweep"
        record = record_from_strategy_run(
            payload,
            factor_slice=slice_id,
            style=spec.style,
            method_id=str(method_id),
            source="strategy_run" if not spec.paper_strategy_id else "paper_strategy_run",
        )
        record["factor_slice"] = slice_id
        append_record(record)
        rebuild_matrix_summary()
    except Exception as exc:  # noqa: BLE001
        print(f"strategy_knowledge: skip record ({exc})", flush=True)


def sync_toolbox_to_e() -> Path:
    """Copy spec templates, paper templates, methods schema + agent knowledge to E: strategy_toolbox."""
    import shutil

    src = repo_toolbox_root()
    dst = default_toolbox_root()
    dst.mkdir(parents=True, exist_ok=True)

    for sub in ("specs", "knowledge", "templates", "methods"):
        src_sub = src / sub
        if not src_sub.exists():
            continue
        dst_sub = dst / sub
        if dst_sub.exists():
            shutil.rmtree(dst_sub)
        shutil.copytree(src_sub, dst_sub)

    # Empirical KB taxonomy template on E:
    from rdagent.scenarios.qlib.paths import strategy_knowledge_root

    kb_root = strategy_knowledge_root()
    kb_root.mkdir(parents=True, exist_ok=True)
    tax_src = Path(__file__).resolve().parents[1] / "strategy_knowledge" / "taxonomy.yaml"
    if tax_src.exists():
        shutil.copy2(tax_src, kb_root / "taxonomy.yaml")

    from rdagent.scenarios.qlib.strategy.registry import list_method_catalog_extended

    catalog = list_method_catalog_extended()
    (dst / "method_catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    readme = """# Strategy Toolbox (E:)

- specs/ — YAML strategy requirements (style, sharpe, drawdown, turnover)
- templates/ — paper strategy templates (map report → method + params)
- methods/ — generic method param schemas (e.g. cross_section_walk_forward)
- paper_strategies/ — registered paper recipes (*.recipe.json) from strategy-ingest
- knowledge/ — Agent PLAYBOOK + knobs

Empirical KB (factor×method×style results) lives in sibling folder:
  ../strategy_knowledge/

Workflow:
  1. strategy-ingest --report-file ... → recipe in paper_strategies/ + factor match + backtest
  2. strategy-knowledge apply-recipe --recipe-id ... --factors ... (--run to backtest + KB)

Run from WSL:
  python -m factor_strategy_agent_cli.main strategy --spec /mnt/remote_e/_paper_factor_unified/strategy_toolbox/specs/small_cap.yaml
"""
    (dst / "README.md").write_text(readme, encoding="utf-8")
    return dst
