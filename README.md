# factor_strategy_agent

从金融研报提取因子、构建策略 toolbox，并在 E 盘维护**实证知识库**（因子类型 × 策略方法 × 风格）。

## E 盘目录（toolbox + 知识库）

```
/mnt/remote_e/_paper_factor_unified/
├── factor_profiles/           # 因子档案
├── strategy_toolbox/          # 策略 toolbox（方法目录、spec 模板、Agent PLAYBOOK）
│   ├── method_catalog.json
│   ├── specs/
│   └── knowledge/             # Agent 调参知识（PLAYBOOK、knobs、lessons）
├── strategy_knowledge/        # 实证知识库（grid 实验、matrix 汇总、论文策略）
│   ├── records/
│   ├── matrix_summary.json
│   ├── taxonomy.yaml
│   └── paper_strategies/
└── strategy_runs/             # 每次策略运行结果
```

环境变量（任选其一，推荐新名称）：

- `FACTOR_STRATEGY_AGENT_UNIFIED_ROOT` 或 `PAPER_FACTOR_UNIFIED_ROOT`

## Quick Start

```bash
bash scripts/setup.sh
# 编辑 .env：Claude API（见 .env.example）
start --report-file papers/inbox/paper.pdf
```

## CLI

| 命令 | 说明 |
|------|------|
| `fsa paths` | 查看 E 盘 toolbox / 知识库路径 |
| `start` / `fsa run` | 研报 → 因子 pipeline |
| `fsa strategy-ingest --report-file ...` | 从研报提取策略方法 |
| `fsa strategy-knowledge build-grid` | 跑 factor×method×style 网格实验 |
| `fsa strategy-knowledge query --slice fundamental:value` | 查询实证 KB |
| `fsa strategy --spec ...` | 跑策略回测 |
| `fsa strategy-agent create --goal "..."` | LLM 策略 Agent（结束打印 token 用量） |

每次 **Agent / LLM 流水线** 结束会打印 token 统计，便于核算成本。

## LLM（Claude）

`.env` 示例：

```
CHAT_MODEL=anthropic/claude-sonnet-4-5-20250929
ANTHROPIC_API_KEY=your-key
ANTHROPIC_API_BASE=https://api.modelverse.cn
```

## Requirements

- Python 3.10+
- Docker（因子执行）
- E 盘 sshfs 挂载（团队远程数据）
