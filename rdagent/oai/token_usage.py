"""Session-level LLM token / cost tracking for CLI and agent runs."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class TokenUsageSession:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_calls: int = 0
    cost_usd: float = 0.0
    models: dict[str, int] = field(default_factory=dict)
    label: str = ""
    started_at: str = ""

    def reset(self, *, label: str = "") -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_calls = 0
        self.cost_usd = 0.0
        self.models = {}
        self.label = label
        self.started_at = datetime.now(timezone.utc).isoformat()

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def record(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost: float | None = None,
        model: str = "",
    ) -> None:
        self.prompt_tokens += max(0, int(prompt_tokens))
        self.completion_tokens += max(0, int(completion_tokens))
        self.total_calls += 1
        if cost is not None and cost == cost:  # skip NaN
            self.cost_usd += float(cost)
        if model:
            self.models[model] = self.models.get(model, 0) + 1

    def summary_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "started_at": self.started_at,
            "total_calls": self.total_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "models": dict(self.models),
        }

    def echo(self, *, label: str | None = None) -> dict[str, Any]:
        title = label or self.label or "LLM session"
        summary = self.summary_dict()
        print(
            f"\n=== Token usage ({title}) ===\n"
            f"  API calls:     {summary['total_calls']}\n"
            f"  Input tokens:  {summary['prompt_tokens']:,}\n"
            f"  Output tokens: {summary['completion_tokens']:,}\n"
            f"  Total tokens:  {summary['total_tokens']:,}\n"
            f"  Est. cost USD: ${summary['cost_usd']:.4f}\n"
            f"  Models:        {summary['models'] or '(none)'}\n",
            flush=True,
        )
        return summary

    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**self.summary_dict(), "recorded_at": datetime.now(timezone.utc).isoformat()}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


_lock = threading.Lock()
_session = TokenUsageSession()


def get_token_session() -> TokenUsageSession:
    return _session


def reset_token_session(*, label: str = "") -> TokenUsageSession:
    with _lock:
        _session.reset(label=label)
    return _session


def echo_token_usage(*, label: str | None = None, save_path: Path | str | None = None) -> dict[str, Any]:
    with _lock:
        summary = _session.echo(label=label)
        if save_path:
            _session.save(save_path)
    return summary
