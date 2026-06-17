# paper-factor 因子库与策略研究 — 工作汇报

> 汇报对象：管理层  
> 项目：paper-factor 远程因子统一、评价与策略框架  
> 数据环境：同事 PC E 盘（sshfs 挂载，WSL 计算，本机 C 盘几乎不占大文件）  
> 状态：**因子库与全量评价已完成**；**策略工具箱已就绪**，可按风格约束跑策略

---

## 一、工作目标（我们解决了什么）

| 痛点 | 解决方案 |
|------|----------|
| C 盘满、数据拷不动 | E 盘 sshfs 挂载 + 符号链接，计算在 WSL，大文件全在 E 盘 |
| 文献因子 / 基本面 / 行情格式不统一 | 统一目录 `_paper_factor_unified`，标准 parquet + profile |
| 因子多、缺少 IC/Barra/说明 | 246 份因子档案（公式、ICIR、换手、Barra 风格暴露） |
| 同事各干各的、路径混乱 | 协作文档 + 固定目录分工（生成 vs 评价 vs 策略） |
| 做策略缺工具 | 策略工具箱：多方法组合 + 约束优化 + 自动/遍历两种模式 |

---

## 二、数据与目录（E 盘一张图）

```
E:\
├── 基本面因子\              ← 原始 Excel/CSV（约 115 个，唯一源）
├── paper_factors\           ← 同事文献因子 parquet（唯一源，不复制）
├── market_daily_daily_new\  ← 日频行情源
│
└── _paper_factor_unified\   ← 统一产出（本次建设重点）
    ├── factor_implementation_source_data\daily_pv.h5   # IC 用行情
    ├── factor_outputs\fundamental\*.parquet             # 基本面标准化
    ├── factor_outputs\literature\*.meta.json            # 文献索引（指向原 parquet）
    ├── factor_profiles\*.profile.json                   # 246 份因子档案
    ├── strategy_toolbox\                                # 策略方法包 + spec 模板
    └── strategy_runs\                                   # 每次策略运行结果
```

**原则**：原始数据只保留一份；文献因子不重复拷贝；评价与策略都读统一 profile。

---

## 三、已完成交付物

### 3.1 数据流水线（一键可复跑）

| 步骤 | 内容 | 结果 |
|------|------|------|
| market | 日频 → `daily_pv.h5` | ~800MB，472+ 交易日 |
| fundamental | 115 源文件 → parquet | **114** 个成功（字典 xlsx 非因子已跳过） |
| literature | 扫描 `paper_factors` | **78** 个文献因子索引 |
| profile | IC + Barra + 文档 | **246** 份 profile + 总索引 |

脚本：`scripts/setup_unified_remote.sh`、`scripts/run_full_pipeline.sh`

### 3.2 因子档案（每个因子一份 JSON）

每份 profile 包含：

- **文档**：论文/基本面说明、公式、变量  
- **评价**：IC、ICIR、RankIC、多空 Sharpe、回撤、换手  
- **Barra**：风格暴露、主导风格因子（已修复代码映射问题）  
- **数据指针**：因子 parquet 在 E 盘的路径  

