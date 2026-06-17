# Strategy knowledge base (Agent 调参)

- `PLAYBOOK.md` — diagnosis → intervention patterns for the LLM agent
- `knobs.json` — allowed StrategySpec fields the agent may patch
- `lessons_learned.jsonl` — append-only log from past agent loops

**位置**：优先在 E 盘 `strategy_toolbox/knowledge/`（与 toolbox 一起 sync）。

**实证知识库**（factor×method×style 网格实验）在 sibling 目录：

```
../strategy_knowledge/
├── records/
├── matrix_summary.json
└── paper_strategies/
```

Run:

```bash
python -m factor_strategy_agent_cli.main strategy-agent create --goal "..." --template strategy_toolbox/specs/small_cap.yaml
python -m factor_strategy_agent_cli.main strategy-knowledge build-grid --dry-run
python -m factor_strategy_agent_cli.main strategy-ingest --report-file papers/inbox/foo.pdf --run
```
