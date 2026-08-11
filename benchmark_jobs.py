"""Background benchmark jobs for the dashboard (CLI-equivalent runners)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from runners.ingest_run import run_ingest
from runners.retrieval_run import run_retrieval
from runners.timem_backfill_run import normalize_backfill_layers, run_timem_backfill
from runners.timem_sweep import parse_sweep_values, run_timem_sweep
from utils.config import PROJECT_ROOT, get_settings, resolve_retrieval_config
from utils.ids import new_run_id, validate_run_id

logger = logging.getLogger(__name__)

REPORTS_DIR = PROJECT_ROOT / "reports"

JobType = Literal["full", "ingest", "retrieve", "timem_sweep", "backfill", "pipeline"]


def _normalize_memory_language(value: Any, *, default: str = "en") -> str:
    lang = str(value if value is not None else default or "en").strip().lower()
    return lang if lang in ("zh", "en") else "en"


@dataclass
class JobOptions:
    use_fixture: bool = True
    persona_count: int | None = None
    systems: list[str] = field(default_factory=lambda: ["timem", "memos", "mem0"])
    run_judge: bool = True
    skip_t1: bool = False
    mode: Literal["T0", "T1"] = "T0"
    preset: str | None = None
    timem_overrides: dict[str, Any] = field(default_factory=dict)
    sweep_params: list[str] = field(default_factory=lambda: ["search_mode", "use_hybrid"])
    sweep_values: list[str] = field(default_factory=list)
    skip_backfill: bool = False
    skip_ingest: bool = False
    retrieval_overrides: dict[str, Any] = field(default_factory=dict)
    backfill_layers: list[str] = field(default_factory=lambda: ["L2"])
    wait_timem_l2_on_ingest: bool = False
    memory_language: str = "en"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobOptions:
        systems = data.get("systems") or ["timem", "memos", "mem0"]
        if isinstance(systems, str):
            systems = [s.strip() for s in systems.split(",") if s.strip()]
        sweep_params = data.get("sweep_params") or ["search_mode", "use_hybrid"]
        if isinstance(sweep_params, str):
            sweep_params = [p.strip() for p in sweep_params.split(",") if p.strip()]
        sweep_values = data.get("sweep_values") or []
        if isinstance(sweep_values, str):
            sweep_values = [sweep_values]
        backfill_layers_raw = data.get("backfill_layers")
        if backfill_layers_raw is None:
            backfill_layers = ["L2"]
        elif isinstance(backfill_layers_raw, list) and not backfill_layers_raw:
            backfill_layers = []
        else:
            backfill_layers = normalize_backfill_layers(backfill_layers_raw)
        return cls(
            use_fixture=bool(data.get("use_fixture", True)),
            persona_count=data.get("persona_count"),
            systems=list(systems),
            run_judge=bool(data.get("run_judge", True)),
            skip_t1=bool(data.get("skip_t1", False)),
            mode=data.get("mode") or "T0",
            preset=data.get("preset"),
            timem_overrides=dict(data.get("timem_overrides") or {}),
            sweep_params=list(sweep_params),
            sweep_values=list(sweep_values),
            skip_backfill=bool(data.get("skip_backfill", False)),
            skip_ingest=bool(data.get("skip_ingest", False)),
            retrieval_overrides=dict(data.get("retrieval_overrides") or {}),
            backfill_layers=backfill_layers,
            wait_timem_l2_on_ingest=bool(data.get("wait_timem_l2_on_ingest", False)),
            memory_language=_normalize_memory_language(
                data.get("memory_language"),
                default=get_settings().timem_memory_language,
            ),
        )


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def status_path(self, run_id: str) -> Path:
        return REPORTS_DIR / run_id / "job_status.json"

    def log_path(self, run_id: str) -> Path:
        return REPORTS_DIR / run_id / "job.log"

    def load_status(self, run_id: str) -> dict[str, Any] | None:
        path = self.status_path(run_id)
        if not path.is_file():
            return None
        for attempt in range(5):
            try:
                text = path.read_text(encoding="utf-8")
                if not text.strip():
                    if attempt < 4:
                        time.sleep(0.02)
                        continue
                    return None
                return json.loads(text)
            except json.JSONDecodeError:
                if attempt < 4:
                    time.sleep(0.02)
                    continue
                logger.warning("Corrupt or partial job_status.json for run_id=%s", run_id)
                return None
        return None

    def _save_status(self, run_id: str, state: dict[str, Any]) -> None:
        path = self.status_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def append_log(self, run_id: str, line: str) -> None:
        with self._lock:
            log_file = self.log_path(run_id)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line.rstrip() + "\n")
            state = self.load_status(run_id) or {}
            logs: list[str] = list(state.get("logs") or [])
            logs.append(line.rstrip())
            state["logs"] = logs[-200:]
            self._save_status(run_id, state)

    def _patch_status(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            state = self.load_status(run_id) or {"run_id": run_id}
            state.update(kwargs)
            self._save_status(run_id, state)
            return state

    def reconcile_status(self, run_id: str) -> dict[str, Any] | None:
        """Mark stale 'running' jobs as failed when no background thread is alive."""
        state = self.load_status(run_id)
        if not state or state.get("status") != "running":
            return state
        thread = self._threads.get(run_id)
        if thread is not None and thread.is_alive():
            return state
        return self._patch_status(
            run_id,
            status="failed",
            step="interrupted",
            error="任务已中断（服务重启或后台结束），可删除",
        )

    def is_running(self, run_id: str) -> bool:
        state = self.reconcile_status(run_id)
        return bool(state and state.get("status") == "running")

    def create_run(self, run_id: str | None = None) -> str:
        rid = validate_run_id(run_id) if run_id else new_run_id()
        (REPORTS_DIR / rid).mkdir(parents=True, exist_ok=True)
        self._patch_status(
            rid,
            status="idle",
            step="idle",
            percent=0,
            job_type=None,
            logs=[],
            error=None,
        )
        return rid

    def start_job(self, run_id: str, job_type: JobType, options: JobOptions) -> dict[str, Any]:
        if self.is_running(run_id):
            raise RuntimeError(f"Run {run_id} already has a job in progress")

        settings = get_settings()
        persona_count = options.persona_count
        if persona_count is None:
            persona_count = 1 if options.use_fixture else settings.benchmark_persona_count

        self._patch_status(
            run_id,
            status="running",
            step="starting",
            percent=0,
            job_type=job_type,
            options={
                "use_fixture": options.use_fixture,
                "persona_count": persona_count,
                "systems": options.systems,
                "run_judge": options.run_judge,
                "skip_t1": options.skip_t1,
                "mode": options.mode,
                "preset": options.preset,
                "timem_overrides": options.timem_overrides,
                "sweep_params": options.sweep_params,
                "sweep_values": options.sweep_values,
                "skip_backfill": options.skip_backfill,
                "skip_ingest": options.skip_ingest,
                "retrieval_overrides": options.retrieval_overrides,
                "backfill_layers": options.backfill_layers,
                "wait_timem_l2_on_ingest": options.wait_timem_l2_on_ingest,
                "memory_language": options.memory_language,
            },
            error=None,
            logs=(self.load_status(run_id) or {}).get("logs") or [],
        )
        self.append_log(run_id, f"[job] Started {job_type} for run {run_id}")

        thread = threading.Thread(
            target=self._thread_main,
            args=(run_id, job_type, options, persona_count),
            daemon=True,
            name=f"benchmark-job-{run_id}",
        )
        with self._lock:
            self._threads[run_id] = thread
        thread.start()
        return self.load_status(run_id) or {}

    def _thread_main(
        self,
        run_id: str,
        job_type: JobType,
        options: JobOptions,
        persona_count: int,
    ) -> None:
        handler = _JobLogHandler(self, run_id)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            asyncio.run(
                self._execute(run_id, job_type, options, persona_count)
            )
            self._patch_status(run_id, status="completed", step="done", percent=100)
            self.append_log(run_id, "[job] Completed successfully")
        except Exception as exc:
            logger.exception("Job failed for run %s", run_id)
            self._patch_status(
                run_id,
                status="failed",
                step="failed",
                error=str(exc),
            )
            self.append_log(run_id, f"[job] Failed: {exc}")
        finally:
            root.removeHandler(handler)
            with self._lock:
                self._threads.pop(run_id, None)

    async def _execute(
        self,
        run_id: str,
        job_type: JobType,
        options: JobOptions,
        persona_count: int,
    ) -> None:
        base = dict(
            run_id=run_id,
            systems=options.systems,
            persona_count=persona_count,
            use_fixture=options.use_fixture,
        )
        retrieval_kwargs = dict(
            **base,
            preset=options.preset,
            timem_overrides=options.timem_overrides or None,
            retrieval_overrides=options.retrieval_overrides or None,
        )

        if job_type == "ingest":
            self._set_step(run_id, "ingest_running", 10)
            await run_ingest(
                **base,
                wait_timem_l2_on_ingest=options.wait_timem_l2_on_ingest,
                memory_language=options.memory_language,
            )
            self._set_step(run_id, "ingest_done", 100)
            return

        if job_type == "retrieve":
            mode = options.mode
            self._set_step(run_id, f"{mode.lower()}_running", 20)
            await run_retrieval(**retrieval_kwargs, mode=mode, run_judge=options.run_judge)
            self._set_step(run_id, f"{mode.lower()}_done", 100)
            return

        if job_type == "backfill":
            ret_cfg = resolve_retrieval_config(options.retrieval_overrides or None)
            self._set_step(run_id, "backfill_running", 20)
            await run_timem_backfill(
                run_id=run_id,
                layers=options.backfill_layers,
                use_fixture=options.use_fixture,
                persona_count=persona_count,
                backfill_concurrency=ret_cfg.backfill_concurrency,
                retrieval_overrides=options.retrieval_overrides or None,
            )
            self._set_step(run_id, "backfill_done", 100)
            return

        if job_type == "timem_sweep":
            self._set_step(run_id, "sweep_running", 10)
            await run_timem_sweep(
                sweep_id=run_id,
                mode=options.mode,
                use_fixture=options.use_fixture,
                persona_count=persona_count,
                run_judge=options.run_judge,
                skip_backfill=options.skip_backfill,
                skip_ingest=options.skip_ingest,
                params=options.sweep_params,
                value_map=parse_sweep_values(options.sweep_values),
                preset=options.preset,
            )
            self._set_step(run_id, "sweep_done", 100)
            return

        if job_type == "pipeline":
            ret_cfg = resolve_retrieval_config(options.retrieval_overrides or None)
            self._set_step(run_id, "ingest_running", 5)
            await run_ingest(
                **base,
                wait_timem_l2_on_ingest=options.wait_timem_l2_on_ingest,
                memory_language=options.memory_language,
            )
            self._set_step(run_id, "ingest_done", 30)

            if "timem" in options.systems and options.backfill_layers:
                self._set_step(run_id, "backfill_running", 35)
                await run_timem_backfill(
                    run_id=run_id,
                    layers=options.backfill_layers,
                    use_fixture=options.use_fixture,
                    persona_count=persona_count,
                    backfill_concurrency=ret_cfg.backfill_concurrency,
                    retrieval_overrides=options.retrieval_overrides or None,
                )
                self._set_step(run_id, "backfill_done", 55)
            else:
                self._set_step(run_id, "backfill_skipped", 35)
                self.append_log(
                    run_id,
                    "[job] skip backfill (no timem or empty backfill_layers)",
                )
                self._set_step(run_id, "backfill_done", 55)

            self._set_step(run_id, "t0_running", 60)
            await run_retrieval(**retrieval_kwargs, mode="T0", run_judge=options.run_judge)
            self._set_step(run_id, "t0_done", 100)
            return

        # full
        self._set_step(run_id, "ingest_running", 5)
        await run_ingest(
            **base,
            wait_timem_l2_on_ingest=options.wait_timem_l2_on_ingest,
            memory_language=options.memory_language,
        )
        self._set_step(run_id, "ingest_done", 30)

        self._set_step(run_id, "t0_running", 35)
        await run_retrieval(**retrieval_kwargs, mode="T0", run_judge=options.run_judge)
        self._set_step(run_id, "t0_done", 65)

        if options.skip_t1:
            self.append_log(run_id, "[job] skip_t1=true, skipping T1 retrieval")
            self._set_step(run_id, "t1_done", 100)
            return

        self._set_step(run_id, "t1_running", 70)
        await run_retrieval(**retrieval_kwargs, mode="T1", run_judge=options.run_judge)
        self._set_step(run_id, "t1_done", 100)

    def _set_step(self, run_id: str, step: str, percent: float) -> None:
        self._patch_status(run_id, step=step, percent=percent, status="running")
        self.append_log(run_id, f"[job] step={step} ({percent:.0f}%)")


class _JobLogHandler(logging.Handler):
    def __init__(self, manager: JobManager, run_id: str) -> None:
        super().__init__()
        self._manager = manager
        self._run_id = run_id

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._manager.append_log(self._run_id, msg)
        except Exception:
            pass


job_manager = JobManager()