位置：`E:\_paper_factor_unified\factor_profiles\`

### 3.3 策略研究框架（新建）

**两条使用路径**（对应业务需求）：

| 路径 | 模式 | 适用场景 |
|------|------|----------|
| **方法一** | `auto` | 给风格 + Sharpe/回撤/换手约束，**系统自动选最优组合方法** |
| **方法二** | `sweep` | **遍历全部方法**，输出对比表，供研究/汇报 |

**工具箱方法（已打包）**：

- 线性：IC 加权、秩平均、**约束优化权重**（max Sharpe + 权重约束）  
- 机器学习：Ridge、Lasso、GBDT、随机森林  
- 深度学习：LSTM、GRU（需安装 torch）  

**风格预设**：小市值、300 指增、空气指增（低 Beta）

**交易摩擦（v1）**：

- 默认 **千二** 单边综合成本（佣金+滑点），可改 **千二点五**  
- 涨跌停 / 停牌：**简化过滤**（新开仓候选剔除）  
- 输出毛收益 vs 净收益，便于看成本影响  

文档：`docs/STRATEGY.md`  
示例 spec：`strategy_toolbox/specs/small_cap.yaml` 等  

### 3.4 协作与运维文档

| 文档 | 用途 |
|------|------|
| `docs/COLLABORATION_REMOTE_E.md` | 同事分工、挂载、目录、常见问题 |
| `docs/STRATEGY.md` | 策略 spec、方法说明、成本与涨跌停 |
| 本文 | 给管理层的一页纸总结 |

---

## 四、团队分工（建议固定）

| 角色 | 职责 | 数据位置 |
|------|------|----------|
| **因子生成同事** | 论文/代码 → parquet + meta | `E:\paper_factors\` |
| **基本面维护** | Excel/CSV + 因子汇总 | `E:\基本面因子\` |
| **研究/策略（本组）** | 统一、评价、profile、策略回测 | WSL + `_paper_factor_unified` |
| **Barra** | 各机本地 CSV | `git_ignore_folder/barra_model/` |

---

## 五、关键数字（当前状态）

| 指标 | 数量 |
|------|------|
| 基本面因子（parquet） | 114 |
| 文献因子（索引） | 78 |
| 因子 profile（IC+Barra+文档） | **246** |
| 旧因子格式不符（已跳过） | ~50（`旧因子/`，待迁移格式后可纳入） |
| 策略方法数 | 9 种 |
| 试跑策略（小市值 8 因子） | 样本外 Sharpe ~1.2（毛）；扣千二后需以新回测为准 |

---

## 六、技术亮点（可对外简述）

1. **零 C 盘拷贝**：E 盘 sshfs + symlink，本机只跑代码和小 JSON。  
2. **因子即资产**：profile 把公式、ICIR、Barra、路径串成可检索档案。  
3. **策略可配置**：YAML 写风格与约束，自动选方法或全量对比。  
4. **可复现**：每次策略运行落盘 `strategy_runs/{name}_{时间}/strategy_result.json`。  

---

## 七、已知限制与后续建议

| 项 | 说明 | 建议 |
|----|------|------|
| 旧因子目录 | MultiIndex 格式不对，未进 profile | 同事批量转格式或写迁移脚本 |
| 300 成分股 | 当前用市值 Top300 proxy | 若有官方成分表，可替换 universe |
| 涨跌停 | 仅过滤新开仓，未模拟「涨停卖不出」 | 策略实盘前加 T+1 + sticky 持仓 |
| 全市场策略 | 246 因子全量 sweep 耗时长 | 按 spec 限制 `max_factors` 或分批 |
| LSTM/GRU | 需额外装 torch | 按需安装后再纳入 sweep |

**建议下一步（业务向）**：

1. 按老板关注的风格（小市值 / 300 指增 / 空气指增）各跑一版 **扣费后** 全量策略，出对比表。  
2. 从 profile 按 ICIR + Barra 筛 **因子池**，固定池子做季度调仓研究。  
3. 与因子生成同事对齐 **交付规范**（parquet 格式、meta 字段），减少「旧因子」类问题。

---

## 八、日常使用命令（给同事参考）

```bash
# 1. 挂载 E 盘（WSL，一次会话）
sshfs pc@192.168.1.13:/E: /mnt/remote_e -o reconnect,ServerAliveInterval=15

# 2. 查看因子库状态
bash scripts/monitor_full_pipeline.sh

# 3. 按需求跑策略（小市值 + 自动选方法 + 千二成本）
cd ~/paper-factor && source .venv/bin/activate
python -m paper_factor_cli.main strategy \
  --spec strategy_toolbox/specs/small_cap.yaml
```

---

## 九、结论（给老板一句话）

**已在 E 盘建成统一因子库（246 份可检索档案），并完成 IC/Barra 全量评价；策略侧已具备「按风格与风险约束自动选方法 / 遍历对比」的工具箱，且默认计入千二交易成本与涨跌停简化约束，可直接进入因子筛选与策略验证阶段。**

---

*附件路径（Windows）：`E:\_paper_factor_unified\`*  
*文档路径（仓库）：`docs/COLLABORATION_REMOTE_E.md`、`docs/STRATEGY.md`*
