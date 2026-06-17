"""Generic signal preprocessing driven by StrategySpec knobs (not agent-specific logic)."""

from __future__ import annotations

import pandas as pd

from rdagent.scenarios.qlib.strategy.spec import StrategySpec


def apply_signal_smooth(signal: pd.Series, days: int) -> pd.Series:
    if days is None or days <= 1:
        return signal
    return signal.groupby(level="instrument", group_keys=False).transform(
        lambda s: s.rolling(int(days), min_periods=1).mean()
    )


def preprocess_signal(signal: pd.Series, spec: StrategySpec) -> pd.Series:
    return apply_signal_smooth(signal, spec.signal_smooth_days)
