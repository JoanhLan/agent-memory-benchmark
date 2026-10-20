<div align="right">

[English](README.md) | **简体中文**

</div>

# Agent Memory Benchmark

文本赛道默认按 [Agent Memory Leaderboard](https://agentmemoryleaderboard.ai/zh-cn/docs) 的 Add / Search 契约调用被测服务。本地打分是非官方的：先根据检索记忆生成答案，再按公开评判提示词打分。评判模型目前走 ARK，之后把 `JUDGE_API_KEY`、`JUDGE_API_BASE`、`JUDGE_MODEL` 换成金山云即可。

```bash
python main.py aml-datasets
python main.py aml-add --paper aml-eval/datasets/locomo_refined/papers/daily.json
python main.py aml-search <run_id>
python main.py aml-score <run_id>
```

自建题库在仓库内 `aml-eval/`（六套官方数据 + `smoke` 20 题）。`--paper` 指向 `papers/daily.json` 或 `papers/full.json` 时按卷筛题；未指定时仍可用 `--dataset` 与 `--limit`。

能跑的数据集：`locomo_refined`、`longmemeval_s`、`personamem_v2_32k`、`personamem_v2_128k`、`beam`（公开 100K / 500K / 1M）、`clbench`（评分点全过才算对，单独出分）。ScriptMem 只登记来源。`--streaming` 默认关闭；打开后每写完一段就检索一次，打分用最后一次。2,000 词按空白和标点近似计数（中文一字一词），报告里写明这一点。

## 数据集下载

原始对话与题目从各套公开来源读取（各 `aml-eval/datasets/*/manifest.yaml` 的 `source` 字段亦有记录）：

| 数据集 id | 下载链接 |
|-----------|----------|
| `locomo_refined` | https://github.com/mem-eval-suite/LoCoMo_refined |
| `longmemeval_s` | https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned |
| `personamem_v2_32k` / `personamem_v2_128k` | https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2 |
| `beam` | https://huggingface.co/datasets/Mohammadta/BEAM |
| `clbench` | https://huggingface.co/datasets/tencent/CL-bench |

经典 LoCoMo（下方 TiMEM / MemOS / Mem0 三方对比）从 [snap-research/locomo](https://github.com/snap-research/locomo) 加载（缓存于 `benchmark_data/cache/`）。可选 HuggingFace 回退：[snap-stanford/LoCoMo](https://huggingface.co/datasets/snap-stanford/LoCoMo)，见 `config/default.yaml`。

## AML 文本赛道用法

卷定义与日常/全量切片在 `aml-eval/`（见 [aml-eval/README.md](./aml-eval/README.md)）。评测框架向 `AML_ADD_URL` / `AML_SEARCH_URL` 调用被测平台。本地打分是非官方的。

### 1. 环境准备

```bash
cd agent-memory-benchmark   # 或你的克隆目录
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
copy .env.example .env          # Windows
# cp .env.example .env          # Linux / macOS
```

至少填写（变量名见 `.env.example`）：

| 变量 | 作用 |
|------|------|
| `AML_ADD_URL` / `AML_SEARCH_URL` | 被测 Add / Search 地址（默认 `http://127.0.0.1:8001/add` 与 `.../search`） |
| `AML_API_KEY` / `AML_AUTH` | 上述接口鉴权（`AML_AUTH` 默认 `x-api-key`） |
| `ARK_API_KEY` / `ARK_API_BASE` / `JUDGE_MODEL` | 生成答案与评判（OpenAI 兼容；评判后续可改 `JUDGE_API_*`） |

可选：`AML_HEALTH_URL`、`ANSWER_API_KEY` / `ANSWER_API_BASE`、`JUDGE_API_KEY` / `JUDGE_API_BASE`。

### 2. 下载 / 缓存数据

没有单独的下载命令。首次对某数据集执行 `aml-add` / `aml` 时会拉到 `benchmark_data/cache/`（LoCoMo-Refined、LongMemEval-S、PersonaMem、CLBench 用 httpx；BEAM 用 HuggingFace `datasets`）。再次运行走缓存。BEAM 依赖 `requirements.txt` 里的 `datasets`。

### 3. 列出数据集

```bash
python main.py aml-datasets
```

可跑的六个 id：`locomo_refined`、`longmemeval_s`、`personamem_v2_32k`、`personamem_v2_128k`、`beam`、`clbench`。`scriptmem` 仅登记来源。

### 4. Smoke / 快速自检

- 仓库内固定小卷：`aml-eval/smoke/sets/small.json`（20 题，`dataset_id: small`）。**当前未接入** `main.py`（没有 `small` 的 loader，也不能作 `--dataset`），请勿把它当作 `--paper` 去跑 Add/Search。
- 可用的快速跑法：

```bash
# 官方日常卷（推荐第一次联调）
python main.py aml --paper aml-eval/datasets/locomo_refined/papers/daily.json --run-id smoke-locomo-daily

# 或不带 paper、只跑 1 个 sample（有 --paper 时 --limit 无效）
python main.py aml --dataset locomo_refined --limit 1 --run-id smoke-limit1
```

### 5. 跑 AML（Add → Search → Score）

分步（共用同一 `run_id`）：

```bash
python main.py aml-add --paper aml-eval/datasets/locomo_refined/papers/daily.json --run-id my-run
python main.py aml-search my-run
python main.py aml-score my-run
```

一键（Add + Search + 非官方打分）：

```bash
python main.py aml --paper aml-eval/datasets/locomo_refined/papers/daily.json --run-id my-run
# 全量卷：
python main.py aml --paper aml-eval/datasets/locomo_refined/papers/full.json --run-id my-full
```

报告在 `reports/{run_id}/`（如 `aml_add.json` 及 search/score 输出）。

### 6. 常用参数

| 参数 | 命令 | 含义 |
|------|------|------|
| `--paper PATH` | `aml` / `aml-add` | `aml-eval/.../papers/` 下的卷 JSON（`daily.json` / `full.json`）。决定 `dataset_id` 与筛题；此时 `--limit` 无效 |
| `--dataset ID` | `aml` / `aml-add` | 六个可跑 id 之一（无 `--paper` 时必填） |
| `--run-id ID` | `aml` / `aml-add` | `reports/` 下的 run 目录名 |
| `--limit N` | `aml` / `aml-add` | 未指定 `--paper` 时的最大 sample 数 |
| `--streaming` | `aml` / `aml-add` | 每写完一段就检索；打分用最后一次检索 |
| `--skip-score` | `aml` | 检索后跳过非官方评判 |
| `--score` | `aml-search` | 每题检索返回后立刻打分（不跑 Add） |
| `--output-dir DIR` | `aml-search` | 搜索/打分写到指定目录，不复用 Add 的 checkpoint |
| `--only-from PATH` | `aml-search` | 只对某次已有 `aml_score` JSON 里出现过的题 id 打分 |

`--paper` 与 `--dataset` 二选一；同时给时 `--dataset` 必须与卷内 `dataset_id` 一致。PersonaMem 一次只开 `32k` 或 `128k` 其中一轨。CLBench 按 rubrics 单独出分，不与其他套准确率加总。

下面仍是原来的 TiMEM / MemOS / Mem0 三方对比，命令还在，不是这次比赛的默认入口。

# TiMEM vs MemOS vs Mem0 基准测试

![CI](https://github.com/JoanhLan/agent-memory-benchmark/actions/workflows/ci.yml/badge.svg)

独立基准测试项目，对比 TiMEM、MemOS Cloud 与 Mem0 Platform 的**记忆写入（ingest）**与**检索（retrieval）**能力。

完整规则见 [BENCHMARK_PROTOCOL.md](./BENCHMARK_PROTOCOL.md)（英文）。

## 环境要求

- **Python 3.10+**
- **Node.js 18+** — 仅 dashboard 开发模式（`npm run dev`）需要；生产模式由 `python main.py dashboard` 自动构建 UI

## 安装

```bash
cd timem-memos-mem0-benchmark   # 或你的克隆目录
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
copy .env.example .env          # Windows — 填入 API Key
# cp .env.example .env          # Linux / macOS
```

**开发 / 测试：**

```bash
pip install -r requirements-dev.txt
pytest tests/unit -q
```

必需环境变量：

| 变量 | 说明 |
|------|------|
| `TIMEM_BASE_URL` | 默认 `https://api.timem.cloud`（本地 TiMEM 可改为 `http://localhost:8001`） |
| `TIMEM_API_KEY` | TiMEM API Key — 在 [api.timem.cloud](https://api.timem.cloud) 注册获取 |
| `TIMEM_ACCOUNT_ID` | Backfill 所需 |
| `MEMOS_API_KEY` | MemOS Cloud Token |
| `MEM0_API_KEY` | Mem0 Platform API Key |
| `MEM0_BASE_URL` | 默认 `https://api.mem0.ai` |
| `ARK_API_KEY` | 火山引擎 ARK API Key |
| `ARK_API_BASE` | 默认 `https://ark.cn-beijing.volces.com/api/v3` |
| `JUDGE_MODEL` | ARK 端点 ID（如 `ep-xxx` 或模型 ID） |

## 快速开始（Fixture — 无需 HuggingFace）

```bash
# 使用内置样例 persona 试跑（三系统）
python main.py --fixture ingest
# 记下输出的 run_id

python main.py --fixture retrieve <run_id> --mode T0
python main.py --fixture retrieve <run_id> --mode T1

# 只跑部分系统
python main.py --fixture ingest --systems timem,mem0
```

## 完整基准（LoCoMo，10 个 persona）

LoCoMo 数据从 [snap-research/locomo](https://github.com/snap-research/locomo) 加载（缓存于 `benchmark_data/cache/`）。HuggingFace 为可选 fallback，见 `config/default.yaml`。

```bash
python main.py ingest --personas 10
python main.py retrieve <run_id> --mode T0
python main.py retrieve <run_id> --mode T1

# 或一键全流程
python main.py full --personas 10
python main.py full --preset paper --personas 10
python main.py timem-sweep --fixture --mode T1
```

报告输出至 `reports/{run_id}/`。

## Dashboard（Benchmark Lab）

基于 Vue 3 的实验控制台（类似 [api.timem.cloud](https://api.timem.cloud) 上的 TiMEM 控制台）：

- 页面发起任务：**Full**（ingest → T0 → T1，含 TiMEM backfill），或分步 **Ingest / T0 / T1**
- 默认数据集：**fixture**；可选 **LoCoMo 10 persona**
- 后台任务 — 可离开页面稍后轮询状态
- **写入** 三系统 session 明细（TiMEM | MemOS | Mem0）
- **对比** 按题目并排查看检索结果
- **调试** 单题多系统检索（不写正式报告）

**生产模式（单端口）：**

```powershell
cd dashboard
npm install
npm run build
cd ..
python main.py dashboard
```

访问 `http://127.0.0.1:8765/`。

**开发模式（热更新）：**

```powershell
# 终端 1
python main.py dashboard --api-only --no-browser

# 终端 2
cd dashboard
npm run dev
```

访问 `http://127.0.0.1:5173/`。

**一键启动（自动构建 UI）：**

```powershell
cd <repo-root>
python main.py dashboard
```

或：`.\scripts\start_dashboard.ps1`

强制重建 UI：`python main.py dashboard --rebuild`

### 界面工作流

1. **新建 Run** → 可填自定义 Run ID（留空则自动生成），数据集选 Fixture 或 LoCoMo 10
2. **一键 Full** 或分步 Ingest / T0 / T1
3. **写入** → 三系统 session 明细
4. **检索** → 指标 + 点题目看召回
5. **对比** → Overview / Ingest / Retrieval
6. **调试** → 单题多系统检索（不写正式报告）

## 项目结构

```
adapters/     TiMEM、MemOS、Mem0 REST 客户端
benchmark_data/     LoCoMo 加载器 + fixtures
runners/      ingest、retrieval、token_compare
evaluators/   延迟、recall@K、tokens、分类指标、ARK judge
utils/        消息对切分（ingest 粒度）
config/       default.yaml
reports/      每次 run 的 JSON 报告
dashboard/    Vue 对比 UI
```

## 免责声明

- 本项目为**独立**基准测试框架，与 TiMEM、MemOS（MemTensor）、Mem0 官方无从属或背书关系。
- TiMEM、MemOS、Mem0、LoCoMo 等名称归各自所有者所有。
- 完整 benchmark 需自备各平台 API 凭证及火山引擎 ARK Judge 端点；请遵守各厂商服务条款与用量限制。

## 说明

- **写入并发**：Session 并行（TiMEM/MemOS/Mem0 默认 `session_concurrency: 10`），session 内 pair 串行。**TiMEM**：同一 `user_id` 同时只跑一个 session（跨 persona 并行）；ingest 结束含 L2 backfill/wait。API 侧 `session_id` 为 `{run_id}_{persona_id}_session_{n}`。ingest 后检查 `ingest.json` → `timem_l2_finalize.l2_ready_count == persona_count`。详见 [BENCHMARK_PROTOCOL.md](./BENCHMARK_PROTOCOL.md#ingest-concurrency-benchmark-harness)。
- **Mem0 轮询**：默认 `deferred` — 先 POST pair，按 session flush event；T0 前 flush 残留。
- **写入延迟**：Dashboard/API p50 为**单次 add**（`add_latency`）；`session_latency` 保留整 session 视图。旧 run：`python scripts/migrate_ingest_add_latency.py --run-id <id>`。
- **写入粒度**：TiMEM/Mem0 按相邻 2 条消息一对写入；MemOS 整 session 一次 POST。见 [BENCHMARK_PROTOCOL.md](./BENCHMARK_PROTOCOL.md#ingest-granularity-per-system)。
- **新 run**：pair 切分规则变更后须新 `run_id` 重新 ingest，勿与旧 whole-session 结果对比。
- **LoCoMo 写入量**：约 272 sessions × ~10 pairs ≈ 每系统 2700+ POST（TiMEM/Mem0）。
- **检索并发**：Search→Judge 流水线（`pipeline_mode: true`）。TiMEM 检索默认 **3**（`timem_query_concurrency`）；memos/mem0 **10**；judge **10**；TiMEM backfill **3**。
- **CLI 调参**：`python main.py retrieve <run_id> --query-concurrency 12 --judge-concurrency 6 --backfill-concurrency 3 --no-pipeline`
- **Token 对比**：`reports/{run_id}/token_compare_T0.json`
- **T0**：ingest 后直接检索（T0 前 flush Mem0 events）
- **T1**：TiMEM 手动 backfill 后检索；MemOS/Mem0 不变
- 用户隔离：`timem_{run_id}_{persona}` / `memos_{run_id}_{persona}` / `mem0_{run_id}_{persona}`
- Mem0 默认 deferred 事件轮询（`MEM0_INGEST_POLL_TIMEOUT_SEC`，默认 120s）

## 许可证

MIT — 见 [LICENSE](./LICENSE)。
