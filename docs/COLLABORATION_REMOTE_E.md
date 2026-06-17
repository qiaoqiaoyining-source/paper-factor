# paper-factor 远程 E 盘协作说明

本文档说明团队如何在 **不占用本机 C 盘** 的前提下，用同事电脑上的 **E 盘** 共享行情、基本面因子和文献因子，并在本机 WSL 里做 IC/Barra 评价与策略研究。

> 维护：数据与脚本变更时请同步更新本文档。  
> 相关脚本：`scripts/setup_unified_remote.sh`、`scripts/unify_remote_factors.py`、`scripts/build_factor_profiles.py`

---

## 1. 分工（谁做什么）

| 角色 | 主要负责 | 数据落点 | 是否跑 paper-factor |
|------|----------|----------|---------------------|
| **因子生成同事** | 从论文/代码生成文献因子 | `E:\paper_factors\` | 是（导出 parquet + meta/json + 可选 code.py） |
| **基本面数据** | 维护宽表 Excel/CSV | `E:\基本面因子\{类别}\` | 否（只提供源文件） |
| **评价/策略同事（你）** | IC/ICIR、换手、Barra、profile、回测 | WSL + E 盘 `_paper_factor_unified` | 是（analyze / profile） |
| **Barra 模型** | 风格暴露 | 各自本机 `git_ignore_folder/barra_model/` | 本地 CSV，不上传 E 盘 |

原则：**原始数据只保留一份**；统一目录里文献因子 **不复制 parquet**，只写索引；基本面 **转成 parquet 一份** 供评价用。

---

## 2. E 盘目录一览

### 2.1 原始区（大家共同维护，勿随意改结构）

```
E:\
├── market_daily_daily_new\      # 日频行情（转 daily_pv.h5 的源）
├── market_minute_daily_new\     # 分钟行情（可选，默认跳过）
├── dailyData.parquet
├── 基本面因子\                   # 宽表因子源（Excel/CSV）
│   ├── 盈利\盈利因子1.xlsx ...
│   ├── 价值\...
│   └── 因子汇总.xlsx            # 因子名称/说明字典（profile 用）
├── paper_factors\               # 文献因子产出（同事生成）
│   ├── 文献因子\*.parquet
│   ├── 文献因子\*.meta.json / *.json
│   └── 旧因子\*.parquet
└── 数据说明.txt
```

### 2.2 统一区（评价流水线自动生成）

由 `bash scripts/setup_unified_remote.sh` 写入 **`E:\_paper_factor_unified\`**（WSL 路径：`/mnt/remote_e/_paper_factor_unified`）：

```
_paper_factor_unified\
├── factor_implementation_source_data\
│   ├── daily_pv.h5              # 全样本行情（IC 标签，约 800MB）
│   ├── 因子汇总.xlsx            # 仅从 E 盘复制字典，不复制整棵 基本面因子
│   ├── 数据说明.txt
│   └── remote_data_meta.json
├── factor_implementation_source_data_debug\
│   └── daily_pv.h5              # 小样本，调试用
├── factor_outputs\
│   ├── fundamental\{类别}\{因子名}.parquet + .meta.json
│   └── literature\{分组}\{因子名}.meta.json   # latest_path 指向 paper_factors 原 parquet
├── factor_profiles\             # profile 命令生成
│   ├── profiles_index.json
│   └── {source_type}\{因子名}.profile.json
└── catalog.json                 # 最近一次 unify 的摘要
```

**不应出现**：`factor_implementation_source_data\基本面因子\` 整目录拷贝（旧版 bug，已修复）。

### 2.3 本机 WSL 项目（符号链接，不占 C 盘大文件）

`link` 步骤后：

```
~/paper-factor/git_ignore_folder/
├── factor_implementation_source_data  → E/_paper_factor_unified/.../source_data
├── factor_implementation_source_data_debug
├── factor_outputs/unified_remote        → E/.../factor_outputs
├── factor_outputs/paper_factors_raw     → E/paper_factors
├── factor_profiles                      → E/.../factor_profiles
└── barra_model/                         # 本地 Barra CSV（各自维护）
```

---

## 3. 网络挂载（评价机必做）

在 **需要跑评价的 WSL** 上，把同事电脑的 E 盘挂到 `/mnt/remote_e`：

```bash
sudo apt install -y sshfs fuse3
sudo mkdir -p /mnt/remote_e
fusermount -u /mnt/remote_e 2>/dev/null || true

