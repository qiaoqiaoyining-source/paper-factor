"""Trading frictions: unified cost, limit up/down tradability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class TradingFrictionConfig:
    """Unified one-way cost (commission + slippage), e.g. 0.002 = 千二."""

    one_way_cost: float = 0.002  # 千二；0.0025 = 千二点五
    apply_limit_filter: bool = True
    limit_up_pct: float = 0.095  # ~10% A-share limit (9.5% threshold)
    limit_down_pct: float = -0.095
    apply_suspended_filter: bool = True


def extract_daily_pct_change(market: pd.DataFrame) -> pd.Series:
    """Return pct change series aligned to (datetime, instrument)."""
    if "$pct_chg" in market.columns:
        s = pd.to_numeric(market["$pct_chg"], errors="coerce")
        if s.notna().mean() > 0.5:
            # Tushare pct_chg often in percent units
            if s.abs().median() > 1.0:
                s = s / 100.0
            return s
    if "$close" in market.columns and "$pre_close" in market.columns:
        close = pd.to_numeric(market["$close"], errors="coerce")
        pre = pd.to_numeric(market["$pre_close"], errors="coerce")
        return close / pre - 1.0
    if "$close" in market.columns:
        close = pd.to_numeric(market["$close"], errors="coerce")
        return close.groupby(level="instrument").pct_change()
    raise ValueError("Cannot derive pct change from market panel")


def extract_suspended_flag(market: pd.DataFrame) -> pd.Series | None:
    for col in ("$paused", "$is_suspended", "paused"):
        if col in market.columns:
            return pd.to_numeric(market[col], errors="coerce").fillna(0) > 0
    return None


def _cohort_turnover(prev: set | None, curr: set) -> float:
    if prev is None or not curr:
        return 0.0
    union = prev | curr
    if not union:
        return 0.0
    return len(prev.symmetric_difference(curr)) / float(len(union))


def signal_to_long_short_returns(
    signal: pd.Series,
    label: pd.Series,
    *,
    top_frac: float = 0.2,
    bottom_frac: float = 0.2,
    hold_buffer_frac: float = 0.0,
    rebalance_period: int = 1,
    market: pd.DataFrame | None = None,
    friction: TradingFrictionConfig | None = None,
) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
    """
    Long-short daily returns with optional frictions.

    Returns (net_daily, gross_daily, meta).
    Cost model: each rebalance pays `one_way_cost` on traded notional of long leg + short leg.
    Limit rules (simplified):
      - Long pool: exclude limit-up (买不进), suspended
      - Short pool: exclude limit-down (卖空/开空受限 proxy), suspended
    Note: does not model stuck positions (涨停卖不出 / 跌停买不回) on exit — conservative bias on entries only.
    """
    friction = friction or TradingFrictionConfig()
    merged = pd.concat([signal.rename("signal"), label], axis=1, join="inner").dropna()

    pct_chg: pd.Series | None = None
    suspended: pd.Series | None = None
    if market is not None:
        try:
            pct_chg = extract_daily_pct_change(market)
        except ValueError:
            pct_chg = None
        if friction.apply_suspended_filter:
            suspended = extract_suspended_flag(market)

    gross_daily: list[float] = []
    net_daily: list[float] = []
    turnover_long: list[float] = []
    turnover_short: list[float] = []
    cost_drag: list[float] = []
    limit_skip_days = 0
    out_dates: list = []

    prev_top: set | None = None
    prev_bot: set | None = None
    dates = merged.index.get_level_values("datetime").unique().sort_values()
    rebalance_period = max(1, int(rebalance_period or 1))
    hold_buffer_frac = max(0.0, float(hold_buffer_frac or 0.0))
    day_idx = 0

    for dt in dates:
        try:
            g = merged.loc[dt]
        except KeyError:
            continue
        if isinstance(g, pd.Series):
            continue
        g = g.dropna(subset=["signal", "label_next_return"])
        if len(g) < 10:
            continue

        tradable = pd.Series(True, index=g.index)
        if friction.apply_limit_filter and pct_chg is not None:
            try:
                day_pct = pct_chg.loc[dt].reindex(g.index)
                tradable &= day_pct < friction.limit_up_pct
                tradable &= day_pct > friction.limit_down_pct
            except KeyError:
                pass
        if suspended is not None:
            try:
                day_susp = suspended.loc[dt].reindex(g.index).fillna(False)
                tradable &= ~day_susp.astype(bool)
            except KeyError:
                pass

        g_long = g.loc[tradable]
        g_short = g.copy()
        if friction.apply_limit_filter and pct_chg is not None:
            try:
                day_pct = pct_chg.loc[dt].reindex(g.index)
                # Short: avoid limit-down (cannot easily short / borrow proxy)
                g_short = g.loc[day_pct > friction.limit_down_pct]
            except KeyError:
                g_short = g
        if suspended is not None:
            try:
                g_short = g_short.loc[~suspended.loc[dt].reindex(g_short.index).fillna(False).astype(bool)]
            except KeyError:
                pass

        if len(g_long) < 10 or len(g_short) < 10:
            limit_skip_days += 1
            continue

        rnk_long = g_long["signal"].rank(pct=True, method="average")
        rnk_short = g_short["signal"].rank(pct=True, method="average")
        entry_top = 1.0 - top_frac
        exit_top = max(0.0, entry_top - hold_buffer_frac)
        entry_bot = bottom_frac
        exit_bot = min(1.0, entry_bot + hold_buffer_frac)

        if prev_top and hold_buffer_frac > 0:
            stay_top = set(g_long.index[rnk_long >= exit_top]) & prev_top
            new_top = set(g_long.index[rnk_long >= entry_top])
            top_idx = stay_top | new_top
        else:
            top_idx = set(g_long.index[rnk_long >= entry_top])

        if prev_bot and hold_buffer_frac > 0:
            stay_bot = set(g_short.index[rnk_short <= exit_bot]) & prev_bot
            new_bot = set(g_short.index[rnk_short <= entry_bot])
            bot_idx = stay_bot | new_bot
        else:
            bot_idx = set(g_short.index[rnk_short <= entry_bot])

        rebalance_today = day_idx % rebalance_period == 0
        if not rebalance_today and prev_top is not None and prev_bot is not None:
            top_idx = prev_top
            bot_idx = prev_bot
            t_long = 0.0
            t_short = 0.0
        else:
            t_long = _cohort_turnover(prev_top, top_idx)
            t_short = _cohort_turnover(prev_bot, bot_idx)
        if not top_idx or not bot_idx:
            continue

        top_valid = g.index.intersection(top_idx)
        bot_valid = g.index.intersection(bot_idx)
        if len(top_valid) < 1 or len(bot_valid) < 1:
            continue

        gross = float(
            g.loc[top_valid, "label_next_return"].mean() - g.loc[bot_valid, "label_next_return"].mean()
        )
        day_cost = friction.one_way_cost * (t_long + t_short)
        net = gross - day_cost

        gross_daily.append(gross)
        net_daily.append(net)
        turnover_long.append(t_long)
        turnover_short.append(t_short)
        cost_drag.append(day_cost)
        out_dates.append(dt)
        prev_top = top_idx
        prev_bot = bot_idx
        day_idx += 1

    gross_s = pd.Series(gross_daily, index=out_dates[: len(gross_daily)])
    net_s = pd.Series(net_daily, index=out_dates[: len(net_daily)])
    meta = {
        "turnover_mean": float(np.mean(turnover_long) + np.mean(turnover_short)) if turnover_long else None,
        "turnover_long_mean": float(np.mean(turnover_long)) if turnover_long else None,
        "turnover_short_mean": float(np.mean(turnover_short)) if turnover_short else None,
        "cost_drag_mean": float(np.mean(cost_drag)) if cost_drag else None,
        "one_way_cost": friction.one_way_cost,
        "limit_filter": friction.apply_limit_filter,
        "limit_skip_days": limit_skip_days,
        "hold_buffer_frac": hold_buffer_frac,
        "rebalance_period": rebalance_period,
        "friction_note": (
            "one_way_cost=commission+slippage per traded leg; "
            "limit filter excludes new entries at limit up/down (simplified)"
        ),
    }
    return net_s, gross_s, meta
