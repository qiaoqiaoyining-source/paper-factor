"""Generic walk-forward cross-section regression (configurable via method_params / toolbox recipes)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from rdagent.scenarios.qlib.strategy.data import cs_zscore, train_test_split_dates
from rdagent.scenarios.qlib.strategy.methods import MethodContext, MethodResult, StrategyMethod


def _to_monthly_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Last trading observation per calendar month per instrument."""
    df = panel.reset_index()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["_month"] = df["datetime"].dt.to_period("M")
    last = df.sort_values("datetime").groupby(["_month", "instrument"], as_index=False).last()
    last = last.drop(columns=["_month"]).set_index(["datetime", "instrument"])
    return last.sort_index()


def _monthly_label(label: pd.Series, panel: pd.DataFrame) -> pd.Series:
    aligned = label.reindex(panel.index)
    return _to_monthly_panel(aligned.to_frame("_y"))["_y"]


def _build_ma_features(m_panel: pd.DataFrame, windows: list[int], *, suffix: str = "_MA{w}") -> pd.DataFrame:
    parts: list[pd.Series] = []
    for col in m_panel.columns:
        wide = m_panel[col].unstack("instrument")
        for w in windows:
            name = f"{col}{suffix.format(w=w)}"
            if w == 0:
                feat = wide
            else:
                feat = wide.rolling(w + 1, min_periods=1).mean()
            parts.append(feat.stack(future_stack=True).rename(name))
    return pd.concat(parts, axis=1).sort_index()


def _monthly_to_daily_signal(monthly: pd.Series, daily_index: pd.MultiIndex) -> pd.Series:
    wide = monthly.unstack("instrument")
    daily_dates = pd.Index(daily_index.get_level_values("datetime").unique().sort_values())
    daily_instruments = pd.Index(daily_index.get_level_values("instrument").unique())
    wide = wide.reindex(columns=daily_instruments)
    expanded = wide.reindex(daily_dates, method="ffill")
    out = expanded.stack(future_stack=True)
    out.index.names = ["datetime", "instrument"]
    return out.reindex(daily_index)


def _walk_forward_regression(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    train_frac: float,
    min_cross_section: int,
    per_factor: bool = False,
    feature_suffix: str = "_MA{w}",
) -> tuple[pd.Series, dict[str, float]]:
    dates = X.index.get_level_values("datetime").unique().sort_values()
    train_dates, test_dates = train_test_split_dates(dates, train_frac)
    if len(train_dates) < 2:
        raise ValueError("insufficient resampled dates for walk-forward regression")

    signal_parts: list[tuple[Any, pd.Series]] = []
    beta_acc: dict[str, list[float]] = {}

    for dt in test_dates:
        pos = int(dates.get_indexer([dt])[0])
        if pos <= 0:
            continue
        prev = dates[pos - 1]
        try:
            x_prev = X.loc[prev]
            if isinstance(x_prev, pd.Series):
                x_prev = x_prev.to_frame().T
            x_prev = x_prev.dropna(how="all")
            y_now = y.loc[dt]
            if not isinstance(y_now, pd.Series):
                y_now = pd.Series(y_now)
            y_now = y_now.reindex(x_prev.index)
        except KeyError:
            continue

        if per_factor:
            suffix_token = feature_suffix.format(w=0).split("{w}")[0] or "_MA"
            base_cols = sorted({c.rsplit(suffix_token, 1)[0] for c in X.columns if suffix_token in c})
            combo = pd.Series(0.0, index=x_prev.index)
            n_used = 0
            for base in base_cols:
                sub_cols = [c for c in X.columns if c.startswith(f"{base}{suffix_token}")]
                if not sub_cols:
                    continue
                common = x_prev.index.intersection(y_now.dropna().index)
                if len(common) < min_cross_section:
                    continue
                x_mat = np.nan_to_num(x_prev.reindex(common)[sub_cols].values, nan=0.0)
                y_vec = y_now.reindex(common).values
                if np.allclose(x_mat.std(axis=0), 0, equal_nan=True):
                    continue
                beta, *_ = np.linalg.lstsq(x_mat, y_vec, rcond=None)
                try:
                    x_row = X.loc[dt, sub_cols]
                except KeyError:
                    continue
                if isinstance(x_row, pd.Series):
                    x_row = x_row.to_frame().T
                x_now = np.nan_to_num(x_row.reindex(common).fillna(0.0).values, nan=0.0)
                if x_now.shape[1] != len(beta):
                    continue
                incr = pd.Series(x_now @ beta, index=common)
                combo = combo.add(incr, fill_value=0.0)
                n_used += 1
                for i, c in enumerate(sub_cols):
                    beta_acc.setdefault(c, []).append(float(beta[i]))
            if n_used == 0:
                continue
            combo /= n_used
            signal_parts.append((dt, combo))
        else:
            common = x_prev.index.intersection(y_now.dropna().index)
            if len(common) < min_cross_section:
                continue
            x_mat = np.nan_to_num(x_prev.reindex(common).values, nan=0.0)
            y_vec = y_now.reindex(common).values
            if np.allclose(x_mat.std(axis=0), 0, equal_nan=True):
                continue
            beta, *_ = np.linalg.lstsq(x_mat, y_vec, rcond=None)
            try:
                x_row = X.loc[dt]
            except KeyError:
                continue
            if isinstance(x_row, pd.Series):
                x_row = x_row.to_frame().T
            x_now = np.nan_to_num(x_row.reindex(common).fillna(0.0).values, nan=0.0)
            if x_now.shape[1] != len(beta):
                continue
            sig = pd.Series(x_now @ beta, index=common)
            signal_parts.append((dt, sig))
            for i, c in enumerate(X.columns):
                beta_acc.setdefault(c, []).append(float(beta[i]))

    if not signal_parts:
        raise ValueError(
            "walk-forward regression produced no signals; check factor coverage, resample frequency, or min_cross_section"
        )

    chunks: list[pd.Series] = []
    for dt, s in signal_parts:
        idx = pd.MultiIndex.from_product([[dt], s.index], names=["datetime", "instrument"])
        chunks.append(pd.Series(s.values, index=idx))
    monthly = pd.concat(chunks).sort_index()
    weights = {k: float(np.mean(v)) for k, v in beta_acc.items()}
    return monthly.sort_index(), weights


