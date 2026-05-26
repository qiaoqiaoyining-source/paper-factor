from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from typing_extensions import Annotated


load_dotenv(".env")

app = typer.Typer(help="Standalone paper_factor: extract and reproduce factors from finance papers.")

DEFAULT_PAPER_REPORT_FOLDER = str(Path.cwd() / "papers" / "inbox")
DEFAULT_FACTOR_PAPER_QUERY = (
    "(cat:q-fin.ST OR cat:q-fin.PM OR cat:q-fin.TR) AND "
    '(all:factor OR all:alpha OR all:predictor OR all:signal OR all:"return prediction" '
    'OR all:"cross-sectional return")'
)

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


@app.command(name="run")
def run_paper_factor(
    report_folder: str = typer.Option(DEFAULT_PAPER_REPORT_FOLDER, help="Folder containing PDF factor reports."),
    report_file: Optional[str] = typer.Option(
        None,
        help="Specific PDF report to process. If omitted, paper_factor scans the report folder for unprocessed papers.",
    ),
    path: Optional[str] = None,
    all_duration: Optional[str] = None,
    checkout: CheckoutOption = True,
    minimal_mode: bool = typer.Option(
        True,
        "--minimal-mode/--full-mode",
        help="Use the lowest-cost extraction path by skipping report classification and extra hypothesis generation.",
    ),
    llm_max_retry: int = typer.Option(1, "--llm-max-retry", min=1),
    max_factors_per_paper: int = typer.Option(10, "--max-factors-per-paper", min=1, max=10),
    extract_only: bool = typer.Option(
        False,
        "--extract-only/--run-full-pipeline",
        help="Only read report and extract factor info without coding/evaluation/export.",
    ),
    post_analyze: bool = typer.Option(
        _env_flag("PAPER_FACTOR_POST_ANALYZE", True),
        "--post-analyze/--no-post-analyze",
        help="After pipeline, run IC/Barra batch analysis on exported factors.",
    ),
    post_analyze_agent: bool = typer.Option(
        _env_flag("PAPER_FACTOR_POST_ANALYZE_AGENT", True),
        "--post-analyze-agent/--no-post-analyze-agent",
        help="After metrics+Barra, run LLM optimization agent (uses API tokens).",
    ),
    analyze_accepted_only: bool = typer.Option(
        False,
        "--analyze-accepted-only/--analyze-all-exported",
        help="Post-analyze only accepted factors (default: all exported parquet).",
    ),
    barra_model: str = typer.Option("trading", "--barra-model", help="Barra CSV set for post-analyze."),
    barra_dir: Optional[str] = typer.Option(None, "--barra-dir", help="Override Barra model directory."),
    analyze_data_type: str = typer.Option("All", "--analyze-data-type", help="All or Debug for IC labels."),
) -> None:
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
            missing_name = getattr(exc, "name", None) or str(exc)
            typer.echo(
                "paper_factor cannot start because this Python environment is missing "
                f"the dependency `{missing_name}`. Install this project with its dependencies and rerun."
            )
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
            return

        if normalized_report_file:
            report_path = Path(normalized_report_file)
            if not report_path.exists():
                raise typer.BadParameter(f"Report file does not exist: {normalized_report_file}")
            typer.echo(f"Processing paper: {normalized_report_file}")
            if extract_only:
                _extract_only(extract_hypothesis_and_exp_from_reports, normalized_report_file, minimal_mode)
                return
            fin_factor_report(
                report_folder=report_folder,
                all_duration=all_duration,
                checkout=checkout,
                minimal_mode=minimal_mode,
                report_paths=[normalized_report_file],
            )
            typer.echo("paper_factor finished after processing 1 paper.")
            if not extract_only:
                _run_post_factor_analysis(
                    post_analyze=post_analyze,
                    post_analyze_agent=post_analyze_agent,
                    accepted_only=analyze_accepted_only,
                    barra_model=barra_model,
                    barra_dir=barra_dir,
                    data_type=analyze_data_type,
                )
            return

        processed_count = 0
        local_pending = list_unprocessed_report_paths(report_folder)
        if local_pending:
            for next_report in local_pending:
                typer.echo(f"Processing local pending paper: {next_report}")
                if extract_only:
                    _extract_only(extract_hypothesis_and_exp_from_reports, str(next_report), minimal_mode)
                    processed_count += 1
                    continue
                fin_factor_report(
                    report_folder=report_folder,
                    all_duration=all_duration,
                    checkout=checkout,
                    minimal_mode=minimal_mode,
                    report_paths=[str(next_report)],
                )
                processed_count += 1
        else:
            typer.echo("No unprocessed papers found in the report folder.")

    typer.echo(f"paper_factor finished after processing {processed_count} paper(s).")
    if not extract_only:
        _run_post_factor_analysis(
            post_analyze=post_analyze,
            post_analyze_agent=post_analyze_agent,
            accepted_only=analyze_accepted_only,
            barra_model=barra_model,
            barra_dir=barra_dir,
            data_type=analyze_data_type,
        )


