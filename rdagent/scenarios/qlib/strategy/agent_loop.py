"""Strategy knowledge-base agent: create → optimize → user feedback cycles."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rdagent.log import rdagent_logger as logger
from rdagent.oai.llm_utils import APIBackend
from rdagent.scenarios.qlib.strategy.agent_session import (
    attach_existing_session,
    begin_feedback_round,
    build_effective_goal,
    create_session,
    finish_feedback_round,
    load_resume_state,
    write_optimization_summary,
)
from rdagent.scenarios.qlib.strategy.diagnostics import diagnose_strategy_run
from rdagent.scenarios.qlib.strategy.knowledge import (
    append_lesson,
    build_agent_context,
    load_knobs,
    validate_spec_patch,
)
from rdagent.scenarios.qlib.strategy.registry import list_method_catalog
from rdagent.scenarios.qlib.strategy.runner import default_output_root, run_strategy_pipeline
from rdagent.scenarios.qlib.strategy.spec import (
    STYLE_PRESETS,
    StrategySpec,
    apply_spec_patch,
    dump_strategy_spec,
    load_strategy_spec,
)


from rdagent.oai.token_usage import echo_token_usage, get_token_session, reset_token_session


def _attach_token_summary(report: dict[str, Any], *, label: str = "strategy-agent") -> dict[str, Any]:
    summary = get_token_session().summary_dict()
    report["token_usage"] = summary
    agent_root = report.get("agent_root")
    if agent_root:
        path = Path(agent_root) / "token_usage.json"
        get_token_session().save(path)
        report["token_usage_path"] = str(path)
    echo_token_usage(label=label)
    return report


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_selection(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    sel = payload.get("selection") or {}
    method = sel.get("selected_method")
    result = sel.get("selected_result")
    if result:
        return method or result.get("method_id"), result
    return method, None


def _patch_system_prompt(*, feedback_mode: bool = False) -> str:
    base = (
        "你是量化策略优化 Agent。根据策略回测诊断、用户目标、知识库 PLAYBOOK 与可调参数 knobs，"
        "提出下一轮 StrategySpec 修正（JSON patch），而不是写 Python 代码。\n"
        "原则：\n"
        "1) 只修改 knobs.json 中列出的字段；\n"
        "2) 每次 loop 给出 1-4 个最关键改动，并解释因果；\n"
        "3) 若 gross 好但 net 差，优先降换手；\n"
        "4) 若因子权重过于集中，可 exclude_factors 或换 method；\n"
        "5) 若已满足约束且无 high severity issue，stop=true；\n"
        "6) 参考 empirical_kb 中该因子类型+风格的历史最优 method，优先尝试 best_methods。\n"
    )
    if feedback_mode:
        base += "6) 用户最新反馈优先级最高；在 patch 中明确响应反馈。\n"
    base += (
        '输出 JSON: {"stop": false, "reasoning": "...", "spec_patch": {...}, '
        '"expected_effect": "...", "risks": ["..."], "tags": ["..."], '
        '"response_to_user": "给用户的一句话说明"}'
    )
    return base


def _create_system_prompt() -> str:
    return (
        "你是量化策略设计 Agent。根据用户自然语言需求，生成初始 StrategySpec（JSON 字段，不是 Python）。\n"
        "可选 style: small_cap | csi300_enh | air_index_enh | neutral\n"
        "默认 mode=auto，one_way_cost=0.002，apply_limit_filter=true。\n"
        "根据用户描述设置合理的 min_sharpe、max_drawdown、max_turnover、max_factors 等约束。\n"
        "只使用 knobs.json 中允许的字段。\n"
        '输出 JSON: {"reasoning": "...", "strategy_spec": {"name": "...", "style": "...", ...}, '
        '"summary_for_user": "用中文告诉用户你打算构建什么样的策略"}'
    )


def _spec_from_llm_dict(data: dict[str, Any], *, fallback: StrategySpec | None = None) -> StrategySpec:
    known = {f.name for f in StrategySpec.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    base = fallback or StrategySpec()
    patch = {key: value for key, value in (data or {}).items() if key in known and key != "output_dir"}
    return apply_spec_patch(base, patch)


def generate_strategy_spec_from_goal(
    user_goal: str,
    *,
    template_path: str | Path | None = None,
    name_hint: str | None = None,
) -> tuple[StrategySpec, dict[str, Any]]:
    """LLM: natural language requirement → initial StrategySpec."""
    template: StrategySpec | None = None
    if template_path:
        template = load_strategy_spec(template_path)

    context = build_agent_context(user_goal=user_goal)
    user_payload = {
        "user_goal": user_goal,
        "name_hint": name_hint,
        "style_presets": STYLE_PRESETS,
        "knobs": context["knobs"],
        "playbook_excerpt": context["playbook_excerpt"][:8000],
        "empirical_kb": context.get("empirical_kb"),
        "template_spec": template.to_dict() if template else None,
        "method_catalog_ids": [m["id"] for m in list_method_catalog()],
    }
    user_prompt = json.dumps(user_payload, ensure_ascii=False)

    backend = APIBackend()
    response = backend.build_messages_and_create_chat_completion(
        system_prompt=_create_system_prompt(),
        user_prompt=user_prompt,
        json_mode=True,
        json_target_type=dict,
    )
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        payload = {"reasoning": response, "strategy_spec": {}, "summary_for_user": response}

    raw_spec = payload.get("strategy_spec") or {}
    if name_hint and not raw_spec.get("name"):
        raw_spec["name"] = name_hint
    spec = _spec_from_llm_dict(raw_spec, fallback=template)
    if not spec.name or spec.name == "custom_strategy":
        stamp = datetime.now().strftime("%Y%m%d")
        spec = apply_spec_patch(spec, {"name": f"agent_{spec.style}_{stamp}"})

    return spec, payload


def propose_spec_patch(
    *,
    spec: StrategySpec,
    diagnosis: dict[str, Any],
    trace: list[dict[str, Any]],
    user_goal: str = "",
    feedback_mode: bool = False,
) -> dict[str, Any]:
    catalog = list_method_catalog()
    context = build_agent_context(user_goal=user_goal, spec_dict=spec.to_dict(), style=spec.style)
    user_payload = {
        "user_goal": user_goal,
        "feedback_mode": feedback_mode,
        "diagnosis": diagnosis,
        "trace_summary": [
            {
                "loop": t.get("loop"),
                "patch": t.get("applied_patch"),
                "metrics": (t.get("diagnosis") or {}).get("metrics_summary"),
                "n_issues": (t.get("diagnosis") or {}).get("n_issues"),
            }
            for t in trace[-5:]
        ],
        "knobs": context["knobs"],
        "playbook_excerpt": context["playbook_excerpt"],
        "recent_lessons": context["recent_lessons"],
        "empirical_kb": context.get("empirical_kb"),
        "method_catalog_ids": [m["id"] for m in catalog],
        "current_spec": spec.to_dict(),
    }
    user_prompt = json.dumps(user_payload, ensure_ascii=False)
    system_prompt = _patch_system_prompt(feedback_mode=feedback_mode)

    backend = APIBackend()
    token_estimate = backend.build_messages_and_calculate_token(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
    )
    logger.info(f"Strategy agent token estimate (input): {token_estimate}")

    response = backend.build_messages_and_create_chat_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=True,
        json_target_type=dict,
    )
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        payload = {"stop": False, "reasoning": response, "spec_patch": {}}

    patch, warnings = validate_spec_patch(payload.get("spec_patch") or {})
    payload["spec_patch"] = patch
    payload["patch_warnings"] = warnings
    payload["input_token_estimate"] = token_estimate
    return payload


def run_strategy_agent_loop(
    spec: StrategySpec,
    *,
    user_goal: str = "",
    max_loops: int = 5,
    output_root: Path | None = None,
    persist_lessons: bool = True,
    start_loop: int = 1,
    existing_trace: list[dict[str, Any]] | None = None,
    existing_best: dict[str, Any] | None = None,
    feedback_mode: bool = False,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Multi-loop: run → diagnose → LLM patch → re-run until done or max_loops."""
    max_loops = max(1, int(max_loops))
    agent_root = output_root or (default_output_root() / f"{spec.name}_agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    agent_root.mkdir(parents=True, exist_ok=True)

    current = copy.deepcopy(spec)
    current.output_dir = str(agent_root)
    trace: list[dict[str, Any]] = list(existing_trace or [])
    best = existing_best
    selected_method: str | None = None
    if trace:
        selected_method = trace[-1].get("selection_method")

    end_loop = start_loop + max_loops - 1
    for loop_idx in range(start_loop, end_loop + 1):
        loop_name = f"loop_{loop_idx:03d}"
        print(f"\n=== Strategy agent {loop_name} ===", flush=True)

        if loop_idx > 1 and selected_method and current.mode == "auto":
            current.mode = "single"
            current.method = selected_method

        payload = run_strategy_pipeline(current, run_subdir=loop_name)
        selected_method, _ = _extract_selection(payload)
        diagnosis = diagnose_strategy_run(payload, current)

        step = {
            "loop": loop_idx,
            "run_dir": payload.get("output_dir"),
            "spec": current.to_dict(),
            "diagnosis": diagnosis,
            "selection_method": selected_method,
        }
        trace.append(step)

        score = (diagnosis.get("metrics_summary") or {}).get("score")
        if best is None or (score is not None and score > (best.get("score") or -1e9)):
            best = {"loop": loop_idx, "score": score, "diagnosis": diagnosis, "spec": current.to_dict()}

        dump_strategy_spec(current, agent_root / f"spec_loop_{loop_idx:03d}.yaml")

        high_issues = [i for i in diagnosis.get("issues") or [] if i.get("severity") == "high"]
        if diagnosis.get("meets_constraints") and not high_issues:
            print(f"Strategy agent: constraints met at {loop_name}", flush=True)
            break

        if loop_idx >= end_loop:
            print("Strategy agent: reached max_loops for this round", flush=True)
            break

        proposal = propose_spec_patch(
            spec=current,
            diagnosis=diagnosis,
            trace=trace,
            user_goal=user_goal,
            feedback_mode=feedback_mode,
        )
        step["agent_proposal"] = proposal

        if proposal.get("stop"):
            print(f"Strategy agent: LLM requested stop — {proposal.get('reasoning', '')[:200]}", flush=True)
            break

        patch = proposal.get("spec_patch") or {}
        if not patch:
            print("Strategy agent: empty patch; stopping", flush=True)
            break

        current = apply_spec_patch(current, patch)
        current.output_dir = str(agent_root)
        step["applied_patch"] = patch
        print(f"Applied patch: {json.dumps(patch, ensure_ascii=False)}", flush=True)

        if persist_lessons:
            append_lesson(
                {
                    "strategy_name": spec.name,
                    "user_goal": user_goal,
                    "issues": [i.get("code") for i in diagnosis.get("issues") or []],
                    "patch": patch,
                    "reasoning": proposal.get("reasoning"),
                    "expected_effect": proposal.get("expected_effect"),
                    "metrics_before": diagnosis.get("metrics_summary"),
                }
            )

    final_spec_path = agent_root / "spec_final.yaml"
    dump_strategy_spec(current, final_spec_path)

    report = {
        "updated_at": _now_iso(),
        "agent_root": str(agent_root),
        "user_goal": user_goal,
        "max_loops": max_loops,
        "start_loop": start_loop,
        "loops_run": len(trace),
        "final_spec_path": str(final_spec_path),
        "best": best,
        "trace": trace,
        "knobs_version": load_knobs().get("version"),
        "feedback_mode": feedback_mode,
    }
    report_path = agent_root / "agent_trace.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Strategy agent trace -> {report_path}", flush=True)

    if session is not None:
        write_optimization_summary(agent_root, report, session)
    return report