class CrossSectionWalkForwardMethod(StrategyMethod):
    """
    Configurable walk-forward cross-section OLS.

    method_params (from toolbox recipe):
      resample: monthly | daily  (default monthly)
      ma_windows: e.g. [0, 1, 4, 8]
      combination: multivariate | per_factor_equal
      min_cross_section: int
      feature_suffix: str template for lagged feature names (default "_MA{w}")
      expand_signal: ffill_to_daily | none
    """

    id = "cross_section_walk_forward"
    description = "Walk-forward cross-section OLS with optional MA features and monthly resample"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        extra = ctx.extra or {}
        resample = str(extra.get("resample") or "monthly").lower()
        windows = list(extra.get("ma_windows") or [])
        combination = str(extra.get("combination") or "multivariate").lower()
        min_cs = int(extra.get("min_cross_section") or 20)
        feature_suffix = str(extra.get("feature_suffix") or "_MA{w}")
        expand = str(extra.get("expand_signal") or "ffill_to_daily").lower()

        panel = ctx.panel.sort_index()
        label = ctx.label.reindex(panel.index)

        if resample == "monthly":
            work_panel = _to_monthly_panel(panel)
            if work_panel.empty:
                raise ValueError("monthly resample produced empty panel")
            y = _monthly_label(label, panel).reindex(work_panel.index)
        else:
            work_panel = panel
            y = label.reindex(panel.index)

        if windows:
            X = _build_ma_features(work_panel, windows, suffix=feature_suffix)
        else:
            X = work_panel

        X = X[~X.index.duplicated(keep="last")]
        y = y.reindex(X.index)
        per_factor = combination in {"per_factor_equal", "per_factor", "forecast_combination"}
        monthly_sig, weights = _walk_forward_regression(
            X,
            y,
            train_frac=ctx.train_frac,
            min_cross_section=min_cs,
            per_factor=per_factor,
            feature_suffix=feature_suffix,
        )

        if expand == "ffill_to_daily" and resample == "monthly":
            signal = _monthly_to_daily_signal(monthly_sig, panel.index)
        else:
            signal = monthly_sig.reindex(panel.index)

        return MethodResult(
            self.id,
            signal,
            weights,
            {
                "resample": resample,
                "ma_windows": windows,
                "combination": combination,
                "n_features": len(X.columns),
                "min_cross_section": min_cs,
            },
        )


class CrossSectionOLSComboMethod(StrategyMethod):
    id = "cross_section_ols_combo"
    description = "Pooled cross-section OLS on z-scored factors (train period)"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        z = cs_zscore(ctx.panel)
        dates = z.index.get_level_values("datetime").unique()
        train_dates, _ = train_test_split_dates(dates, ctx.train_frac)
        z_train = z.loc[pd.IndexSlice[train_dates, :]]
        y = ctx.label.reindex(z_train.index)
        df = z_train.join(y).dropna()
        if len(df) < 100:
            raise ValueError("insufficient train rows for cross_section_ols_combo")
        cols = list(z_train.columns)
        beta, *_ = np.linalg.lstsq(df[cols].values, df["label_next_return"].values, rcond=None)
        w = {c: float(max(beta[i], 0.0)) for i, c in enumerate(cols)}
        total = sum(w.values()) or 1.0
        w = {k: v / total for k, v in w.items()}
        signal = sum(z[c] * w.get(c, 0.0) for c in cols)
        return MethodResult(self.id, signal, w)