@app.command(name="start")
def start_paper_factor(
    report_folder: str = typer.Option(DEFAULT_PAPER_REPORT_FOLDER, help="Folder containing PDF factor reports."),
    report_file: Optional[str] = typer.Option(
        None,
        help="Specific PDF report to process. If omitted, paper_factor scans the report folder for unprocessed papers.",
    ),
    path: Optional[str] = None,
    all_duration: Optional[str] = None,
    checkout: CheckoutOption = True,
    minimal_mode: bool = typer.Option(
        True,
        "--minimal-mode/--full-mode",
        help="Use the lowest-cost extraction path by skipping report classification and extra hypothesis generation.",
    ),
    llm_max_retry: int = typer.Option(1, "--llm-max-retry", min=1),
    post_analyze: bool = typer.Option(
        _env_flag("PAPER_FACTOR_POST_ANALYZE", True),
        "--post-analyze/--no-post-analyze",
        help="After start finishes, auto-run factor metrics + Barra analysis.",
    ),
    post_analyze_agent: bool = typer.Option(
        _env_flag("PAPER_FACTOR_POST_ANALYZE_AGENT", True),
        "--post-analyze-agent/--no-post-analyze-agent",
        help="Also run LLM optimization agent after post-analyze.",
    ),
    analyze_accepted_only: bool = typer.Option(
        False,
        "--analyze-accepted-only/--analyze-all-exported",
    ),
    barra_model: str = typer.Option("trading", "--barra-model"),
    barra_dir: Optional[str] = typer.Option(None, "--barra-dir"),
    analyze_data_type: str = typer.Option("All", "--analyze-data-type"),
) -> None:
    with _temporary_env(
        DS_CODER_COSTEER_ENV_TYPE="docker",
    ):
        run_paper_factor(
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
    preview_path = Path.cwd() / "git_ignore_folder" / "factor_outputs" / "extracted_reports" / f"{report_path.stem}.extracted.json"
    extracted_count = len(exp.sub_tasks) if exp is not None else 0
    typer.echo(f"Extract-only finished. Extracted factors: {extracted_count}")
    typer.echo(f"Preview JSON: {preview_path}")
    if exp is not None and exp.sub_tasks:
        typer.echo("Extracted factor names:")
        for task in exp.sub_tasks:
            typer.echo(f"- {task.factor_name}")


@app.command(name="init")
def init_workspace(force: bool = typer.Option(False, help="Overwrite existing local workspace files.")) -> None:
    from rdagent.app.utils.init_workspace import init_workspace as init_rdagent_workspace

    summary = init_rdagent_workspace(force=force)
    typer.echo("paper_factor workspace initialized.")
    typer.echo(f"Env: {summary['env']}")
    for item in summary["data"]:
        typer.echo(f"- {item}")


@app.command(name="analyze")
def analyze_factors(
    accepted_only: bool = typer.Option(
        False,
        "--accepted-only/--all-exported",
        help="Only analyze factors marked accepted in metadata.",
    ),
    data_type: str = typer.Option(
        "All",
        "--data-type",
        help="Use All (full sample) or Debug data folder for IC/label evaluation.",
    ),
    barra_model: str = typer.Option(
        "trading",
        "--barra-model",
        help="Barra CSV bundle: trading | long_term_stable",
    ),
    barra_dir: Optional[str] = typer.Option(
        None,
        help="Override Barra CSV directory (default: git_ignore_folder/barra_model).",
    ),
    with_agent: bool = typer.Option(
        True,
        "--with-agent/--metrics-only",
        help="Run LLM agent for optimization suggestions after metrics + Barra.",
    ),
    setup_barra: bool = typer.Option(
        False,
        "--setup-barra",
        help="Copy Desktop Barra模型 CSVs into git_ignore_folder/barra_model before analyze.",
    ),
) -> None:
    """Evaluate exported factors (IC/IR/RankIC/long-short/turnover/etc.) + Barra + agent advice."""
    _auto_init_workspace(download_missing=False)
    if setup_barra:
        import subprocess

        script = Path.cwd() / "scripts" / "setup_barra_model.sh"
        if script.exists():
            subprocess.run(["bash", str(script)], check=False)
        else:
            typer.echo("setup_barra_model.sh not found; skip Barra copy.")

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


def main() -> None:
    app()


def start_main() -> None:
    typer.run(start_paper_factor)


if __name__ == "__main__":
    main()
