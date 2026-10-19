#!/usr/bin/env python3
"""Agent Memory Benchmark CLI.

Default path simulates the AML text track (Add / Search, then a local unofficial score).
The older TiMEM / MemOS / Mem0 commands remain available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_data.catalog import DATASETS, runnable_ids
from runners.aml_run import run_add, run_pipeline, run_score, run_search
from runners.ingest_run import run_ingest
from runners.retrieval_run import run_retrieval
from runners.timem_sweep import parse_sweep_values, run_timem_sweep
from utils.ids import new_run_id, validate_run_id


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Agent Memory Benchmark")
    p.add_argument("--fixture", action="store_true", help="Use local sample dataset")
    p.add_argument("--personas", type=int, default=None, help="Number of LoCoMo personas")
    p.add_argument("--systems", default="timem,memos,mem0", help="Comma-separated: timem,memos,mem0")
    p.add_argument("--no-judge", action="store_true", help="Skip ARK judge")
    p.add_argument(
        "--preset",
        choices=["stable", "paper"],
        default=None,
        help="Benchmark preset: stable (default) or paper (top_k=20; both use enhanced_semantic)",
    )
    p.add_argument("--query-concurrency", type=int, default=None, help="Retrieval search concurrency (memos/mem0)")
    p.add_argument("--timem-query-concurrency", type=int, default=None, help="TiMEM retrieval concurrency")
    p.add_argument("--judge-concurrency", type=int, default=None, help="ARK judge concurrency")
    p.add_argument("--backfill-concurrency", type=int, default=None, help="T1 TiMEM backfill concurrency")
    p.add_argument(
        "--no-pipeline",
        action="store_true",
        help="Use two-phase retrieval (all search then all judge) instead of pipeline",
    )

    sub = p.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("aml-datasets", help="List AML text datasets")
    listing.set_defaults(command="aml-datasets")

    aml_add = sub.add_parser("aml-add", help="AML Add: chunk and write one text dataset")
    aml_add.add_argument("--dataset", required=False, choices=runnable_ids())
    aml_add.add_argument(
        "--paper",
        default=None,
        help="aml-eval paper JSON (e.g. aml-eval/datasets/locomo_refined/papers/daily.json)",
    )
    aml_add.add_argument("--run-id", default=None)
    aml_add.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max samples when --paper is not set (ignored if --paper is set)",
    )
    aml_add.add_argument(
        "--streaming",
        action="store_true",
        help="After each written chunk, search every question. Score uses the last search.",
    )

    aml_search = sub.add_parser("aml-search", help="AML Search for a run produced by aml-add")
    aml_search.add_argument("run_id")

    aml_score = sub.add_parser("aml-score", help="Unofficial answer-then-judge score")
    aml_score.add_argument("run_id")

    aml_full = sub.add_parser("aml", help="AML per-sample Add, Search, and unofficial score")
    aml_full.add_argument("--dataset", required=False, choices=runnable_ids())
    aml_full.add_argument("--paper", default=None, help="aml-eval paper JSON (daily or full)")
    aml_full.add_argument("--run-id", default=None)
    aml_full.add_argument("--limit", type=int, default=None)
    aml_full.add_argument("--skip-score", action="store_true")
    aml_full.add_argument(
        "--streaming",
        action="store_true",
        help="Search after each written chunk. Score uses the last search and skips a second search pass.",
    )

    ingest = sub.add_parser("ingest", help="Legacy three-system ingest")
    ingest.add_argument("--run-id", default=None)
    ingest.add_argument(
        "--no-wait-timem-l2",
        action="store_true",
        help="Skip TiMEM L2 backfill/wait after ingest (default: wait for L2)",
    )

    ret = sub.add_parser("retrieve", help="Run retrieval benchmark")
    ret.add_argument("run_id", help="Run id from ingest stage")
    ret.add_argument("--mode", choices=["T0", "T1"], default="T0")

    full = sub.add_parser("full", help="Ingest then retrieve T0 (+ T1 for timem backfill)")
    full.add_argument("--run-id", default=None)
    full.add_argument("--skip-t1", action="store_true")

    sweep = sub.add_parser("timem-sweep", help="TiMEM-only parameter sweep")
    sweep.add_argument("--run-id", default=None, help="Sweep id (also used as ingest run_id)")
    sweep.add_argument("--mode", choices=["T0", "T1"], default="T1")
    sweep.add_argument("--skip-backfill", action="store_true")
    sweep.add_argument("--skip-ingest", action="store_true")
    sweep.add_argument(
        "--params",
        default="search_mode,use_hybrid",
        help="Comma-separated sweep axes",
    )
    sweep.add_argument(
        "--values",
        action="append",
        default=[],
        help="Param values, e.g. search_mode=semantic,enhanced_semantic",
    )

    dash = sub.add_parser("dashboard", help="Serve benchmark comparison UI (read reports/)")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8765)
    dash.add_argument("--api-only", action="store_true", help="API only (use with: cd dashboard && npm run dev)")
    dash.add_argument("--no-browser", action="store_true")
    dash.add_argument("--rebuild", action="store_true", help="Force npm run build before serve")
    dash.add_argument(
        "--no-kill-port",
        action="store_true",
        help="Do not stop other processes listening on --port (default: kill stale servers)",
    )

    return p


def _base_kwargs(args: argparse.Namespace) -> dict:
    return {
        "persona_count": args.personas,
        "use_fixture": args.fixture,
    }


def _retrieval_kwargs(args: argparse.Namespace) -> dict:
    overrides: dict = {}
    if getattr(args, "query_concurrency", None) is not None:
        overrides["query_concurrency"] = args.query_concurrency
    if getattr(args, "timem_query_concurrency", None) is not None:
        overrides["timem_query_concurrency"] = args.timem_query_concurrency
    if getattr(args, "judge_concurrency", None) is not None:
        overrides["judge_concurrency"] = args.judge_concurrency
    if getattr(args, "backfill_concurrency", None) is not None:
        overrides["backfill_concurrency"] = args.backfill_concurrency
    if getattr(args, "no_pipeline", False):
        overrides["pipeline_mode"] = False
    return {
        **_base_kwargs(args),
        "preset": args.preset,
        "retrieval_overrides": overrides or None,
    }


async def _cmd_ingest(args: argparse.Namespace) -> str:
    run_id = validate_run_id(args.run_id) if args.run_id else new_run_id()
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    reports = await run_ingest(
        run_id=run_id,
        systems=systems,
        wait_timem_l2_on_ingest=not getattr(args, "no_wait_timem_l2", False),
        **_base_kwargs(args),
    )
    print(json.dumps({k: asdict(v) for k, v in reports.items()}, indent=2, ensure_ascii=False))
    print(f"\nrun_id={run_id}")
    return run_id


async def _cmd_retrieve(args: argparse.Namespace) -> None:
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    reports = await run_retrieval(
        run_id=args.run_id,
        mode=args.mode,
        systems=systems,
        run_judge=not args.no_judge,
        **_retrieval_kwargs(args),
    )
    # Avoid dumping full detail blobs to console (huge + may contain chars that break GBK).
    summary = {
        k: {
            "system": getattr(v, "system", k),
            "mode": getattr(v, "mode", args.mode),
            "detail_count": len(getattr(v, "details", []) or []),
        }
        for k, v in reports.items()
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nReports under reports/{args.run_id}/retrieval_{args.mode}.json")


async def _cmd_full(args: argparse.Namespace) -> None:
    run_id = await _cmd_ingest(args)
    args.run_id = run_id
    args.mode = "T0"
    print("\n--- Retrieval T0 ---\n")
    await _cmd_retrieve(args)
    if not args.skip_t1:
        args.mode = "T1"
        print("\n--- Retrieval T1 (TiMEM backfill) ---\n")
        await _cmd_retrieve(args)


async def _cmd_timem_sweep(args: argparse.Namespace) -> None:
    sweep_id = validate_run_id(args.run_id) if args.run_id else f"sweep_{new_run_id()}"
    params = [p.strip() for p in args.params.split(",") if p.strip()]
    value_map = parse_sweep_values(args.values or [])
    payload = await run_timem_sweep(
        sweep_id=sweep_id,
        mode=args.mode,
        use_fixture=args.fixture,
        persona_count=args.personas,
        run_judge=not args.no_judge,
        skip_backfill=args.skip_backfill,
        skip_ingest=args.skip_ingest,
        params=params,
        value_map=value_map,
        preset=args.preset,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nsweep_id={sweep_id}")


def _aml_run_targets(args: argparse.Namespace) -> tuple[str, dict | None, str | None, int | None]:
    from benchmark_data.aml_papers import load_paper, resolve_paper_path

    paper_path: str | None = getattr(args, "paper", None)
    paper: dict | None = None
    if paper_path:
        resolved = resolve_paper_path(paper_path)
        paper = load_paper(resolved)
        paper_path = str(resolved)
        dataset_id = str(paper["dataset_id"])
        if getattr(args, "dataset", None) and args.dataset != dataset_id:
            raise SystemExit(f"--dataset {args.dataset} does not match paper dataset_id {dataset_id}")
    elif getattr(args, "dataset", None):
        dataset_id = args.dataset
    else:
        raise SystemExit("Provide --dataset or --paper")
    limit = None if paper else getattr(args, "limit", None)
    return dataset_id, paper, paper_path, limit


def _cmd_aml_datasets() -> None:
    rows = [
        {
            "id": item.dataset_id,
            "title": item.title,
            "runnable": item.runnable,
            "source": item.source,
            "note": item.note,
        }
        for item in DATASETS.values()
    ]
    print(json.dumps(rows, indent=2, ensure_ascii=False))


async def _cmd_aml(args: argparse.Namespace) -> None:
    run_id = validate_run_id(args.run_id) if args.run_id else new_run_id()
    dataset_id, paper, paper_path, limit = _aml_run_targets(args)
    if getattr(args, "streaming", False):
        report = run_add(
            run_id=run_id,
            dataset_id=dataset_id,
            limit=limit,
            paper=paper,
            paper_path=paper_path,
            streaming=True,
        )
        print(json.dumps({k: v for k, v in report.items() if k != "adds"}, indent=2, ensure_ascii=False))
        print(json.dumps({"searched": report.get("streaming_searches", 0), "streaming": True}, ensure_ascii=False))
        if not args.skip_score:
            score = await run_score(run_id=run_id)
            print(json.dumps({k: v for k, v in score.items() if k != "results"}, indent=2, ensure_ascii=False))
    else:
        report = await run_pipeline(
            run_id=run_id,
            dataset_id=dataset_id,
            limit=limit,
            paper=paper,
            paper_path=paper_path,
            skip_score=bool(args.skip_score),
        )
        print(json.dumps({"searched": report["searched"], "pipeline": "sample"}, ensure_ascii=False))
        if report.get("score"):
            print(json.dumps({k: v for k, v in report["score"].items() if k != "results"}, indent=2, ensure_ascii=False))
    print(f"\nrun_id={run_id}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "aml-datasets":
        _cmd_aml_datasets()
    elif args.command == "aml-add":
        run_id = validate_run_id(args.run_id) if args.run_id else new_run_id()
        dataset_id, paper, paper_path, limit = _aml_run_targets(args)
        report = run_add(
            run_id=run_id,
            dataset_id=dataset_id,
            limit=limit,
            paper=paper,
            paper_path=paper_path,
            streaming=bool(args.streaming),
        )
        print(json.dumps({k: v for k, v in report.items() if k != "adds"}, indent=2, ensure_ascii=False))
        print(f"\nrun_id={run_id}")
    elif args.command == "aml-search":
        report = run_search(run_id=args.run_id)
        print(json.dumps({"searched": len(report["results"])}, ensure_ascii=False))
    elif args.command == "aml-score":
        score = asyncio.run(run_score(run_id=args.run_id))
        print(json.dumps({k: v for k, v in score.items() if k != "results"}, indent=2, ensure_ascii=False))
    elif args.command == "aml":
        asyncio.run(_cmd_aml(args))
    elif args.command == "ingest":
        asyncio.run(_cmd_ingest(args))
    elif args.command == "retrieve":
        asyncio.run(_cmd_retrieve(args))
    elif args.command == "full":
        asyncio.run(_cmd_full(args))
    elif args.command == "timem-sweep":
        asyncio.run(_cmd_timem_sweep(args))
    elif args.command == "dashboard":
        from dashboard_build import ensure_dashboard_built
        from dashboard_server import run_dashboard_server

        ensure_dashboard_built(force=args.rebuild)
        run_dashboard_server(
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser and not args.api_only,
            kill_port=not args.no_kill_port,
        )


if __name__ == "__main__":
    main()