# 默认同事机 IP（按实际修改）
sshfs pc@192.168.1.13:/E: /mnt/remote_e \
  -o reconnect,ServerAliveInterval=15,ServerAliveCountMax=3

mountpoint /mnt/remote_e
ls /mnt/remote_e
```

- 主机：`192.168.1.13`（原 `192.168.1.254` 若 22 端口不通则换 IP）
- 用户：`pc`，密码为同事 Windows 登录密码
- 断线后重跑 `sshfs` 即可；**不要**把整盘 E 复制到 C 盘或 `Downloads`

---

## 4. 一键整理（评价同事执行）

```bash
cd ~/paper-factor
source .venv/bin/activate
dos2unix scripts/*.sh   # Windows 检出后首次需要

export PAPER_FACTOR_REMOTE_ROOT=/mnt/remote_e
export PAPER_FACTOR_UNIFIED_ROOT=/mnt/remote_e/_paper_factor_unified
export SKIP_MINUTE=1
```

### 4.1 试跑（推荐第一次）

只转 3 个基本面文件 + 索引全部文献因子 + 建链接（**注意**：`--fundamental-limit 3` 按**文件名排序**取前 3 个，可能是 `价值因子1、价值因子10…`，不是「每个类别 3 个」）。

```bash
bash scripts/setup_unified_remote.sh --fundamental-limit 3
```

预计耗时：**market 约 5–20 分钟**（sshfs 写 `daily_pv.h5` 较慢），fundamental 视 Excel 大小，literature 较快（只写 meta）。

### 4.2 全量基本面 + 全量评价（后台一条龙）

```bash
cd ~/paper-factor
source .venv/bin/activate
# 确保 E 盘已挂载且不断线
bash scripts/run_full_pipeline.sh          # 前台（可 nohup 后台）
# 或查看进度：
bash scripts/monitor_full_pipeline.sh
tail -f log/full_pipeline.log
```

`run_full_pipeline.sh` 顺序：**全量 fundamental 转 parquet → literature 索引 → link → 全量 profile（含 IC/Barra）**。  
基本面源文件约 **115** 个 Excel/CSV，sshfs 下可能 **数小时**；日志：`log/full_pipeline.log`。

### 4.3 全量基本面（仅 unify，不含 profile）

```bash
bash scripts/setup_unified_remote.sh
```

会遍历 `E:\基本面因子\` 下所有 `.csv/.xlsx/.xls`，磁盘占用明显增加，建议在同事 E 盘空间充足时跑。

### 4.4 分步执行（便于排错）

```bash
python scripts/unify_remote_factors.py market --skip-minute
python scripts/unify_remote_factors.py fundamental --limit 3
python scripts/unify_remote_factors.py literature
python scripts/unify_remote_factors.py link --force
```

### 4.5 检查是否成功

```bash
ls -lh /mnt/remote_e/_paper_factor_unified/factor_implementation_source_data/daily_pv.h5
test ! -d /mnt/remote_e/_paper_factor_unified/factor_implementation_source_data/基本面因子 \
  && echo "OK: 无重复基本面目录"
find /mnt/remote_e/_paper_factor_unified/factor_outputs -name '*.meta.json' | wc -l
ls -la ~/paper-factor/git_ignore_folder/factor_implementation_source_data
```

---

## 5. 因子生成同事：交付规范

### 5.1 文献因子（`E:\paper_factors\`）

每个因子建议具备：

| 文件 | 说明 |
|------|------|
| `{因子名}.parquet` | MultiIndex：`(datetime, instrument)`，单列因子值 |
| `{因子名}.meta.json` 或 `.json` | `factor_name`、`source_report_title`、公式/描述等 |
| `{因子名}.code.py` | 可选；仅当没有 parquet 时才需要 `--execute-code` 重跑 |

**不要**要求评价同事重新跑生成；评价侧默认 **只索引已有 parquet**。

目录示例：

```
paper_factors/文献因子/某报告标题/alpha001.parquet
paper_factors/文献因子/某报告标题/alpha001.meta.json
```

### 5.2 基本面（`E:\基本面因子\`）

- 宽表：第一列为 `trade_date`（或 `date`/`datetime`），其余列为股票代码
- 文件名即因子名（如 `盈利因子1.xlsx`）
- 更新 `因子汇总.xlsx` 中的说明，便于 profile 自动带文档

---

## 6. 评价同事：IC / Barra / 档案

### 6.1 批量评价 + 生成 profile

```bash
cd ~/paper-factor
source .venv/bin/activate
export PAPER_FACTOR_OUTPUTS_DIR=~/paper-factor/git_ignore_folder/factor_outputs

# 先试 5 个
python -m paper_factor_cli.main profile --limit 5

# 全量（缺分析的会先算 IC/Barra）
python -m paper_factor_cli.main profile
```

输出：`E:\_paper_factor_unified\factor_profiles\`，索引见 `profiles_index.json`。

### 6.2 仅跑指标（不建 profile）

```bash
python -m paper_factor_cli.main analyze --metrics-only --data-type All
```

分析 JSON 默认在：`git_ignore_folder/factor_outputs/factor_analysis/`（体积小，可留本机）。

### 6.3 自己本地试算的小因子

可放在：`git_ignore_folder/factor_outputs/my_local/`，同样格式 parquet + meta.json，再跑 `profile`。

---

## 7. 数据流简图

```
同事 E 盘原始数据
  market_daily_*  ──market──►  daily_pv.h5
  基本面因子/*    ──fundamental──►  factor_outputs/fundamental/*.parquet
  paper_factors/* ──literature──►  factor_outputs/literature/*.meta.json (指向原 parquet)
                                        │
                                        ▼
                              profile / analyze (本机 Barra)
                                        │
                                        ▼
                              factor_profiles/*.profile.json
```

---

## 8. 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| `$'\r': command not found` | Windows 换行 | `dos2unix scripts/*.sh` |
| `copytree` / `Operation not permitted` 基本面 | 旧脚本整目录复制 | 拉最新代码，删 `.../source_data/基本面因子` 后重跑 market |
| `Loading daily` 很久 | sshfs 写大 h5 | 正常，看 `daily_pv.h5` 大小是否增长 |
| WSL 找不到 parquet | 未挂载或路径错 | `mountpoint /mnt/remote_e`；`ls /mnt/remote_e/paper_factors` |
| `--fundamental-limit 3` 不是 3 个类别 | limit 对**全局排序文件列表** | 全量跑或改脚本按类别 limit |
| C 盘满 | 误复制 E 到本机 | 删本地副本，只用 sshfs + symlink |
| 文献因子重复占盘 | 旧版 literature 复制 parquet | 用当前 `literature`（只写 meta） |
| Barra `No overlapping` | 因子 `instrument` 为整型代码 `1`（应为 `000001`） | 已自动映射为 `000001.XSHE`；重跑 `profile --force` |

---

## 9. 环境变量速查

| 变量 | 默认值 | 含义 |
|------|--------|------|
| `PAPER_FACTOR_REMOTE_ROOT` | `/mnt/remote_e` | E 盘挂载点 |
| `PAPER_FACTOR_UNIFIED_ROOT` | `{REMOTE}/_paper_factor_unified` | 统一输出根目录 |
| `PAPER_FACTOR_OUTPUTS_DIR` | `git_ignore_folder/factor_outputs` | 分析 JSON 输出 |
| `SKIP_MINUTE` | `1`（setup 脚本） | 跳过分钟行情转换 |

---

## 10. 跑完 setup 后的检查清单

- [ ] `daily_pv.h5` 存在且约 800MB 级
- [ ] **无** `factor_implementation_source_data/基本面因子/` 目录
- [ ] `factor_outputs/fundamental/` 或 `literature/` 下有 `.meta.json`
- [ ] `git_ignore_folder/factor_implementation_source_data` 为指向 E 的 symlink
- [ ] `python -m paper_factor_cli.main profile --limit 5` 能生成 profile
- [ ] `catalog.json` 中 `fundamental` / `literature` 非空（跑完全部步骤后）

---

## 11. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-05-27 | 初版：远程 E 统一目录、分工、挂载、setup/profile 流程；market 不再 copytree 基本面 |
| 2026-05-28 | 策略工具箱：auto/sweep、线性优化、ML/DL，见 [STRATEGY.md](STRATEGY.md) |
| 2026-05-31 | 管理层汇报摘要：[WORK_SUMMARY_FOR_MANAGEMENT.md](WORK_SUMMARY_FOR_MANAGEMENT.md) |
