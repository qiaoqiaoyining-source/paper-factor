"""Match paper strategy factor requirements to existing factor profiles via LLM agent."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rdagent.log import rdagent_logger as logger
from rdagent.oai.llm_utils import APIBackend
from rdagent.scenarios.qlib.paths import paper_strategies_root
from rdagent.scenarios.qlib.strategy.profile_loader import load_profile, load_profiles_index
from rdagent.scenarios.qlib.strategy.spec import StrategySpec, apply_spec_patch

_MATCH_SYSTEM = """你是量化因子匹配 Agent。任务：根据研报策略的因子需求，从现有 factor profile 目录中选出最匹配的因子名称。

你会收到：
- 策略意图与 factor_selection 描述
- paper_factor_hints（从研报文本抽出的 ROE/EPS/盈利 等关键词）
- candidate_profiles：每个 profile 的 factor_name、source_type、tags（含 theme:...）、documentation（description/formula/english_name 等）、ICIR

规则：
1) 只能返回 candidate_profiles 里存在的 factor_name，禁止编造。
2) 充分利用 theme:、short_name、english_name、factor_description、formula 做语义匹配（例如 ROE↔净资产收益率，EPS↔每股收益）。
3) 研报里的滞后窗口 MA(L=0,1,4,8) 是组合方法层面的构造，不是要求 profile 名字里带 L0；优先匹配基础指标因子。
4) 若策略明显是基本面策略，优先 fundamental_remote；否则可混合 literature_remote。
5) include_tags 只能填写候选 profile 里真实出现过的 tag；不要输出 profile 中不存在的 tag（例如 profitability 若无人拥有则不要写）。
6) 若无法匹配足够因子，在 warnings 说明，并给出最接近的候选。