def run_strategy_agent_create(
    user_goal: str,
    *,
    template_path: str | Path | None = None,
    max_loops: int = 5,
    output_root: Path | None = None,
    name_hint: str | None = None,
) -> dict[str, Any]:
    """Mode A: user requirement → generate spec → auto optimize."""
    reset_token_session(label="strategy-agent-create")
    print("=== Strategy agent: generating initial spec from goal ===", flush=True)
    spec, create_payload = generate_strategy_spec_from_goal(
        user_goal,
        template_path=template_path,
        name_hint=name_hint,
    )
    print(create_payload.get("summary_for_user") or create_payload.get("reasoning", "")[:300], flush=True)

    agent_root = output_root or (default_output_root() / f"{spec.name}_agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    session = create_session(
        agent_root,
        initial_goal=user_goal,
        spec=spec,
        template_path=str(template_path) if template_path else None,
    )
    (agent_root / "create_proposal.json").write_text(
        json.dumps(create_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report = run_strategy_agent_loop(
        spec,
        user_goal=user_goal,
        max_loops=max_loops,
        output_root=agent_root,
        session=session,
    )
    report["create_proposal"] = create_payload
    report["session_id"] = session["session_id"]
    (agent_root / "agent_trace.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    attach_existing_session(agent_root, report)
    summary = write_optimization_summary(agent_root, report, load_session_safe(agent_root))
    report["summary_path"] = str(summary)
    return _attach_token_summary(report, label=f"strategy-agent-create:{spec.name}")


def run_strategy_agent_optimize(
    spec: StrategySpec,
    *,
    user_goal: str = "",
    max_loops: int = 5,
    output_root: Path | None = None,
) -> dict[str, Any]:
    """Mode B: existing spec → auto optimize."""
    reset_token_session(label="strategy-agent-optimize")
    agent_root = output_root or (default_output_root() / f"{spec.name}_agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    session = create_session(
        agent_root,
        initial_goal=user_goal or f"Optimize strategy {spec.name}",
        spec=spec,
        template_path=None,
    )
    effective_goal = user_goal or session["initial_goal"]
    report = run_strategy_agent_loop(
        spec,
        user_goal=effective_goal,
        max_loops=max_loops,
        output_root=agent_root,
        session=session,
    )
    attach_existing_session(agent_root, report)
    summary = write_optimization_summary(agent_root, report, load_session_safe(agent_root))
    report["summary_path"] = str(summary)
    report["session_id"] = session["session_id"]
    return _attach_token_summary(report, label=f"strategy-agent-optimize:{spec.name}")


def run_strategy_agent_continue(
    agent_root: str | Path,
    user_feedback: str,
    *,
    max_loops: int = 3,
) -> dict[str, Any]:
    """Mode C: after user reviews results, apply feedback and keep optimizing."""
    reset_token_session(label="strategy-agent-continue")
    agent_root = Path(agent_root)
    spec, trace, best, session = load_resume_state(agent_root)
    begin_feedback_round(agent_root, user_feedback)

    effective_goal = build_effective_goal(session, user_feedback)
    start_loop = (session.get("total_loops") or len(trace)) + 1

    spec.output_dir = str(agent_root)
    report = run_strategy_agent_loop(
        spec,
        user_goal=effective_goal,
        max_loops=max_loops,
        output_root=agent_root,
        start_loop=start_loop,
        existing_trace=trace,
        existing_best=best,
        feedback_mode=True,
        session=session,
    )
    finish_feedback_round(agent_root, ended_loop=report.get("loops_run") or start_loop + max_loops - 1, report=report)
    session = load_session_safe(agent_root)
    summary = write_optimization_summary(agent_root, report, session)
    report["summary_path"] = str(summary)
    report["session_id"] = session.get("session_id")
    report["user_feedback"] = user_feedback
    return _attach_token_summary(report, label="strategy-agent-continue")


def load_session_safe(agent_root: Path | str) -> dict[str, Any]:
    from rdagent.scenarios.qlib.strategy.agent_session import load_session

    try:
        return load_session(agent_root)
    except FileNotFoundError:
        return {}


def get_session_status(agent_root: str | Path) -> dict[str, Any]:
    agent_root = Path(agent_root)
    session = load_session_safe(agent_root)
    trace_file = agent_root / "agent_trace.json"
    report = {}
    if trace_file.exists():
        report = json.loads(trace_file.read_text(encoding="utf-8"))
    best = report.get("best") or {}
    diag = best.get("diagnosis") or {}
    return {
        "session": session,
        "agent_root": str(agent_root),
        "summary_path": str(agent_root / "optimization_summary.md"),
        "best_loop": best.get("loop"),
        "best_metrics": diag.get("metrics_summary"),
        "meets_constraints": diag.get("meets_constraints"),
        "total_loops": report.get("loops_run"),
        "status": session.get("status"),
    }
