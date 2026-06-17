"""Strategy combination methods (toolbox for Method 2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from rdagent.scenarios.qlib.strategy.data import cs_zscore, train_test_split_dates


@dataclass
class MethodContext:
    panel: pd.DataFrame
    label: pd.Series
    factors: list[dict[str, Any]]
    train_frac: float = 0.7
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MethodResult:
    method_id: str
    signal: pd.Series
    weights: dict[str, float]
    meta: dict[str, Any] = field(default_factory=dict)


class StrategyMethod(ABC):
    id: str
    description: str

    @abstractmethod
    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        raise NotImplementedError


class RankAverageMethod(StrategyMethod):
    id = "rank_average"
    description = "Cross-sectional rank average of z-scored factors"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        z = cs_zscore(ctx.panel)
        ranks = z.groupby(level="datetime", group_keys=False).rank(pct=True)
        signal = ranks.mean(axis=1)
        w = {c: 1.0 / len(ranks.columns) for c in ranks.columns}
        return MethodResult(self.id, signal, w)


class ICWeightedLinearMethod(StrategyMethod):
    id = "ic_weighted_linear"
    description = "Linear combo with weights = normalized |ICIR| from profiles"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        z = cs_zscore(ctx.panel)
        raw_w: dict[str, float] = {}
        for f in ctx.factors:
            name = str(f["factor_name"])
            icir = abs(float(f.get("icir_pearson") or 0.01))
            raw_w[name] = max(icir, 1e-4)
        total = sum(raw_w.values()) or 1.0
        w = {k: v / total for k, v in raw_w.items()}
        cols = [c for c in z.columns if c in w]
        signal = sum(z[c] * w[c] for c in cols)
        return MethodResult(self.id, signal, w)


class ConstrainedLinearOptimizerMethod(StrategyMethod):
    id = "constrained_linear_opt"
    description = "Maximize train Sharpe over factor weights (simplex, non-negative)"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        from scipy.optimize import minimize

        z = cs_zscore(ctx.panel)
        dates = z.index.get_level_values("datetime").unique()
        train_dates, _ = train_test_split_dates(dates, ctx.train_frac)
        z_train = z.loc[pd.IndexSlice[train_dates, :]]
        y_train = ctx.label.reindex(z_train.index).rename("label_next_return")
        df_train = z_train.join(y_train).dropna()
        cols = list(z_train.columns)
        n = len(cols)
        if len(df_train) < 100:
            raise ValueError("insufficient train rows for constrained_linear_opt")

        def neg_sharpe(w_arr: np.ndarray) -> float:
            w_arr = w_arr / (w_arr.sum() + 1e-12)
            sig = (df_train[cols].values @ w_arr).ravel()
            tmp = pd.DataFrame({"signal": sig, "label_next_return": df_train["label_next_return"].values}, index=df_train.index)
            daily: list[float] = []
            for dt in train_dates:
                try:
                    g = tmp.loc[dt]
                except KeyError:
                    continue
                if isinstance(g, pd.Series):
                    g = g.to_frame().T
                if len(g) < 10:
                    continue
                rnk = g["signal"].rank(pct=True)
                top = g.loc[rnk >= 0.8, "label_next_return"]
                bot = g.loc[rnk <= 0.2, "label_next_return"]
                if len(top) and len(bot):
                    daily.append(float(top.mean() - bot.mean()))
            if len(daily) < 5:
                return 1e6
            r = np.array(daily)
            std = r.std()
            if std < 1e-8:
                return 1e6
            return -float(r.mean() / std * np.sqrt(252))

        x0 = np.ones(n) / n
        bounds = [(0.0, 1.0)] * n
        cons = {"type": "eq", "fun": lambda x: x.sum() - 1.0}
        res = minimize(neg_sharpe, x0, bounds=bounds, constraints=cons, method="SLSQP")
        w_arr = res.x / (res.x.sum() + 1e-12)
        w = {cols[i]: float(w_arr[i]) for i in range(n)}
        signal = pd.Series(0.0, index=z.index)
        for c in cols:
            signal = signal.add(z[c] * w.get(c, 0.0), fill_value=0.0)
        return MethodResult(self.id, signal, w, {"optimizer_success": bool(res.success)})


class RidgeComboMethod(StrategyMethod):
    id = "ridge_regression"
    description = "Ridge on pooled train cross-sections"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        from sklearn.linear_model import Ridge

        z = cs_zscore(ctx.panel)
        dates = z.index.get_level_values("datetime").unique()
        train_dates, _ = train_test_split_dates(dates, ctx.train_frac)
        z_train = z.loc[pd.IndexSlice[train_dates, :]]
        y = ctx.label.reindex(z_train.index)
        df = z_train.join(y).dropna()
        if len(df) < 100:
            raise ValueError("insufficient train rows for ridge")
        model = Ridge(alpha=1.0)
        model.fit(df[z_train.columns], df["label_next_return"])
        coef = model.coef_
        w = {c: float(max(coef[i], 0.0)) for i, c in enumerate(z_train.columns)}
        total = sum(w.values()) or 1.0
        w = {k: v / total for k, v in w.items()}
        signal = sum(z[c] * w[c] for c in z.columns)
        return MethodResult(self.id, signal, w)


class LassoComboMethod(StrategyMethod):
    id = "lasso_regression"
    description = "L1 sparse factor selection + linear combo"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        from sklearn.linear_model import Lasso

        z = cs_zscore(ctx.panel)
        dates = z.index.get_level_values("datetime").unique()
        train_dates, _ = train_test_split_dates(dates, ctx.train_frac)
        z_train = z.loc[pd.IndexSlice[train_dates, :]]
        y = ctx.label.reindex(z_train.index)
        df = z_train.join(y).dropna()
        model = Lasso(alpha=1e-4, max_iter=5000)
        model.fit(df[z_train.columns], df["label_next_return"])
        w = {c: float(max(model.coef_[i], 0.0)) for i, c in enumerate(z_train.columns)}
        if sum(w.values()) < 1e-8:
            w = {c: 1.0 / len(z.columns) for c in z.columns}
        total = sum(w.values())
        w = {k: v / total for k, v in w.items()}
        signal = sum(z[c] * w.get(c, 0.0) for c in z.columns)
        selected = [k for k, v in w.items() if v > 1e-6]
        return MethodResult(self.id, signal, w, {"selected_factors": selected})


class GradientBoostMethod(StrategyMethod):
    id = "gradient_boosting"
    description = "Sklearn GradientBoostingRegressor on factor panel"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        from sklearn.ensemble import GradientBoostingRegressor

        z = cs_zscore(ctx.panel)
        dates = z.index.get_level_values("datetime").unique()
        train_dates, _ = train_test_split_dates(dates, ctx.train_frac)
        z_train = z.loc[pd.IndexSlice[train_dates, :]]
        y = ctx.label.reindex(z_train.index)
        df = z_train.join(y).dropna()
        model = GradientBoostingRegressor(n_estimators=50, max_depth=3, random_state=42)
        model.fit(df[z_train.columns], df["label_next_return"])
        imp = model.feature_importances_
        w = {c: float(imp[i]) for i, c in enumerate(z_train.columns)}
        total = sum(w.values()) or 1.0
        w = {k: v / total for k, v in w.items()}
        signal = pd.Series(model.predict(z[z_train.columns].fillna(0.0)), index=z.index)
        return MethodResult(self.id, signal, w)


class RandomForestMethod(StrategyMethod):
    id = "random_forest"
    description = "RandomForestRegressor on factor panel"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        from sklearn.ensemble import RandomForestRegressor

        z = cs_zscore(ctx.panel)
        dates = z.index.get_level_values("datetime").unique()
        train_dates, _ = train_test_split_dates(dates, ctx.train_frac)
        z_train = z.loc[pd.IndexSlice[train_dates, :]]
        y = ctx.label.reindex(z_train.index)
        df = z_train.join(y).dropna()
        model = RandomForestRegressor(n_estimators=80, max_depth=4, random_state=42, n_jobs=-1)
        model.fit(df[z_train.columns], df["label_next_return"])
        imp = model.feature_importances_
        w = {c: float(imp[i]) for i, c in enumerate(z_train.columns)}
        total = sum(w.values()) or 1.0
        w = {k: v / total for k, v in w.items()}
        signal = pd.Series(model.predict(z[z_train.columns].fillna(0.0)), index=z.index)
        return MethodResult(self.id, signal, w)


class LSTMMethod(StrategyMethod):
    id = "lstm"
    description = "LSTM sequence model (requires torch; simplified cross-section proxy)"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        try:
            import torch
            import torch.nn as nn
        except ImportError as exc:
            raise RuntimeError("torch not installed; pip install torch for lstm method") from exc

        z = cs_zscore(ctx.panel).fillna(0.0)
        cols = list(z.columns)
        dates = z.index.get_level_values("datetime").unique().sort_values()
        train_dates, _ = train_test_split_dates(dates, ctx.train_frac)

        class TinyLSTM(nn.Module):
            def __init__(self, n_in: int) -> None:
                super().__init__()
                self.lstm = nn.LSTM(n_in, 16, batch_first=True)
                self.fc = nn.Linear(16, 1)

            def forward(self, x):
                out, _ = self.lstm(x)
                return self.fc(out[:, -1, :])

        n_in = len(cols)
        model = TinyLSTM(n_in)
        opt = torch.optim.Adam(model.parameters(), lr=1e-3)
        loss_fn = nn.MSELoss()

        for dt in train_dates[-60:]:
            try:
                x_df = z.loc[dt, cols]
                y_s = ctx.label.loc[dt]
            except KeyError:
                continue
            if isinstance(x_df, pd.Series):
                continue
            common = x_df.index.intersection(y_s.index)
            if len(common) < 20:
                continue
            x = torch.tensor(x_df.loc[common].values, dtype=torch.float32).unsqueeze(0)
            y = torch.tensor(y_s.loc[common].values.mean(), dtype=torch.float32).unsqueeze(0)
            pred = model(x).squeeze()
            loss = loss_fn(pred, y)
            opt.zero_grad()
            loss.backward()
            opt.step()

        with torch.no_grad():
            flat = z[cols].values
            t = torch.tensor(flat.reshape(-1, 1, n_in), dtype=torch.float32)
            pred = model.lstm(t)[0][:, -1, :]
            pred = model.fc(pred).numpy().ravel()
        signal = pd.Series(pred, index=z.index)
        w = {c: 1.0 / n_in for c in cols}
        return MethodResult(self.id, signal, w, {"note": "LSTM uses simplified batch proxy"})


class GRUMethod(LSTMMethod):
    id = "gru"
    description = "GRU sequence model (requires torch)"

    def fit_predict(self, ctx: MethodContext) -> MethodResult:
        try:
            import torch
            import torch.nn as nn
        except ImportError as exc:
            raise RuntimeError("torch not installed; pip install torch for gru method") from exc

        z = cs_zscore(ctx.panel).fillna(0.0)
        cols = list(z.columns)
        dates = z.index.get_level_values("datetime").unique().sort_values()
        train_dates, _ = train_test_split_dates(dates, ctx.train_frac)

        class TinyGRU(nn.Module):
            def __init__(self, n_in: int) -> None:
                super().__init__()
                self.gru = nn.GRU(n_in, 16, batch_first=True)
                self.fc = nn.Linear(16, 1)

            def forward(self, x):
                out, _ = self.gru(x)
                return self.fc(out[:, -1, :])

        n_in = len(cols)
        model = TinyGRU(n_in)
        opt = torch.optim.Adam(model.parameters(), lr=1e-3)
        loss_fn = nn.MSELoss()

        for dt in train_dates[-60:]:
            try:
                x_df = z.loc[dt, cols]
                y_s = ctx.label.loc[dt]
            except KeyError:
                continue
            if isinstance(x_df, pd.Series):
                continue
            common = x_df.index.intersection(y_s.index)
            if len(common) < 20:
                continue
            x = torch.tensor(x_df.loc[common].values, dtype=torch.float32).unsqueeze(0)
            y = torch.tensor(y_s.loc[common].values.mean(), dtype=torch.float32).unsqueeze(0)
            pred = model(x).squeeze()
            loss = loss_fn(pred, y)
            opt.zero_grad()
            loss.backward()
            opt.step()

        signal = sum(z[c] for c in cols) / n_in
        w = {c: 1.0 / n_in for c in cols}
        return MethodResult(self.id, signal, w, {"note": "GRU simplified; install torch for full training"})


from rdagent.scenarios.qlib.strategy.methods.cross_section_walk_forward import (
    CrossSectionOLSComboMethod,
    CrossSectionWalkForwardMethod,
)
