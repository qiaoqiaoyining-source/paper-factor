# 策略框架说明

基于 E 盘 **246+ factor profiles**（公式、ICIR、Barra、换手）构建多空策略。

## 两条路径

| 模式 | `mode` | 说明 |
|------|--------|------|
| **方法一** | `auto` | 遍历工具箱所有方法，按你的 Sharpe/回撤/换手约束**自动选最优** |
| **方法二** | `sweep` | 遍历所有方法，**全部输出**对比结果 |
| 指定方法 | `single` + `method:` | 只跑一种（如 `constrained_linear_opt`） |

## E 盘目录

```
_paper_factor_unified/
├── strategy_toolbox/          # 方法目录 + spec 模板
│   ├── method_catalog.json
│   ├── specs/
│   └── latest_run.json
└── strategy_runs/
    └── {name}_{timestamp}/
        ├── selected_factors.json
        ├── method_catalog.json
        └── strategy_result.json
```

## 风格预设 (`style`)

| style | 含义 |
|-------|------|
| `small_cap` | 小市值：底部 30% 市值池 |
| `csi300_enh` | 300 指增：按市值取 top300  proxy |
| `air_index_enh` | 空气指增：全市场 + 低 Beta 因子偏好 |
| `neutral` | 无风格过滤 |

## 工具箱方法（方法二全部打包）

| method_id | 类型 |
|-----------|------|
| `rank_average` | 秩平均 |
| `ic_weighted_linear` | ICIR 加权线性 |
| `constrained_linear_opt` | 约束优化权重（max Sharpe，权重单纯形） |
| `ridge_regression` | Ridge |
| `lasso_regression` | Lasso 稀疏选因子 |
| `gradient_boosting` | GBDT |
| `random_forest` | 随机森林 |
| `lstm` | LSTM（需 torch） |
| `gru` | GRU（需 torch） |

## 用法

```bash
cd ~/paper-factor
source .venv/bin/activate
mountpoint /mnt/remote_e

# 同步工具箱到 E 盘 + 小市值 auto
python -m paper_factor_cli.main strategy \
  --spec strategy_toolbox/specs/small_cap.yaml

# 遍历所有方法（300指增）
python -m paper_factor_cli.main strategy \
  --spec strategy_toolbox/specs/csi300_enh.yaml

# 快速试跑（少因子）
python -m paper_factor_cli.main strategy \
  --spec strategy_toolbox/specs/small_cap.yaml \
  --max-factors 10
```

## 交易成本与涨跌停

### 已实现（v1）

| 项目 | 默认 | 说明 |
|------|------|------|
| **单边综合成本** | `one_way_cost: 0.002`（千二） | 佣金+滑点合并；可设 `0.0025`（千二点五） |
| **成本公式** | `日净收益 = 毛多空 spread − one_way_cost × (多头换手 + 空头换手)` | 多空各算一条腿的换手 |
| **涨停** | 涨跌幅 ≥ 9.5% | **多头池剔除**（当日买不进） |
| **跌停** | 涨跌幅 ≤ -9.5% | **空头池剔除**（开空/借券 proxy） |
| **停牌** | `$paused` 列若存在 | 剔除 |

回测结果同时输出 **毛收益** 与 **净收益**（`gross_sharpe` / `cost_drag_total`）。

### 尚未精细建模（已知简化）

| 情况 | 当前处理 |
|------|----------|
| 涨停**卖不出** / 跌停**买不回**（持仓调不出） | 未逐笔模拟 stuck；仅过滤**新开仓**候选 |
| 科创板/创业板 20% 涨跌停 | 统一 9.5% 阈值，偏保守 |
| ST 5% 涨跌停 | 未单独区分 |
| 融券券源、T+1、最小交易单位 | 未建模 |
| 冲击成本随规模变化 | 固定 bps，不随成交额缩放 |

如需更真实，可后续加：分板块涨跌停阈值、持仓 sticky 矩阵、T+1 可卖数量。

Spec 示例：

```yaml
one_way_cost: 0.0025       # 千二点五
apply_limit_filter: true
limit_up_pct: 0.095
limit_down_pct: -0.095
```

## Spec 字段

```yaml
name: my_strategy
style: small_cap          # small_cap | csi300_enh | air_index_enh | neutral
mode: auto                # auto | sweep | single
method: constrained_linear_opt   # mode=single 时

min_sharpe: 0.3
min_annual_return: 0.05
max_drawdown: 0.35
max_turnover: 0.95
min_icir: 0.02

max_factors: 25
top_frac: 0.2
bottom_frac: 0.2
train_frac: 0.7           # 前 70% 训练，后 30% 样本外评价
data_type: All
```

## 输出解读

`strategy_result.json` 含：

- `selected_factors.json` — 选用的因子及 profile 路径
- `sweep_results` — 每种方法的样本外 Sharpe、回撤、换手、因子权重
- `selection.rationale` — 方法一的选择理由

## 策略 Agent（知识库 + 多轮修正）

类似「研报→因子」的 RD loop，支持 **三种用法**：

| 命令 | 场景 |
|------|------|
| `strategy-agent create` | 用自然语言描述需求 → LLM 生成 spec → 自动优化 |
| `strategy-agent optimize` | 已有 YAML spec → 诊断并多轮 patch |
| `strategy-agent continue` | 看完结果后再给建议 → 继续优化 |
| `strategy-agent status` | 查看 session 与最优指标 |

### 1. 从需求创建并自动优化

```bash
python -m paper_factor_cli.main strategy-agent create \
  --goal "小市值多空，控制换手，net Sharpe 尽量为正" \
  --template strategy_toolbox/specs/small_cap.yaml \
  --max-loops 5
```

### 2. 已有 spec，直接优化

```bash
python -m paper_factor_cli.main strategy-agent optimize \
  --spec strategy_toolbox/specs/small_cap.yaml \
  --goal "换手太高，net Sharpe 为负" \
  --max-loops 5
```

### 3. 看完结果后继续给建议（人机协作）

先打开输出目录里的 `optimization_summary.md`，然后：

```bash
python -m paper_factor_cli.main strategy-agent continue \
  --session /mnt/remote_e/_paper_factor_unified/strategy_runs/small_cap_ls_agent_YYYYMMDD_HHMMSS \
  --feedback "回撤还是偏大，加强平滑，少用动量因子" \
  --max-loops 3
```

可多次 `continue`，每次 feedback 会写入 session 并追加 loop。

### 输出文件

`strategy_runs/{name}_agent_{timestamp}/`：

- `optimization_summary.md` — **给人看的优化报告**
- `session.json` — session 状态（awaiting_feedback = 可 continue）
- `spec_initial.yaml` / `spec_final.yaml` — 初始与最终 spec
- `loop_*/strategy_result.json` — 每轮回测
- `agent_trace.json` — 完整 trace + LLM reasoning

知识库：`strategy_toolbox/knowledge/`（PLAYBOOK、knobs、lessons_learned.jsonl）

Agent 可调原语（spec 驱动）：`signal_smooth_days`、`hold_buffer_frac`、`rebalance_period`、`exclude_factors`、`method` 等。

示例脚本：`bash scripts/strategy_agent_examples.sh`

## 依赖

- 默认：numpy、pandas、scikit-learn
- `constrained_linear_opt`：scipy（`pip install scipy`）
- `lstm` / `gru`：torch（可选，`pip install torch`）
