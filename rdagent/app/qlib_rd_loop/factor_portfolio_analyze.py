"""Batch factor evaluation (IC/IR/RankIC/long-short/etc.) + Barra + LLM optimization."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import typer
from dotenv import load_dotenv

from rdagent.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
from rdagent.components.coder.factor_coder.eva_utils import (
    _format_extended_metrics_feedback,
    evaluate_factor_metrics_bundle,
)
from rdagent.log import rdagent_logger as logger
from rdagent.oai.llm_utils import APIBackend
from rdagent.scenarios.qlib.developer.barra_analysis import (
    analyze_factor_barra_full,
    list_barra_models,
    resolve_barra_dir,
)

load_dotenv(".env")

FACTOR_OUTPUT_DIR = Path(
    os.environ.get("PAPER_FACTOR_OUTPUTS_DIR", str(Path.cwd() / "git_ignore_folder" / "factor_outputs"))
)
ANALYSIS_DIR = FACTOR_OUTPUT_DIR / "factor_analysis"
OPTIMIZATION_DIR = FACTOR_OUTPUT_DIR / "optimization_reports"


def _discover_factor_records(*, accepted_only: bool = False) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not FACTOR_OUTPUT_DIR.exists():
        return records
    for meta_path in FACTOR_OUTPUT_DIR.rglob("*.meta.json"):
        if "dashboard" in meta_path.parts or "factor_analysis" in meta_path.parts:
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(meta, dict):
            continue
        if accepted_only and not meta.get("accepted"):
            continue
        parquet_path = meta.get("latest_path") or str(meta_path.with_suffix(".parquet"))
        if not Path(parquet_path).exists():
            continue
        meta["metadata_path"] = str(meta_path)
        meta["parquet_path"] = str(parquet_path)
        records.append(meta)
    return records


def _analyze_single_factor(
    record: dict[str, Any],
    *,
    data_type: str = "All",
    barra_model: str = "trading",
    barra_dir: Path | None = None,
) -> dict[str, Any]:
    factor_name = str(record.get("factor_name") or Path(record["parquet_path"]).stem)
    df = pd.read_parquet(record["parquet_path"])
    feedback, ic_scalar, metrics = evaluate_factor_metrics_bundle(None, data_type=data_type, gen_df=df)
    threshold = FACTOR_COSTEER_SETTINGS.min_abs_ic
    metrics_feedback = _format_extended_metrics_feedback(metrics, threshold=threshold)

    barra: dict[str, Any]
    try:
        barra = analyze_factor_barra_full(
            df,
            barra_dir=barra_dir,
            model=barra_model,
            data_type=data_type,
        )
    except Exception as exc:  # noqa: BLE001
        barra = {"status": "error", "reason": str(exc)}

    return {
        "factor_name": factor_name,
        "display_name": record.get("display_name") or factor_name,
        "accepted": bool(record.get("accepted")),
        "source_type": record.get("source_type"),
        "source_report_title": record.get("source_report_title"),
        "parquet_path": record.get("parquet_path"),
        "metadata_path": record.get("metadata_path"),
        "ic_scalar": ic_scalar,
        "metrics": metrics,
        "metrics_feedback": metrics_feedback,
        "evaluation_feedback": feedback,
        "barra": barra,
        "barra_summary": barra.get("summary_markdown") if isinstance(barra, dict) else "",
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
    }


def run_factor_batch_analysis(
    *,
    accepted_only: bool = False,
    data_type: str = "All",
    barra_model: str = "trading",
    barra_dir: Path | None = None,
) -> dict[str, Any]:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    records = _discover_factor_records(accepted_only=accepted_only)
    if not records:
        return {
            "status": "empty",
            "message": "No exported factor parquet files found under git_ignore_folder/factor_outputs.",
            "analyzed": 0,
        }

    results: list[dict[str, Any]] = []
    for record in records:
        name = str(record.get("factor_name") or "unknown")
        logger.info(f"Analyzing factor: {name}")
        try:
            item = _analyze_single_factor(
                record,
                data_type=data_type,
                barra_model=barra_model,
                barra_dir=barra_dir,
            )
        except Exception as exc:  # noqa: BLE001
            item = {
                "factor_name": name,
                "status": "error",
                "error": str(exc),
                "metadata_path": record.get("metadata_path"),
            }
        results.append(item)
        out_path = ANALYSIS_DIR / f"{item.get('factor_name', name)}.analysis.json"
        out_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "status": "ok",
        "analyzed": len(results),
        "accepted_only": accepted_only,
        "data_type": data_type,
        "barra_model": barra_model,
        "barra_dir": str(resolve_barra_dir(barra_dir)),
        "barra_files": list_barra_models(barra_dir),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "factors": [
            {
                "factor_name": r.get("factor_name"),
                "accepted": r.get("accepted"),
                "ic_mean_pearson": (r.get("metrics") or {}).get("ic_mean_pearson"),
                "rank_ic_mean": (r.get("metrics") or {}).get("rank_ic_mean"),
                "icir_pearson": (r.get("metrics") or {}).get("icir_pearson"),
                "rank_icir": (r.get("metrics") or {}).get("rank_icir"),
                "ls_sharpe_annualized": (r.get("metrics") or {}).get("ls_sharpe_annualized"),
                "ls_max_drawdown": (r.get("metrics") or {}).get("ls_max_drawdown"),
                "top_bottom_turnover_mean": (r.get("metrics") or {}).get("top_bottom_turnover_mean"),
                "ic_positive_hit_rate": (r.get("metrics") or {}).get("ic_positive_hit_rate"),
                "barra_status": (r.get("barra") or {}).get("status"),
                "barra_attrib_status": ((r.get("barra") or {}).get("return_risk_attribution") or {}).get(
                    "status"
                ),
                "mean_daily_factor_contrib": (
                    (r.get("barra") or {}).get("return_risk_attribution") or {}
                ).get("mean_daily_factor_contrib"),
                "mean_daily_specific_contrib": (
                    (r.get("barra") or {}).get("return_risk_attribution") or {}
                ).get("mean_daily_specific_contrib"),
                "analysis_path": str(ANALYSIS_DIR / f"{r.get('factor_name')}.analysis.json"),
            }
            for r in results
        ],
    }
    summary_path = ANALYSIS_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = FACTOR_OUTPUT_DIR / "analysis_manifest.csv"
    pd.DataFrame(summary["factors"]).to_csv(manifest_path, index=False)
    return summary


def run_factor_optimization_agent(
    summary: dict[str, Any] | None = None,
    *,
    summary_path: Path | None = None,
) -> dict[str, Any]:
    OPTIMIZATION_DIR.mkdir(parents=True, exist_ok=True)
    if summary is None:
        path = summary_path or (ANALYSIS_DIR / "summary.json")
        if not path.exists():
            raise FileNotFoundError(f"Analysis summary not found: {path}. Run analyze first.")
        summary = json.loads(path.read_text(encoding="utf-8"))

    compact_rows = []
    for row in summary.get("factors") or []:
        factor_name = row.get("factor_name")
        detail_path = ANALYSIS_DIR / f"{factor_name}.analysis.json"
        detail: dict[str, Any] = {}
        if detail_path.exists():
            detail = json.loads(detail_path.read_text(encoding="utf-8"))
        compact_rows.append(
            {
                "factor_name": factor_name,
                "accepted": row.get("accepted"),
                "metrics": detail.get("metrics") or {},
                "barra": detail.get("barra") or {},
                "barra_return_attribution": (detail.get("barra") or {}).get("return_risk_attribution"),
                "logic_summary": detail.get("metrics_feedback"),
                "source_report_title": detail.get("source_report_title"),
            }
        )

    system_prompt = (
        "你是量化因子优化顾问。根据因子的 IC/RankIC/IR、多空收益、换手、Barra 风格暴露诊断，"
        "以及 Barra 全量收益归因（风格+行业因子收益、特质收益、残差）和风险归因（因子协方差 vs 特质风险），"
        "给出可执行的优化建议：公式调整、中性化、平滑、换手控制、与 Barra 风格/行业去相关等。"
        "输出 JSON："
        '{"overall_summary":"...", "factor_recommendations":[{"factor_name":"...", "priority":"high|medium|low", '
        '"issues":["..."], "actions":["..."], "barra_notes":"..."}]}'
    )
    user_prompt = json.dumps(
        {
            "analysis_batch": compact_rows,
            "metric_glossary": {
                "ic_mean_pearson": "日均截面 Pearson IC",
                "icir_pearson": "IC mean / IC std",
                "rank_ic_mean": "日均 Rank IC (Spearman)",
                "rank_icir": "Rank IC IR",
                "ls_sharpe_annualized": "多空组合年化 Sharpe proxy",
                "ls_max_drawdown": "多空复利曲线最大回撤",
                "top_bottom_turnover_mean": "Top/Bottom 组合换手 proxy",
                "ic_positive_hit_rate": "IC>0 的交易日占比",
            },
        },
        ensure_ascii=False,
    )

    backend = APIBackend()
    token_estimate = backend.build_messages_and_calculate_token(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
    )
    logger.info(f"Factor optimization agent token estimate (input): {token_estimate}")

    response = backend.build_messages_and_create_chat_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=True,
        json_target_type=dict,
    )
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        payload = {"overall_summary": response, "factor_recommendations": []}

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_token_estimate": token_estimate,
        "model": os.environ.get("CHAT_MODEL") or os.environ.get("OPENAI_API_MODEL") or "default",
        "summary": payload,
        "source_analysis": str(summary_path or ANALYSIS_DIR / "summary.json"),
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OPTIMIZATION_DIR / f"optimization_{stamp}.json"
    md_path = OPTIMIZATION_DIR / f"optimization_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Factor optimization report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Input token estimate: {token_estimate}",
        "",
        "## Overall",
        str(payload.get("overall_summary") or ""),
        "",
        "## Recommendations",
    ]
    for item in payload.get("factor_recommendations") or []:
        lines.append(f"### {item.get('factor_name')} ({item.get('priority')})")
        for issue in item.get("issues") or []:
            lines.append(f"- Issue: {issue}")
        for action in item.get("actions") or []:
            lines.append(f"- Action: {action}")
        if item.get("barra_notes"):
            lines.append(f"- Barra: {item['barra_notes']}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    report["json_path"] = str(json_path)
    report["markdown_path"] = str(md_path)
    return report


def run_post_export_analysis(
    *,
    accepted_only: bool = False,
    data_type: str = "All",
    barra_model: str = "trading",
    with_agent: bool = True,
    barra_dir: Path | str | None = None,
    allow_empty: bool = True,
    echo_summary: bool = True,
) -> dict[str, Any]:
    """
    Metrics + Barra batch analysis, optionally followed by optimization agent.
    Used after `start` finishes and by the standalone `analyze` CLI.
    """
    resolved = Path(barra_dir) if barra_dir else None
    if echo_summary:
        print(
            "paper_factor: running factor analysis (IC/RankIC/long-short/turnover + Barra full attribution)...",
            flush=True,
        )
    summary = run_factor_batch_analysis(
        accepted_only=accepted_only,
        data_type=data_type,
        barra_model=barra_model,
        barra_dir=resolved,
    )
    if echo_summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if summary.get("status") == "empty":
        if allow_empty:
            print(
                "paper_factor: no exported factor parquet found; analysis skipped. "
                "Export at least one factor (accepted) then rerun `analyze`.",
                flush=True,
            )
            return summary
        raise RuntimeError(summary.get("message") or "No exported factors to analyze.")
    if with_agent:
        report = run_factor_optimization_agent(summary)
        print(f"factor_strategy_agent: optimization report -> {report['markdown_path']}", flush=True)
        try:
            from rdagent.oai.token_usage import echo_token_usage

            echo_token_usage(label="factor-optimization-agent")
        except Exception:  # noqa: BLE001
            pass
        summary["optimization_report"] = report
    return summary


def main_analyze_cli(
    accepted_only: bool = False,
    data_type: str = "All",
    barra_model: str = "trading",
    with_agent: bool = True,
    barra_dir: str | None = None,
) -> None:
    run_post_export_analysis(
        accepted_only=accepted_only,
        data_type=data_type,
        barra_model=barra_model,
        with_agent=with_agent,
        barra_dir=barra_dir,
        allow_empty=False,
        echo_summary=True,
    )