输出 JSON：
{
  "paper_factor_requirements": [{"name": "ROE", "notes": "..."}],
  "matched_factors": [
    {"factor_name": "盈利因子1", "paper_names": ["ROE"], "confidence": "high|medium|low", "reason": "..."}
  ],
  "include_factors": ["盈利因子1"],
  "include_tags": [],
  "factor_source_types": ["fundamental_remote"],
  "warnings": []
}
只输出 JSON。"""

_PAPER_FACTOR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ROE", re.compile(r"\bROE\b|净资产收益率", re.I)),
    ("ROA", re.compile(r"\bROA\b|资产回报率|总资产报酬", re.I)),
    ("EPS", re.compile(r"\bEPS\b|每股收益", re.I)),
    ("APE", re.compile(r"\bAPE\b|权责发生制.*营业利润.*权益|营业利润.*权益比", re.I)),
    ("CPA", re.compile(r"\bCPA\b|收付实现制.*营业利润.*资产|营业利润.*资产比", re.I)),
    ("GPA", re.compile(r"\bGPA\b|毛利资产比|毛利率.*资产", re.I)),
    ("revenue_growth", re.compile(r"营业收入.*增长|营收.*增长", re.I)),
    ("profit_growth", re.compile(r"净利润.*增长|盈利.*增长", re.I)),
]


def _profile_search_text(profile: dict[str, Any], entry: dict[str, Any]) -> str:
    doc = profile.get("documentation") or {}
    tags = profile.get("tags") or entry.get("tags") or []
    parts = [
        str(profile.get("factor_name") or entry.get("factor_name") or ""),
        str(doc.get("factor_description") or ""),
        str(doc.get("short_name") or ""),
        str(doc.get("english_name") or ""),
        str(doc.get("formula") or ""),
        str(doc.get("factor_formulation") or ""),
        str(doc.get("source_report_title") or ""),
        " ".join(str(t) for t in tags),
    ]
    return " ".join(parts).lower()


def summarize_profile_for_matching(entry: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    doc = profile.get("documentation") or {}
    tags = list(profile.get("tags") or entry.get("tags") or [])
    themes = [t for t in tags if str(t).startswith("theme:")]
    ev = profile.get("evaluation") or {}
    return {
        "factor_name": str(profile.get("factor_name") or entry.get("factor_name") or ""),
        "source_type": str(profile.get("source_type") or entry.get("source_type") or ""),
        "source_category": profile.get("source_category") or entry.get("source_category"),
        "tags": tags[:20],
        "themes": themes[:5],
        "factor_description": str(doc.get("factor_description") or "")[:400],
        "short_name": doc.get("short_name"),
        "english_name": doc.get("english_name"),
        "formula": str(doc.get("formula") or doc.get("factor_formulation") or "")[:300],
        "icir_pearson": ev.get("icir_pearson"),
    }


def collect_profile_summaries(
    profile_root: Path | None = None,
    *,
    source_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    index = load_profiles_index(profile_root)
    root = Path(index.get("profile_root") or profile_root or "")
    summaries: list[dict[str, Any]] = []
    allowed = set(source_types) if source_types else None

    for entry in index.get("factors") or []:
        src = str(entry.get("source_type") or "")
        if allowed and src not in allowed:
            continue
        profile_path = Path(str(entry.get("profile_path") or ""))
        if not profile_path.exists():
            profile_path = root / profile_path.name
        if not profile_path.exists():
            continue
        profile = load_profile(profile_path)
        parquet = (profile.get("data") or {}).get("values_parquet")
        if not parquet:
            continue
        summaries.append(summarize_profile_for_matching(entry, profile))
    return summaries


def extract_paper_factor_hints(extracted: dict[str, Any]) -> list[str]:
    factor_sel = extracted.get("factor_selection") or {}
    chunks = [
        str(extracted.get("intent") or ""),
        str(factor_sel.get("description") or ""),
        " ".join(str(q) for q in (extracted.get("evidence_quotes") or [])),
    ]
    text = "\n".join(chunks)
    hints: list[str] = []
    for name, pattern in _PAPER_FACTOR_PATTERNS:
        if pattern.search(text):
            hints.append(name)
    for token in ("ROE", "ROA", "EPS", "APE", "CPA", "GPA"):
        if token.lower() in text.lower() and token not in hints:
            hints.append(token)
    return hints


def prefilter_candidates(
    extracted: dict[str, Any],
    profiles: list[dict[str, Any]],
    *,
    max_candidates: int = 120,
) -> list[dict[str, Any]]:
    hints = extract_paper_factor_hints(extracted)
    factor_sel = extracted.get("factor_selection") or {}
    query_parts = hints + list(factor_sel.get("include_tags") or [])
    query = " ".join(query_parts).lower()

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in profiles:
        score = 0.0
        blob = _profile_search_text(
            {"factor_name": item.get("factor_name"), "documentation": item, "tags": item.get("tags")},
            item,
        )
        for hint in hints:
            h = hint.lower()
            if h in blob:
                score += 3.0
            if h == "roe" and ("净资产" in blob or "roe" in blob):
                score += 2.0
            if h == "roa" and ("资产回报" in blob or "roa" in blob):
                score += 2.0
            if h == "eps" and ("每股收益" in blob or "eps" in blob):
                score += 2.0
        for tag in factor_sel.get("include_tags") or []:
            if str(tag).lower() in blob:
                score += 1.0
        if item.get("source_type") == "fundamental_remote":
            score += 0.2
        icir = item.get("icir_pearson")
        if icir is not None:
            score += min(abs(float(icir)), 0.2)
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    if hints:
        top = [item for s, item in scored if s > 0][:max_candidates]
        if len(top) >= 5:
            return top
    return [item for _, item in scored[:max_candidates]]


def _heuristic_match(extracted: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    hints = extract_paper_factor_hints(extracted)
    matched: list[dict[str, Any]] = []
    used: set[str] = set()

    for hint in hints:
        best_score = 0.0
        best_item: dict[str, Any] | None = None
        for item in candidates:
            name = str(item.get("factor_name") or "")
            if name in used:
                continue
            blob = _profile_search_text(
                {"factor_name": name, "documentation": item, "tags": item.get("tags")},
                item,
            )
            score = 0.0
            if hint.lower() in blob:
                score += 2.0
            if hint == "ROE" and ("净资产收益率" in blob or "roe" in blob):
                score += 3.0
            if hint == "ROA" and ("资产回报率" in blob or "roa" in blob):
                score += 3.0
            if hint == "EPS" and ("每股收益" in blob or "eps" in blob):
                score += 3.0
            if score > best_score:
                best_score = score
                best_item = item
        if best_item and best_score >= 2.0:
            fname = str(best_item["factor_name"])
            used.add(fname)
            matched.append(
                {
                    "factor_name": fname,
                    "paper_names": [hint],
                    "confidence": "medium",
                    "reason": "heuristic keyword match on profile documentation/themes",
                }
            )

    include = [m["factor_name"] for m in matched]
    source_types = sorted({str(c.get("source_type")) for c in candidates if c.get("factor_name") in include})
    return {
        "paper_factor_requirements": [{"name": h, "notes": "from paper text"} for h in hints],
        "matched_factors": matched,
        "include_factors": include,
        "include_tags": [],
        "factor_source_types": source_types or ["fundamental_remote", "literature_remote"],
        "warnings": [] if include else ["heuristic match found no factors"],
        "matcher": "heuristic",
    }


def match_strategy_factors(
    extracted: dict[str, Any],
    spec: StrategySpec,
    profile_root: Path | None = None,
) -> dict[str, Any]:
    """Run LLM agent to map paper factor requirements → profile factor_name list."""
    prefer_fundamental = "fundamental" in (extracted.get("applicability_tags") or []) or "fundamental" in spec.include_tags
    source_types = list(spec.factor_source_types)
    if prefer_fundamental and "fundamental_remote" in source_types:
        pool = collect_profile_summaries(profile_root, source_types=["fundamental_remote"])
        if not pool:
            pool = collect_profile_summaries(profile_root, source_types=source_types)
    else:
        pool = collect_profile_summaries(profile_root, source_types=source_types)

    candidates = prefilter_candidates(extracted, pool)
    if not candidates:
        return {
            "matched_factors": [],
            "include_factors": [],
            "include_tags": [],
            "warnings": ["no candidate profiles found"],
            "matcher": "none",
        }

    user_payload = {
        "strategy_name": extracted.get("strategy_name"),
        "intent": extracted.get("intent"),
        "factor_selection": extracted.get("factor_selection"),
        "paper_factor_hints": extract_paper_factor_hints(extracted),
        "max_factors": spec.max_factors,
        "style": spec.style,
        "candidate_profiles": candidates,
    }

    try:
        backend = APIBackend()
        response = backend.build_messages_and_create_chat_completion(
            system_prompt=_MATCH_SYSTEM,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            json_mode=True,
        )
        result = json.loads(response)
        result["matcher"] = "llm"
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Factor match LLM failed: {exc}; falling back to heuristic")
        result = _heuristic_match(extracted, candidates)

    # Validate factor names exist in candidates
    valid_names = {str(c.get("factor_name")) for c in candidates}
    raw_include = [str(x) for x in (result.get("include_factors") or [])]
    include = [n for n in raw_include if n in valid_names]
    if len(include) < len(raw_include):
        result.setdefault("warnings", []).append("dropped include_factors not in candidate catalog")

    if not include:
        fallback = _heuristic_match(extracted, candidates)
        if fallback.get("include_factors"):
            result = fallback
            include = list(fallback["include_factors"])

    result["include_factors"] = include[: spec.max_factors] if spec.max_factors else include
    return result


def apply_factor_match(spec: StrategySpec, match_result: dict[str, Any]) -> StrategySpec:
    """Merge agent match result into StrategySpec."""
    include_factors = list(match_result.get("include_factors") or [])
    patch: dict[str, Any] = {}

    if include_factors:
        patch["include_factors"] = include_factors
        patch["include_tags"] = []
        patch["min_icir"] = None
    else:
        tags = [str(t) for t in (match_result.get("include_tags") or []) if t]
        if tags:
            patch["include_tags"] = tags

    source_types = match_result.get("factor_source_types")
    if isinstance(source_types, list) and source_types:
        patch["factor_source_types"] = [str(s) for s in source_types]

    if not include_factors and not patch.get("include_tags"):
        # Avoid impossible AND tag sets from paper extract (e.g. profitability missing everywhere)
        patch["include_tags"] = ["fundamental"] if "fundamental_remote" in (spec.factor_source_types or []) else []

    return apply_spec_patch(spec, patch)


def persist_factor_match(
    strategy_name: str,
    match_result: dict[str, Any],
    root: Path | None = None,
) -> Path:
    root = root or paper_strategies_root()
    root.mkdir(parents=True, exist_ok=True)
    safe = str(strategy_name).replace(" ", "_")
    path = root / f"{safe}.factor_match.json"
    path.write_text(json.dumps(match_result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
