# Strategy Agent Playbook

面向 LLM 的策略诊断与修正模式库。**Agent 通过修改 StrategySpec（knobs.json）触发通用执行原语**，而不是在代码里写死「if 换手高 then …」。

## 1. 诊断 → 干预映射（模式，非硬编码）

| 现象 | 可能原因 | 可尝试的 spec 干预（选 1-3 个） |
|------|----------|--------------------------------|
| 换手过高 (`HIGH_TURNOVER`) | 信号日频抖动、因子多且弱相关、组合日调 | `signal_smooth_days`↑、`hold_buffer_frac`↑、`rebalance_period`↑、减少 `max_factors` |
| Gross 好 Net 差 (`GROSS_POSITIVE_NET_NEGATIVE`) | 成本被换手放大 | 同上 + 检查 `one_way_cost` 是否与研究假设一致（勿为刷 net 而改成本） |
| 回撤大 (`HIGH_DRAWDOWN`) | 因子权重集中、风格暴露、尾部股票 | `exclude_factors` 去掉 dominant 因子、`max_factors`↓、换 `method`（如 constrained_linear_opt） |
| 因子权重集中 (`FACTOR_WEIGHT_CONCENTRATION`) | 单一因子主导 composite | `exclude_factors`、提高 `min_icir`、换 `ic_weighted_linear` → `constrained_linear_opt` |
| Sharpe 低 (`LOW_SHARPE`) | 因子池弱、方法不匹配 | `min_icir`↑、`max_factors` 微调、`mode=auto` 重 sweep 或指定更强 `method` |
| 约束不满足 (`CONSTRAINT_VIOLATION`) | 多目标冲突 | 先修换手/成本类 issue，再修回撤；必要时略放宽 `max_turnover` 并记录 trade-off |

## 2. 干预原语说明

- **signal_smooth_days**：对每只股票信号做 rolling mean，降低 Rank 日频翻转。
- **hold_buffer_frac**：Top/Bottom  cohort 迟滞带；已在组合内的票需 rank 滑出更宽边界才换出。
- **rebalance_period**：每 N 日才允许调仓，中间持仓不变、换手为 0。
- **exclude_factors / include_factors**：从 profile 池增减因子，改变信号结构。
- **method / methods**：换组合算法（线性约束、IC 加权、ML 等）。

## 3. Loop 策略

1. 第一轮 `mode=auto` 全方法 sweep，选定 baseline method。
2. 后续轮次固定 `mode=single` + 已选 method（除非 agent 主动改 method）。
3. 每轮只改少量 knob；对比 `agent_trace.json` 中 metrics 是否改善。
4. `meets_constraints=true` 且无 high severity issue → `stop=true`。

## 4. 用户目标示例

- 「回撤太大」→ 优先查 `FACTOR_WEIGHT_CONCENTRATION`、`HIGH_DRAWDOWN`，再平滑/降频。
- 「换手太高」→ `signal_smooth_days`、`hold_buffer_frac`、`rebalance_period`。
- 「成本把收益吃掉了」→ 在保持 `one_way_cost` 真实前提下降换手。

## 5. 禁止

- 不要建议改 Python 源码或新增 hardcoded 规则。
- 不要通过调低 `one_way_cost` 来「修复」net 表现（除非用户明确要求敏感性分析）。
