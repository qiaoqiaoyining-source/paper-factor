"""Extract strategy construction methods from finance research PDFs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rdagent.log import rdagent_logger as logger
from rdagent.oai.llm_utils import APIBackend
from rdagent.scenarios.qlib.paths import paper_strategies_root
from rdagent.scenarios.qlib.strategy.registry import list_method_catalog
from rdagent.scenarios.qlib.strategy.spec import STYLE_PRESETS


_EXTRACT_SYSTEM = """你是量化策略文献分析助手。从研报中提取**投资组合构建/策略方法**（不是单个 alpha 因子公式）。
输出 JSON，字段：
{
  "strategy_name": "短名",
  "paper_title": "论文标题或文件名",
  "intent": "策略意图一句话",
  "factor_selection": {
    "description": "如何选因子",
    "include_tags": ["value", "momentum"],
    "min_icir": null,
    "max_factors": null
  },
  "combination": {
    "description": "如何组合因子",
    "method_id": "registry 中已有 id 或 null",
    "alternatives": ["method_id"],
    "novelty": "none | template | new_method",
    "template_hint": "若 novelty=template，描述参数化模板"
  },
  "portfolio": {
    "description": "组合构建",
    "top_frac": 0.2,
    "bottom_frac": 0.2,
    "rebalance": "daily|weekly|monthly",
    "style": "small_cap|csi300_enh|air_index_enh|neutral"
  },
  "constraints": {
    "max_turnover": null,
    "max_drawdown": null,
    "min_sharpe": null
  },
  "applicability_tags": ["fundamental", "low_turnover"],
  "evidence_quotes": ["原文关键句"]
}
只输出 JSON。"""


def extract_strategy_from_report(report_path: str | Path) -> dict[str, Any]:
    """LLM extract strategy spec draft from PDF report."""
    from rdagent.components.document_reader.document_reader import load_and_process_pdfs_for_paper_factor

    report_path = Path(report_path).resolve()
    docs = load_and_process_pdfs_for_paper_factor(str(report_path))
    text = "\n\n".join(str(v) for v in docs.values())[:120000]
    catalog = list_method_catalog()

    user_payload = {
        "report_file": report_path.name,
        "available_methods": catalog,
        "style_presets": list(STYLE_PRESETS.keys()),
        "document_excerpt": text,
    }
    backend = APIBackend()
    response = backend.build_messages_and_create_chat_completion(
        system_prompt=_EXTRACT_SYSTEM,
        user_prompt=json.dumps(user_payload, ensure_ascii=False),
        json_mode=True,
    )
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        logger.warning("Strategy extract JSON parse failed; wrapping raw response")
        data = {"raw_response": response, "strategy_name": report_path.stem}

    data["report_path"] = str(report_path)
    data["source"] = "strategy_ingest"
    return data


def persist_extracted_strategy(data: dict[str, Any], root: Path | None = None) -> Path:
    root = root or paper_strategies_root()
    root.mkdir(parents=True, exist_ok=True)
    name = str(data.get("strategy_name") or "unnamed").replace(" ", "_")
    path = root / f"{name}.strategy.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
