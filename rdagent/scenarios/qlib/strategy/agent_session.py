"""Persist strategy agent sessions for create → optimize → user feedback cycles."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rdagent.scenarios.qlib.strategy.spec import StrategySpec, dump_strategy_spec, load_strategy_spec


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_path(agent_root: Path | str) -> Path:
    return Path(agent_root) / "session.json"


def trace_path(agent_root: Path | str) -> Path:
    return Path(agent_root) / "agent_trace.json"


def load_session(agent_root: Path | str) -> dict[str, Any]:
    path = session_path(agent_root)
    if not path.exists():
        raise FileNotFoundError(f"No session.json under {agent_root}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_session(agent_root: Path | str, session: dict[str, Any]) -> Path:
    agent_root = Path(agent_root)
    agent_root.mkdir(parents=True, exist_ok=True)
    session["updated_at"] = _now_iso()
    path = session_path(agent_root)
    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def create_session(
    agent_root: Path | str,
    *,
    initial_goal: str,
    spec: StrategySpec,
    template_path: str | None = None,
) -> dict[str, Any]:
    agent_root = Path(agent_root)
    agent_root.mkdir(parents=True, exist_ok=True)
    session = {
        "session_id": uuid.uuid4().hex[:12],
        "agent_root": str(agent_root),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "status": "optimizing",
        "initial_goal": initial_goal,
        "template_path": template_path,
        "feedback_rounds": [],
        "total_loops": 0,
        "best_loop": None,
        "best_score": None,
        "spec_initial_path": str(agent_root / "spec_initial.yaml"),
        "spec_final_path": None,
        "trace_path": str(trace_path(agent_root)),
        "summary_path": str(agent_root / "optimization_summary.md"),
    }
    dump_strategy_spec(spec, session["spec_initial_path"])
    save_session(agent_root, session)
    return session


def attach_existing_session(agent_root: Path | str, report: dict[str, Any]) -> dict[str, Any]:
    """Create or refresh session.json from an completed agent trace."""
    agent_root = Path(agent_root)
    if session_path(agent_root).exists():
        session = load_session(agent_root)
    else:
        session = {
            "session_id": uuid.uuid4().hex[:12],
            "agent_root": str(agent_root),
            "created_at": report.get("updated_at") or _now_iso(),
            "initial_goal": report.get("user_goal") or "",
            "feedback_rounds": [],
            "template_path": report.get("template_path"),
        }
    best = report.get("best") or {}
    session.update(
        {
            "status": "awaiting_feedback",
            "updated_at": _now_iso(),
            "total_loops": report.get("loops_run") or len(report.get("trace") or []),
            "best_loop": best.get("loop"),
            "best_score": best.get("score"),
            "spec_final_path": report.get("final_spec_path"),
            "trace_path": str(trace_path(agent_root)),
            "summary_path": str(agent_root / "optimization_summary.md"),
        }
    )
    save_session(agent_root, session)
    return session


def begin_feedback_round(agent_root: Path | str, feedback: str) -> dict[str, Any]:
    session = load_session(agent_root)
    session["status"] = "optimizing"
    session.setdefault("feedback_rounds", []).append(
        {
            "feedback": feedback,
            "started_at": _now_iso(),
            "started_loop": (session.get("total_loops") or 0) + 1,
            "ended_loop": None,
        }
    )
    save_session(agent_root, session)
    return session


def finish_feedback_round(agent_root: Path | str, *, ended_loop: int, report: dict[str, Any]) -> dict[str, Any]:
    session = load_session(agent_root)
    if session.get("feedback_rounds"):
        session["feedback_rounds"][-1]["ended_loop"] = ended_loop
        session["feedback_rounds"][-1]["ended_at"] = _now_iso()
    best = report.get("best") or {}
    session.update(
        {
            "status": "awaiting_feedback",
            "total_loops": report.get("loops_run") or ended_loop,
            "best_loop": best.get("loop"),
            "best_score": best.get("score"),
            "spec_final_path": report.get("final_spec_path"),
        }
    )
    save_session(agent_root, session)
    return session


def load_resume_state(agent_root: Path | str) -> tuple[StrategySpec, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]]:
    agent_root = Path(agent_root)
    session = load_session(agent_root)
    spec_path = session.get("spec_final_path") or session.get("spec_initial_path")
    if not spec_path or not Path(spec_path).exists():
        raise FileNotFoundError(f"Cannot find spec to resume under {agent_root}")
    spec = load_strategy_spec(spec_path)

    trace: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    tp = trace_path(agent_root)
    if tp.exists():
        report = json.loads(tp.read_text(encoding="utf-8"))
        trace = report.get("trace") or []
        best = report.get("best")

    selected_method = None
    if trace:
        selected_method = trace[-1].get("selection_method")

    return spec, trace, best, session


def build_effective_goal(session: dict[str, Any], extra_feedback: str = "") -> str:
    parts = []
    if session.get("initial_goal"):
        parts.append(f"初始目标: {session['initial_goal']}")
    for rnd in session.get("feedback_rounds") or []:
        fb = rnd.get("feedback")
        if fb:
            parts.append(f"用户反馈: {fb}")
    if extra_feedback:
        parts.append(f"最新反馈: {extra_feedback}")
    return "\n".join(parts)


def write_optimization_summary(agent_root: Path | str, report: dict[str, Any], session: dict[str, Any] | None = None) -> Path:
    agent_root = Path(agent_root)
    best = report.get("best") or {}
    diag = best.get("diagnosis") or {}
    ms = diag.get("metrics_summary") or {}
    issues = diag.get("issues") or []

    lines = [
        "# Strategy Agent 优化结果",
        "",
        f"- Session: `{session.get('session_id') if session else 'n/a'}`",
        f"- Agent root: `{agent_root}`",
        f"- 状态: **{session.get('status') if session else 'n/a'}**（可用 `strategy-agent continue` 继续提建议）",
        "",
        "## 目标",
        "",
        report.get("user_goal") or session.get("initial_goal") if session else "",
        "",
        "## 最优轮次",
        "",
        f"- Loop: **{best.get('loop')}**  score={best.get('score')}",
        f"- 满足约束: **{diag.get('meets_constraints')}**",
        f"- Method: `{diag.get('method_id')}`",
        "",
        "### 样本外指标",
        "",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| Net Sharpe | {ms.get('sharpe_annualized')} |",
        f"| Gross Sharpe | {ms.get('gross_sharpe_annualized')} |",
        f"| 年化收益 | {ms.get('annualized_return_approx')} |",
        f"| 最大回撤 | {ms.get('max_drawdown')} |",
        f"| 换手 | {ms.get('turnover_mean')} |",
        f"| Net 累计 | {ms.get('cumulative_return')} |",
        f"| Gross 累计 | {ms.get('gross_cumulative_return')} |",
        "",
        "## 仍存在的问题",
        "",
    ]
    if issues:
        for issue in issues:
            lines.append(f"- **{issue.get('code')}** ({issue.get('severity')}): {issue.get('detail')}")
    else:
        lines.append("- 无（或已满足约束）")

    lines.extend(
        [
            "",
            "## 最终 Spec",
            "",
            f"见 `{report.get('final_spec_path')}`",
            "",
            "## 迭代历史",
            "",
        ]
    )
    for step in report.get("trace") or []:
        proposal = step.get("agent_proposal") or {}
        patch = step.get("applied_patch") or proposal.get("spec_patch") or {}
        sm = (step.get("diagnosis") or {}).get("metrics_summary") or {}
        lines.append(
            f"- Loop {step.get('loop')}: Sharpe={sm.get('sharpe_annualized')} "
            f"turnover={sm.get('turnover_mean')} patch={json.dumps(patch, ensure_ascii=False)}"
        )
        if proposal.get("reasoning"):
            lines.append(f"  - 推理: {str(proposal.get('reasoning'))[:240]}")

    if session and session.get("feedback_rounds"):
        lines.extend(["", "## 用户反馈轮次", ""])
        for i, rnd in enumerate(session["feedback_rounds"], 1):
            lines.append(
                f"{i}. `{rnd.get('feedback')}` (loop {rnd.get('started_loop')}–{rnd.get('ended_loop') or '?'})"
            )

    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "若需继续优化，执行：",
            "",
            "```bash",
            f"python -m paper_factor_cli.main strategy-agent continue \\",
            f"  --session {agent_root} \\",
            f'  --feedback "你的新建议" \\',
            "  --max-loops 3",
            "```",
            "",
        ]
    )

    out = agent_root / "optimization_summary.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
