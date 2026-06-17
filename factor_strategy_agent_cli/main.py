"""factor_strategy_agent CLI —研报因子 + 策略 toolbox + 实证知识库."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from typing_extensions import Annotated

from rdagent.oai.token_usage import echo_token_usage, reset_token_session
from rdagent.scenarios.qlib.paths import strategy_knowledge_root, toolbox_root, unified_root

load_dotenv(".env")

app = typer.Typer(help="factor_strategy_agent: papers → factors → strategy toolbox + empirical KB.")

DEFAULT_PAPER_REPORT_FOLDER = str(Path.cwd() / "papers" / "inbox")
CheckoutOption = Annotated[bool, typer.Option("--checkout/--no-checkout", "-c/-C")]


@contextmanager
def _temporary_env(**updates: object):
    old_values = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _auto_init_workspace(*, download_missing: bool = False) -> None:
    if download_missing:
        from rdagent.app.utils.init_workspace import init_workspace

        init_workspace(force=False)
    else:
        from rdagent.app.utils.init_workspace import validate_workspace_ready

        validate_workspace_ready(require_factor_data=True)


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _finish_llm_session(label: str) -> None:
    echo_token_usage(label=label)


def _run_post_factor_analysis(
    *,
    post_analyze: bool,
    post_analyze_agent: bool,
    accepted_only: bool,
    barra_model: str,
    barra_dir: Optional[str],
    data_type: str,
) -> None:
    if not post_analyze:
        return
    from rdagent.app.qlib_rd_loop.factor_portfolio_analyze import run_post_export_analysis

    run_post_export_analysis(
        accepted_only=accepted_only,
        data_type=data_type,
        barra_model=barra_model,
        with_agent=post_analyze_agent,
        barra_dir=barra_dir,
        allow_empty=True,
        echo_summary=True,
    )


@app.command(name="paths")
def show_paths() -> None:
    """Show E: drive layout for toolbox and knowledge bases."""
    typer.echo(f"Unified root (E:):     {unified_root()}")
    typer.echo(f"Strategy toolbox:      {toolbox_root()}")
    typer.echo(f"Empirical KB:          {strategy_knowledge_root()}")
    typer.echo(f"  paper_strategies:    {strategy_knowledge_root() / 'paper_strategies'}")
    typer.echo(f"  agent PLAYBOOK:      {toolbox_root() / 'knowledge'}")


@app.command(name="run")
def run_pipeline(
    report_folder: str = typer.Option(DEFAULT_PAPER_REPORT_FOLDER, help="Folder containing PDF reports."),
    report_file: Optional[str] = typer.Option(None, help="Specific PDF to process."),
    path: Optional[str] = None,
    all_duration: Optional[str] = None,
    checkout: CheckoutOption = True,
    minimal_mode: bool = typer.Option(True, "--minimal-mode/--full-mode"),
    llm_max_retry: int = typer.Option(1, "--llm-max-retry", min=1),
    max_factors_per_paper: int = typer.Option(10, "--max-factors-per-paper", min=1, max=10),
    extract_only: bool = typer.Option(False, "--extract-only/--run-full-pipeline"),
    post_analyze: bool = typer.Option(_env_flag("PAPER_FACTOR_POST_ANALYZE", True), "--post-analyze/--no-post-analyze"),
    post_analyze_agent: bool = typer.Option(
        _env_flag("PAPER_FACTOR_POST_ANALYZE_AGENT", True),
        "--post-analyze-agent/--no-post-analyze-agent",
    ),
    analyze_accepted_only: bool = typer.Option(False, "--analyze-accepted-only/--analyze-all-exported"),
    barra_model: str = typer.Option("trading", "--barra-model"),
    barra_dir: Optional[str] = typer.Option(None, "--barra-dir"),
    analyze_data_type: str = typer.Option("All", "--analyze-data-type"),
) -> None:
    reset_token_session(label="factor-pipeline")
    _auto_init_workspace(download_missing=False)
    normalized_report_file = str(Path(report_file).resolve()) if report_file else None

    with _temporary_env(
        MAX_RETRY=str(llm_max_retry),
        LOG_LLM_CHAT_CONTENT="False",
        QLIB_FACTOR_MAX_FACTORS_PER_EXP=str(max_factors_per_paper),
        RDAGENT_PAPER_FACTOR_SKIP_LOW_IC_REPAIR="1",
        RDAGENT_PAPER_FACTOR_FAST="1",
    ):
        try:
            from rdagent.app.qlib_rd_loop.factor_from_report import extract_hypothesis_and_exp_from_reports
            from rdagent.app.qlib_rd_loop.factor_from_report import list_unprocessed_report_paths
            from rdagent.app.qlib_rd_loop.factor_from_report import main as fin_factor_report
        except ModuleNotFoundError as exc:
            typer.echo(f"Missing dependency: {exc}")
            raise typer.Exit(code=1) from exc

        if path is not None:
            fin_factor_report(
                report_folder=report_folder,
                path=path,
                all_duration=all_duration,
                checkout=checkout,
                minimal_mode=minimal_mode,
            )
            if not extract_only:
                _run_post_factor_analysis(
                    post_analyze=post_analyze,
                    post_analyze_agent=post_analyze_agent,
                    accepted_only=analyze_accepted_only,
                    barra_model=barra_model,
                    barra_dir=barra_dir,
                    data_type=analyze_data_type,
                )
            _finish_llm_session("factor-pipeline")
            return

        if normalized_report_file:
            report_path = Path(normalized_report_file)
            if not report_path.exists():
                raise typer.BadParameter(f"Report file does not exist: {normalized_report_file}")
            typer.echo(f"Processing paper: {normalized_report_file}")
            if extract_only:
                _extract_only(extract_hypothesis_and_exp_from_reports, normalized_report_file, minimal_mode)
                _finish_llm_session("factor-extract-only")
                return
            fin_factor_report(
                report_folder=report_folder,
                all_duration=all_duration,
                checkout=checkout,
                minimal_mode=minimal_mode,
                report_paths=[normalized_report_file],
            )
            if not extract_only:
                _run_post_factor_analysis(
                    post_analyze=post_analyze,
                    post_analyze_agent=post_analyze_agent,
                    accepted_only=analyze_accepted_only,
                    barra_model=barra_model,
                    barra_dir=barra_dir,
                    data_type=analyze_data_type,
                )
            _finish_llm_session("factor-pipeline")
            return

        processed_count = 0
        for next_report in list_unprocessed_report_paths(report_folder):
            typer.echo(f"Processing: {next_report}")
            if extract_only:
                _extract_only(extract_hypothesis_and_exp_from_reports, str(next_report), minimal_mode)
            else:
                fin_factor_report(
                    report_folder=report_folder,
                    all_duration=all_duration,
                    checkout=checkout,
                    minimal_mode=minimal_mode,
                    report_paths=[str(next_report)],
                )
            processed_count += 1

        if processed_count == 0:
            typer.echo("No unprocessed papers found.")
        if not extract_only and processed_count:
            _run_post_factor_analysis(
                post_analyze=post_analyze,
                post_analyze_agent=post_analyze_agent,
                accepted_only=analyze_accepted_only,
                barra_model=barra_model,
                barra_dir=barra_dir,
                data_type=analyze_data_type,
            )
    _finish_llm_session("factor-pipeline")


@app.command(name="start")
def start_pipeline(
    report_folder: str = typer.Option(DEFAULT_PAPER_REPORT_FOLDER),
    report_file: Optional[str] = None,
    path: Optional[str] = None,
    all_duration: Optional[str] = None,
    checkout: CheckoutOption = True,
    minimal_mode: bool = True,
    llm_max_retry: int = 1,
    post_analyze: bool = _env_flag("PAPER_FACTOR_POST_ANALYZE", True),
    post_analyze_agent: bool = _env_flag("PAPER_FACTOR_POST_ANALYZE_AGENT", True),
    analyze_accepted_only: bool = False,
    barra_model: str = "trading",
    barra_dir: Optional[str] = None,
    analyze_data_type: str = "All",
) -> None:
    with _temporary_env(DS_CODER_COSTEER_ENV_TYPE="docker"):
        run_pipeline(
            report_folder=report_folder,
            report_file=report_file,
            path=path,
            all_duration=all_duration,
            checkout=checkout,
            minimal_mode=minimal_mode,
            llm_max_retry=llm_max_retry,
            max_factors_per_paper=10,
            extract_only=False,
            post_analyze=post_analyze,
            post_analyze_agent=post_analyze_agent,
            analyze_accepted_only=analyze_accepted_only,
            barra_model=barra_model,
            barra_dir=barra_dir,
            analyze_data_type=analyze_data_type,
        )


def _extract_only(extractor, report_file: str, minimal_mode: bool) -> None:
    report_path = Path(report_file)
    exp = extractor(report_file, minimal_mode=minimal_mode)
    preview = Path.cwd() / "git_ignore_folder" / "factor_outputs" / "extracted_reports" / f"{report_path.stem}.extracted.json"
    typer.echo(f"Extract-only: {len(exp.sub_tasks) if exp else 0} factors → {preview}")


@app.command(name="init")
def init_workspace(force: bool = False) -> None:
    from rdagent.app.utils.init_workspace import init_workspace as init_rdagent_workspace

    summary = init_rdagent_workspace(force=force)
    typer.echo("factor_strategy_agent workspace initialized.")
    for item in summary["data"]:
        typer.echo(f"- {item}")


@app.command(name="analyze")
def analyze_factors(
    accepted_only: bool = False,
    data_type: str = "All",
    barra_model: str = "trading",
    barra_dir: Optional[str] = None,
    with_agent: bool = True,
    setup_barra: bool = False,
) -> None:
    reset_token_session(label="factor-analyze")
    _auto_init_workspace(download_missing=False)
    if setup_barra:
        import subprocess

        script = Path.cwd() / "scripts" / "setup_barra_model.sh"
        if script.exists():
            subprocess.run(["bash", str(script)], check=False)
    from rdagent.app.qlib_rd_loop.factor_portfolio_analyze import run_post_export_analysis

    try:
        run_post_export_analysis(
            accepted_only=accepted_only,
            data_type=data_type,
            barra_model=barra_model,
            with_agent=with_agent,
            barra_dir=barra_dir,
            allow_empty=False,
            echo_summary=True,
        )
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    _finish_llm_session("factor-analyze")


@app.command(name="profile")
def build_factor_profiles_cmd(
    evaluate_missing: bool = True,
    limit: Optional[int] = None,
    force: bool = False,
    barra_model: str = "trading",
    data_type: str = "All",
) -> None:
    _auto_init_workspace(download_missing=False)
    import importlib.util

    script = Path.cwd() / "scripts" / "build_factor_profiles.py"
    spec = importlib.util.spec_from_file_location("build_factor_profiles", script)
    if spec is None or spec.loader is None:
        raise typer.Exit(code=1)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    index = mod.run_build(
        evaluate_missing=evaluate_missing,
        limit=limit,
        force=force,
        barra_model=barra_model,
        data_type=data_type,
    )
    typer.echo(f"Built {index.get('count', 0)} profiles → {index.get('profile_root', '')}")


@app.command(name="strategy")
def run_strategy_cmd(
    spec_path: str = typer.Option(..., "--spec"),
    mode: Optional[str] = None,
    method: Optional[str] = None,
    max_factors: Optional[int] = None,
    sync_toolbox: bool = True,
) -> None:
    _auto_init_workspace(download_missing=False)
    from rdagent.scenarios.qlib.strategy.runner import run_strategy_pipeline, sync_toolbox_to_e
    from rdagent.scenarios.qlib.strategy.spec import load_strategy_spec

    spec = load_strategy_spec(spec_path)
    if mode:
        spec.mode = mode
    if method:
        spec.method = method
        spec.mode = "single"
    if max_factors is not None:
        spec.max_factors = max_factors
    if sync_toolbox:
        typer.echo(f"Synced toolbox → {sync_toolbox_to_e()}")
    result = run_strategy_pipeline(spec)
    sel = result.get("selection") or {}
    typer.echo(f"Output: {result.get('output_dir')}")
    if sel.get("selected_method"):
        m = (sel.get("selected_result") or {}).get("metrics") or {}
        typer.echo(f"Method: {sel['selected_method']}  Sharpe: {m.get('sharpe_annualized')}")


@app.command(name="strategy-ingest")
def strategy_ingest_cmd(
    report_file: str = typer.Option(..., "--report-file", help="PDF report with portfolio/strategy section."),
    run: bool = typer.Option(False, "--run/--extract-only", help="After extract, run strategy backtest."),
    sync_toolbox: bool = typer.Option(True, "--sync-toolbox/--no-sync-toolbox"),
) -> None:
    """Extract strategy method from paper → map to toolbox → optional run."""
    reset_token_session(label="strategy-ingest")
    _auto_init_workspace(download_missing=False)
    from rdagent.scenarios.qlib.strategy.runner import run_strategy_pipeline, sync_toolbox_to_e
    from rdagent.scenarios.qlib.strategy.spec import dump_strategy_spec
    from rdagent.scenarios.qlib.strategy_ingest import ingest_report_to_spec

    if sync_toolbox:
        typer.echo(f"Synced toolbox → {sync_toolbox_to_e()}")

    spec, extracted, mapping = ingest_report_to_spec(report_file)
    typer.echo(f"Extracted strategy → {mapping.get('extracted_path')}")
    factor_match = mapping.get("factor_match") or {}
    if factor_match:
        typer.echo(f"Factor match ({factor_match.get('matcher', 'agent')}) → {mapping.get('factor_match_path')}")
        matched = factor_match.get("matched_factors") or []
        for item in matched[:12]:
            typer.echo(
                f"  · {item.get('factor_name')} ← {item.get('paper_names')} "
                f"({item.get('confidence')}: {item.get('reason', '')[:80]})"
            )
        if len(matched) > 12:
            typer.echo(f"  … and {len(matched) - 12} more")
        typer.echo(f"  include_factors: {len(spec.include_factors or [])} selected")
    if mapping.get("warnings"):
        for w in mapping["warnings"]:
            typer.echo(f"  warn: {w}")
    if mapping.get("paper_strategy_id"):
        typer.echo(
            f"Paper strategy → {mapping['paper_strategy_id']} "
            f"(template={mapping.get('template_id')} method={mapping.get('mapped_method')})"
        )
        typer.echo(f"  recipe: {mapping.get('paper_strategy_recipe_path')}")
    spec_path = strategy_knowledge_root() / "paper_strategies" / f"{spec.name}.yaml"
    dump_strategy_spec(spec, spec_path)
    typer.echo(f"StrategySpec → {spec_path}")

    try:
        if run:
            result = run_strategy_pipeline(spec)
            typer.echo(f"Backtest → {result.get('output_dir')}")
            sel = result.get("selection") or {}
            res = sel.get("selected_result") or {}
            metrics = res.get("metrics") or {}
            if metrics:
                typer.echo(
                    f"  Sharpe: {metrics.get('sharpe_annualized')}  "
                    f"Ann.return: {metrics.get('annualized_return')}  "
                    f"MaxDD: {metrics.get('max_drawdown')}  "
                    f"Turnover: {metrics.get('turnover_mean')}"
                )
            elif res.get("status") == "error":
                typer.echo(f"  Backtest error: {res.get('error', '')[:200]}")
    finally:
        _finish_llm_session("strategy-ingest")


strategy_knowledge_app = typer.Typer(help="Empirical KB: factor_type × method × style grid on E:")


@strategy_knowledge_app.command("build-grid")
def kb_build_grid(
    dry_run: bool = typer.Option(False, "--dry-run"),
    max_per_bucket: int = typer.Option(15, "--max-per-bucket"),
    styles: Optional[str] = typer.Option(None, "--styles", help="Comma-separated: small_cap,csi300_enh,neutral"),
    slices: Optional[str] = typer.Option(None, "--slices", help="Comma-separated factor slice ids"),
    methods: Optional[str] = typer.Option(None, "--methods", help="Comma-separated method ids"),
) -> None:
    from rdagent.scenarios.qlib.strategy_knowledge import run_benchmark_grid

    style_list = [s.strip() for s in styles.split(",")] if styles else None
    slice_list = [s.strip() for s in slices.split(",")] if slices else None
    method_list = [m.strip() for m in methods.split(",")] if methods else None
    summary = run_benchmark_grid(
        styles=style_list,
        method_ids=method_list,
        slice_ids=slice_list,
        max_per_bucket=max_per_bucket,
        dry_run=dry_run,
    )
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))


@strategy_knowledge_app.command("rebuild-matrix")
def kb_rebuild_matrix() -> None:
    from rdagent.scenarios.qlib.strategy_knowledge import rebuild_matrix_summary

    summary = rebuild_matrix_summary()
    typer.echo(f"Matrix rebuilt: {summary.get('record_count')} records → {strategy_knowledge_root() / 'matrix_summary.json'}")


@strategy_knowledge_app.command("list-recipes")
def kb_list_recipes() -> None:
    """List paper strategy recipes registered in toolbox."""
    from rdagent.scenarios.qlib.strategy.paper_strategy.store import list_paper_strategies

    for row in list_paper_strategies():
        typer.echo(
            f"  {row.get('recipe_id')}  method={row.get('method_id')}  template={row.get('template_id')}  "
            f"{row.get('display_name', '')}"
        )


@strategy_knowledge_app.command("apply-recipe")
def kb_apply_recipe(
    recipe_id: str = typer.Option(..., "--recipe-id", help="Paper strategy recipe id from toolbox"),
    factors: Optional[str] = typer.Option(None, "--factors", help="Comma-separated factor names"),
    factor_slice: Optional[str] = typer.Option(None, "--slice", help="Taxonomy slice id, e.g. fundamental:value"),
    style: Optional[str] = typer.Option(None, "--style"),
    max_factors: Optional[int] = typer.Option(None, "--max-factors"),
    run: bool = typer.Option(False, "--run/--dry-run", help="Run backtest; default dry-run preview only"),
) -> None:
    """Apply a registered paper strategy to other factors (default: dry-run preview)."""
    from rdagent.scenarios.qlib.strategy.paper_strategy.pipeline import apply_paper_strategy_to_factors

    factor_list = [f.strip() for f in factors.split(",")] if factors else None
    result = apply_paper_strategy_to_factors(
        recipe_id,
        factor_names=factor_list,
        factor_slice=factor_slice,
        style=style,
        max_factors=max_factors,
        dry_run=not run,
        run_backtest=run,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@strategy_knowledge_app.command("query")
def kb_query(
    factor_slice: str = typer.Option(..., "--slice", help="e.g. fundamental:value"),
    style: str = typer.Option("neutral", "--style"),
    top_k: int = typer.Option(5, "--top-k"),
) -> None:
    from rdagent.scenarios.qlib.strategy_knowledge import query_methods

    result = query_methods(factor_slice=factor_slice, style=style, top_k=top_k)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


app.add_typer(strategy_knowledge_app, name="strategy-knowledge")


strategy_agent_app = typer.Typer(help="Strategy agent: create / optimize / continue.")


def _sync_strategy_toolbox(sync: bool) -> None:
    if sync:
        from rdagent.scenarios.qlib.strategy.runner import sync_toolbox_to_e

        typer.echo(f"Synced toolbox → {sync_toolbox_to_e()}")


def _echo_agent_report(report: dict) -> None:
    typer.echo(f"Agent root: {report.get('agent_root')}")
    tu = report.get("token_usage") or {}
    if tu:
        typer.echo(
            f"Tokens: in={tu.get('prompt_tokens', 0):,} out={tu.get('completion_tokens', 0):,} "
            f"total={tu.get('total_tokens', 0):,} cost=${tu.get('cost_usd', 0):.4f}"
        )
    best = report.get("best") or {}
    ms = (best.get("diagnosis") or {}).get("metrics_summary") or {}
    typer.echo(f"Best loop {best.get('loop')} Sharpe={ms.get('sharpe_annualized')} MDD={ms.get('max_drawdown')}")


@strategy_agent_app.command("create")
def strategy_agent_create(
    goal: str = typer.Option(..., "--goal"),
    template: Optional[str] = None,
    max_loops: int = 5,
    name_hint: Optional[str] = None,
    sync_toolbox: bool = True,
) -> None:
    _auto_init_workspace(download_missing=False)
    _sync_strategy_toolbox(sync_toolbox)
    from rdagent.scenarios.qlib.strategy.agent_loop import run_strategy_agent_create

    _echo_agent_report(run_strategy_agent_create(goal, template_path=template, max_loops=max_loops, name_hint=name_hint))


@strategy_agent_app.command("optimize")
def strategy_agent_optimize(
    spec_path: str = typer.Option(..., "--spec"),
    goal: str = "",
    max_loops: int = 5,
    max_factors: Optional[int] = None,
    sync_toolbox: bool = True,
) -> None:
    _auto_init_workspace(download_missing=False)
    _sync_strategy_toolbox(sync_toolbox)
    from rdagent.scenarios.qlib.strategy.agent_loop import run_strategy_agent_optimize
    from rdagent.scenarios.qlib.strategy.spec import load_strategy_spec

    spec = load_strategy_spec(spec_path)
    if max_factors is not None:
        spec.max_factors = max_factors
    _echo_agent_report(run_strategy_agent_optimize(spec, user_goal=goal, max_loops=max_loops))


@strategy_agent_app.command("continue")
def strategy_agent_continue(
    session: str = typer.Option(..., "--session"),
    feedback: str = typer.Option(..., "--feedback"),
    max_loops: int = 3,
    sync_toolbox: bool = False,
) -> None:
    _auto_init_workspace(download_missing=False)
    _sync_strategy_toolbox(sync_toolbox)
    from rdagent.scenarios.qlib.strategy.agent_loop import run_strategy_agent_continue

    _echo_agent_report(run_strategy_agent_continue(session, feedback, max_loops=max_loops))


@strategy_agent_app.command("status")
def strategy_agent_status(session: str = typer.Option(..., "--session")) -> None:
    from rdagent.scenarios.qlib.strategy.agent_loop import get_session_status

    typer.echo(json.dumps(get_session_status(session), ensure_ascii=False, indent=2))


app.add_typer(strategy_agent_app, name="strategy-agent")


def main() -> None:
    app()


def start_main() -> None:
    typer.run(start_pipeline)


if __name__ == "__main__":
    main()
