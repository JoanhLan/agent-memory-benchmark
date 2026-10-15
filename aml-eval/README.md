# AML 评测题库

自建评测卷。每次只指定一套来跑。ScriptMem 不在本库（公开包没有真实对话）。

原始对话与题目仍从各套公开来源读取。本目录保存的是**卷**：跑哪一套、日常抽哪些题、发版认哪一版全量。

## 三档

| 场合 | 跑什么 | 怎么选 |
|------|--------|--------|
| 评测开始前 | `smoke/sets/small.json`（20 题） | 固定 |
| 日常 | 某个数据集夹里的 `papers/daily.json` | 指定一个夹 |
| 发版 | 某个数据集夹里的 `papers/full.json` | 指定一个夹 |

六套都在库里，供点名。一次日常或一次发版不要求六套串完。

PersonaMem 一次只开 `personamem_v2_32k` 或 `personamem_v2_128k` 其中一夹。

## 各卷

| 夹 | 日常卷 | 发版全量 |
|----|--------|----------|
| `locomo_refined` | `conv-26`，87 道文本题 | 10 段对话，861 道文本题 |
| `longmemeval_s` | 文件顺序前 50 题（题号已冻结） | 500 题 |
| `personamem_v2_32k` | persona 521 + 737，56 题 | 该轨 5000 题 |
| `personamem_v2_128k` | 同上两个人设、56 题，用 128k 对话 | 该轨 5000 题 |
| `beam` | 公开 **100K** 档（20 段） | 公开 **500K** 档（35 段） |
| `clbench` | 公开 `CL-bench.jsonl` 前 50 条 `task_id`（已写入 daily 卷） | 公开集约 1899 条 |

BEAM 另有 `papers/optional_1m.json`（1M，35 段）。只有点名才跑。论文中的 10M 未公开，不入库。

CLBench 按 rubrics 单独出分，不与前面几套的对错准确率加总。

## 目录

```text
aml-eval/
├── smoke/sets/small.json
└── datasets/
    ├── locomo_refined/
    ├── longmemeval_s/
    ├── personamem_v2_32k/
    ├── personamem_v2_128k/
    ├── beam/
    └── clbench/
```

每夹含 `manifest.yaml`（来源）和 `papers/`（日常卷、全量卷）。

## 跑卷（agent-memory-benchmark）

```bash
cd agent-memory-benchmark
python main.py aml-add --paper aml-eval/datasets/locomo_refined/papers/daily.json --run-id my-run
python main.py aml-search my-run
python main.py aml-score my-run
```

`--paper` 与 `--dataset` 二选一；有 `--paper` 时以卷内 `dataset_id` 为准，`--limit` 无效。
