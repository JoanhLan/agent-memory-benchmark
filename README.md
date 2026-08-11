<div align="right">

**English** | [简体中文](README.zh-CN.md)

</div>

# TiMEM vs MemOS vs Mem0 Benchmark

![CI](https://github.com/JoanhLan/timem-memos-mem0-benchmark/actions/workflows/ci.yml/badge.svg)

Independent benchmark project comparing **memory ingest** and **retrieval** between TiMEM, MemOS Cloud, and Mem0 Platform.

See [BENCHMARK_PROTOCOL.md](./BENCHMARK_PROTOCOL.md) for rules.

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** — only for dashboard development (`npm run dev`); production mode auto-builds the UI via `python main.py dashboard`

## Setup

```bash
cd timem-memos-mem0-benchmark   # or your clone directory
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
copy .env.example .env          # Windows — fill API keys
# cp .env.example .env          # Linux / macOS
```

**Development / tests:**

```bash
pip install -r requirements-dev.txt
pytest tests/unit -q
```

Required env vars:

| Variable | Description |
|----------|-------------|
| `TIMEM_BASE_URL` | Default `https://api.timem.cloud` (override with `http://localhost:8001` for local TiMEM) |
| `TIMEM_API_KEY` | TiMEM API key — register at [api.timem.cloud](https://api.timem.cloud) |
| `TIMEM_ACCOUNT_ID` | Required for backfill |
| `MEMOS_API_KEY` | MemOS Cloud token |
| `MEM0_API_KEY` | Mem0 Platform API key |
| `MEM0_BASE_URL` | Default `https://api.mem0.ai` |
| `ARK_API_KEY` | Volcengine ARK API key |
| `ARK_API_BASE` | Default `https://ark.cn-beijing.volces.com/api/v3` |
| `JUDGE_MODEL` | ARK endpoint id (e.g. `ep-xxx` or model id) |

## Quick start (fixture — no HuggingFace)

```bash
# Dry run with bundled sample persona (all three systems)
python main.py --fixture ingest
# note the run_id printed

python main.py --fixture retrieve <run_id> --mode T0
python main.py --fixture retrieve <run_id> --mode T1

# Run a subset of systems
python main.py --fixture ingest --systems timem,mem0
```

## Full benchmark (LoCoMo, 10 personas)

LoCoMo data is loaded from [snap-research/locomo](https://github.com/snap-research/locomo) (cached under `benchmark_data/cache/`). HuggingFace is an optional fallback — see `config/default.yaml`.

```bash
python main.py ingest --personas 10
python main.py retrieve <run_id> --mode T0
python main.py retrieve <run_id> --mode T1

# or one shot
python main.py full --personas 10
python main.py full --preset paper --personas 10
python main.py timem-sweep --fixture --mode T1
```

Reports are written to `reports/{run_id}/`.

## Dashboard (Benchmark Lab)

Vue 3 experiment console (similar to the TiMEM cloud dashboard at [api.timem.cloud](https://api.timem.cloud)):

- Start jobs on the page: **Full** (ingest → T0 → T1 with TiMEM backfill), or step **Ingest / T0 / T1**
- Default dataset: **fixture**; optional **LoCoMo 10 persona**
- Background jobs — you can leave the page and poll status later
- **Ingest** multi-column session details (TiMEM | MemOS | Mem0)
- **Compare** per-question retrieval side-by-side
- **Debug** single-query search on all enabled systems

**Production (single port):**

```powershell
cd dashboard
npm install
npm run build
cd ..
python main.py dashboard
```

Opens `http://127.0.0.1:8765/`.

**Development (hot reload):**

```powershell
# terminal 1
python main.py dashboard --api-only --no-browser

# terminal 2
cd dashboard
npm run dev
```

Open `http://127.0.0.1:5173/`.

**Quick start (one command, auto-builds UI if needed):**

```powershell
cd <repo-root>
python main.py dashboard
```

Or: `.\scripts\start_dashboard.ps1`

Force rebuild UI: `python main.py dashboard --rebuild`

### Workflow in the UI

1. **New Run** — optional custom Run ID (auto-generated if empty); dataset: Fixture or LoCoMo 10
2. **Full pipeline** or step **Ingest / T0 / T1**
3. **Ingest** — per-system session details
4. **Retrieval** — metrics + per-question recall drill-down
5. **Compare** — Overview / Ingest / Retrieval tabs
6. **Debug** — single-query search across systems (no formal report)

## Project layout

```
adapters/     TiMEM, MemOS & Mem0 REST clients
benchmark_data/     LoCoMo loader + fixtures
runners/      ingest, retrieval, token_compare
evaluators/   latency, recall@K, tokens, category metrics, ARK judge
utils/        message pair splitting (ingest granularity)
config/       default.yaml
reports/      JSON output per run
dashboard/    Vue comparison UI
```

## Disclaimer

- This is an **independent** benchmark harness. It is not affiliated with or endorsed by TiMEM, MemOS (MemTensor), or Mem0.
- TiMEM, MemOS, Mem0, and LoCoMo are trademarks or names of their respective owners.
- Running the full benchmark requires your own API credentials for each platform and a Volcengine ARK judge endpoint. You are responsible for complying with each vendor's terms of service and usage limits.

## Notes

- **Ingest concurrency**: Sessions run in parallel (`session_concurrency: 10` for TiMEM/MemOS/Mem0). Pairs within a session stay serial. **TiMEM**: only one session per `user_id` at a time (parallel across personas); ingest ends with L2 backfill/wait. TiMEM `session_id` sent to the API is `{run_id}_{persona_id}_session_{n}` so `memory_sessions` matches `user_id`. After ingest, check `ingest.json` → `timem_l2_finalize.l2_ready_count == persona_count`. See [BENCHMARK_PROTOCOL.md](./BENCHMARK_PROTOCOL.md#ingest-concurrency-benchmark-harness).
- **Mem0 poll**: Default `deferred` — POST pairs first, flush events per session; T0 flushes any stragglers.
- **Ingest latency**: Dashboard/API p50 is **per single add** (`add_latency`); `session_latency` kept for whole-session view. Old runs: `python scripts/migrate_ingest_add_latency.py --run-id <id>` (equal-split, `add_latency_estimated: true`).
- **Ingest granularity**: TiMEM and Mem0 write **adjacent 2-message pairs** per API call (official `fragment_size=2` / Contextual Add); MemOS sends the **full session** in one call. TiMEM `messages[].role` uses the **LoCoMo speaker name**; MemOS/Mem0 map to `user`/`assistant`. See [BENCHMARK_PROTOCOL.md](./BENCHMARK_PROTOCOL.md#ingest-granularity-per-system).
- **New run required**: After pair-chunking or TiMEM speaker-name payload changes, create a new `run_id` for ingest; do not compare with older runs that used whole-session TiMEM/Mem0 ingest or `user1`/`user2` as TiMEM roles.
- **LoCoMo ingest cost**: ~272 sessions × ~10 pairs ≈ 2700+ POST calls per system for TiMEM and Mem0; use session concurrency to reduce wall time.
- **Retrieval concurrency**: **Search→Judge pipeline** (`pipeline_mode: true`). TiMEM search default **3** (`timem_query_concurrency`) to avoid exhausting backend PostgreSQL `max_connections`; memos/mem0 query **10**; judge **10**; TiMEM backfill **3**. See [BENCHMARK_PROTOCOL.md](./BENCHMARK_PROTOCOL.md#retrieval-concurrency-benchmark-harness).
- **CLI tuning**: `python main.py retrieve <run_id> --query-concurrency 12 --judge-concurrency 6 --backfill-concurrency 3 --no-pipeline` (disable pipeline for A/B).
- **Token compare**: `reports/{run_id}/token_compare_T0.json` — per-question cross-system token deltas.
- **Dashboard**: Compare tab shows **Tokens** and **R@10** per question; Overview shows wall time and concurrency settings.
- **T0**: search after ingest (Mem0 events flushed before T0)
- **T1**: TiMEM manual backfill (`POST /api/v1/backfill/manual`) then search; MemOS/Mem0 unchanged
- User isolation: `timem_{run_id}_{persona}` / `memos_{run_id}_{persona}` / `mem0_{run_id}_{persona}`
- Mem0 ingest uses deferred event polling by default (`MEM0_INGEST_POLL_TIMEOUT_SEC`, default 120s)
- LoCoMo HF dataset id is configurable in `config/default.yaml`; parser may need tuning for your dataset revision

## License

MIT — see [LICENSE](./LICENSE).
