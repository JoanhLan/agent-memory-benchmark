"""Local HTTP server: benchmark reports API, background jobs, SPA static files."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from benchmark_jobs import JobOptions, job_manager
from adapters.registry import SUPPORTED_SYSTEMS, close_adapters, get_adapters
from utils.config import PROJECT_ROOT, get_settings, load_reference_baselines, make_user_id
from utils.ids import new_run_id, validate_run_id

REPORTS_DIR = PROJECT_ROOT / "reports"
DASHBOARD_DIST = PROJECT_ROOT / "dashboard" / "dist"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _system_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    backfill = report.get("backfill_summary") or {}
    backfill_total = backfill.get("backfill_total_ms") or {}
    return {
        "persona_count": report.get("persona_count"),
        "session_count": report.get("session_count"),
        "add_count": report.get("add_count"),
        "add_success_count": report.get("add_success_count"),
        "success_count": report.get("success_count"),
        "failure_count": report.get("failure_count"),
        "query_count": report.get("query_count"),
        "empty_count": report.get("empty_count"),
        "recall_at_5": report.get("recall_at_5"),
        "recall_at_10": report.get("recall_at_10"),
        "judge_accuracy": report.get("judge_accuracy"),
        "judge_avg_score": report.get("judge_avg_score"),
        "avg_recalled_tokens": report.get("avg_recalled_tokens"),
        "p50_recalled_tokens": report.get("p50_recalled_tokens"),
        "total_judge_tokens": report.get("total_judge_tokens"),
        "run_wall_ms": report.get("run_wall_ms"),
        "avg_input_tokens": report.get("avg_input_tokens"),
        "backfill_total_p50": backfill_total.get("p50"),
        "backfill_total_mean": backfill_total.get("mean"),
        "latency_p50": (report.get("add_latency") or report.get("latency") or {}).get("p50"),
        "latency_p95": (report.get("add_latency") or report.get("latency") or {}).get("p95"),
        "latency_mean": (report.get("add_latency") or report.get("latency") or {}).get("mean"),
        "session_latency_p50": (report.get("session_latency") or {}).get("p50"),
        "add_latency_estimated": report.get("add_latency_estimated"),
        "preset": report.get("preset"),
    }


def list_runs() -> list[dict[str, Any]]:
    if not REPORTS_DIR.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for entry in sorted(REPORTS_DIR.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        run_id = entry.name
        ingest = _load_json(entry / "ingest.json")
        retrieval_files = sorted(entry.glob("retrieval_*.json"))
        modes = [p.stem.replace("retrieval_", "") for p in retrieval_files]
        job = job_manager.reconcile_status(run_id) or job_manager.load_status(run_id)
        item: dict[str, Any] = {
            "run_id": run_id,
            "has_ingest": ingest is not None,
            "has_backfill": (entry / "backfill.json").is_file(),
            "has_sweep": (entry / "sweep_matrix.json").is_file(),
            "retrieval_modes": modes,
            "job": job,
        }
        for system in SUPPORTED_SYSTEMS:
            sys_block: dict[str, Any] = {"ingest": _system_summary((ingest or {}).get(system))}
            ret_block: dict[str, Any] = {}
            for mode in modes:
                data = _load_json(entry / f"retrieval_{mode}.json")
                if data:
                    ret_block[mode] = _system_summary(data.get(system))
            sys_block["retrieval"] = ret_block
            item[system] = sys_block
        runs.append(item)
    return runs


def load_dataset(
    run_id: str | None = None,
    *,
    use_fixture: bool | None = None,
    persona_count: int | None = None,
) -> dict[str, Any]:
    from benchmark_data.locomo_loader import load_locomo_personas

    uf = True if use_fixture is None else bool(use_fixture)
    pc = persona_count
    if run_id:
        job = job_manager.load_status(run_id)
        if job and job.get("options"):
            opts = job["options"]
            if use_fixture is None:
                uf = bool(opts.get("use_fixture", True))
            if persona_count is None:
                pc = int(opts.get("persona_count") or (1 if uf else 10))
    if pc is None:
        settings = get_settings()
        pc = 1 if uf else settings.benchmark_persona_count

    from benchmark_data.locomo_loader import get_last_load_info

    personas = load_locomo_personas(persona_count=pc, use_fixture=uf)
    load_info = get_last_load_info()
    rid = run_id or ""
    out_personas: list[dict[str, Any]] = []
    for p in personas:
        user_ids: dict[str, str | None] = {s: None for s in SUPPORTED_SYSTEMS}
        if rid:
            for s in SUPPORTED_SYSTEMS:
                user_ids[s] = make_user_id(s, rid, p.persona_id)
        out_personas.append(
            {
                "persona_id": p.persona_id,
                "user_ids": user_ids,
                "sessions": [
                    {
                        "session_id": s.session_id,
                        "message_count": len(s.messages),
                        "messages": [{"role": m.role, "content": m.content} for m in s.messages],
                    }
                    for s in p.sessions
                ],
                "qa_pairs": [
                    {
                        "question": q.question,
                        "answer": q.answer,
                        "category": q.category,
                    }
                    for q in p.qa_pairs
                ],
            }
        )
    loaded = len(out_personas)
    warning = None
    if load_info.get("source") == "fixture" and not uf:
        warning = (
            f"已选择 LoCoMo（目标 {pc} 个 persona），但实际只加载了 {loaded} 个（本地 Fixture 回退）。"
            f" 原因: {load_info.get('error') or 'HuggingFace 未加载'}"
        )
    elif loaded < pc:
        warning = f"目标 {pc} 个 persona，实际加载 {loaded} 个。"

    return {
        "run_id": run_id,
        "use_fixture": uf,
        "persona_count": pc,
        "persona_count_loaded": loaded,
        "dataset_label": (
            "fixture"
            if uf or load_info.get("source") == "fixture"
            else "locomo"
        ),
        "load_source_label": {
            "github": "LoCoMo 官方 (GitHub)",
            "huggingface": "LoCoMo (HuggingFace)",
            "fixture": "本地 Fixture",
        }.get(load_info.get("source") or "fixture", load_info.get("source")),
        "load_source": load_info.get("source"),
        "load_error": load_info.get("error"),
        "warning": warning,
        "personas": out_personas,
    }


def delete_run(run_id: str, *, force: bool = False) -> None:
    validate_run_id(run_id)
    job_manager.reconcile_status(run_id)
    if not force and job_manager.is_running(run_id):
        raise RuntimeError("任务运行中，无法删除")
    run_dir = REPORTS_DIR / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(run_id)
    shutil.rmtree(run_dir)


def load_run(run_id: str) -> dict[str, Any] | None:
    run_dir = REPORTS_DIR / run_id
    if not run_dir.is_dir():
        return None
    ingest = _load_json(run_dir / "ingest.json")
    retrieval: dict[str, Any] = {}
    for path in sorted(run_dir.glob("retrieval_*.json")):
        mode = path.stem.replace("retrieval_", "")
        retrieval[mode] = _load_json(path)
    category: dict[str, Any] = {}
    for path in sorted(run_dir.glob("summary_by_category_*.json")):
        mode = path.stem.replace("summary_by_category_", "")
        category[mode] = _load_json(path)
    return {
        "run_id": run_id,
        "ingest": ingest,
        "retrieval": retrieval,
        "backfill": _load_json(run_dir / "backfill.json"),
        "category_summary": category,
        "sweep_matrix": _load_json(run_dir / "sweep_matrix.json"),
        "reference_baselines": load_reference_baselines().get("locomo", {}),
        "job": job_manager.load_status(run_id),
    }


def check_health() -> dict[str, Any]:
    settings = get_settings()
    timem_ok = False
    timem_detail = ""
    try:
        headers: dict[str, str] = {}
        if settings.timem_api_key:
            headers["X-API-Key"] = settings.timem_api_key
        url = f"{settings.timem_base_url.rstrip('/')}/health"
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url, headers=headers)
            timem_ok = resp.status_code == 200
            timem_detail = f"HTTP {resp.status_code}"
    except Exception as exc:
        timem_detail = str(exc)

    memos_ok = bool(settings.memos_api_key.strip())
    mem0_ok = bool(settings.mem0_api_key.strip())
    judge_ok = bool(settings.ark_api_key.strip() and settings.judge_model.strip())

    return {
        "timem": {"ok": timem_ok, "url": settings.timem_base_url, "detail": timem_detail},
        "memos": {"ok": memos_ok, "url": settings.memos_base_url},
        "mem0": {"ok": mem0_ok, "url": settings.mem0_base_url},
        "judge": {
            "ok": judge_ok,
            "model": settings.judge_model or "(unset)",
        },
    }


async def debug_search(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload.get("run_id") or "")
    persona_id = str(payload.get("persona_id") or "locomo_persona_00")
    query = str(payload.get("query") or "").strip()
    if not run_id or not query:
        raise ValueError("run_id and query are required")

    systems = payload.get("systems") or list(SUPPORTED_SYSTEMS)
    if isinstance(systems, str):
        systems = [s.strip() for s in systems.split(",") if s.strip()]
    top_k = int(payload.get("top_k") or get_settings().benchmark_top_k)
    timem_overrides = payload.get("timem_overrides") or {}

    adapters = get_adapters(systems)

    results: dict[str, Any] = {}
    try:
        for name, adapter in adapters.items():
            user_id = make_user_id(name, run_id, persona_id)
            overrides = timem_overrides if name == "timem" else None
            sr = await adapter.search(
                user_id=user_id,
                query=query,
                top_k=top_k,
                overrides=overrides,
            )
            metrics = sr.metrics or {}
            raw_meta = sr.raw or {}
            results[name] = {
                "user_id": user_id,
                "success": sr.success,
                "latency_ms": sr.latency_ms,
                "recalled_tokens": metrics.get("recalled_tokens"),
                "recalled_chars": metrics.get("recalled_chars"),
                "layer_breakdown": metrics.get("layer_breakdown"),
                "workflow_metadata": raw_meta.get("workflow_metadata"),
                "search_config": raw_meta.get("search_config"),
                "error": sr.error,
                "records": [
                    {
                        "content": r.content,
                        "type": r.memory_type,
                        "layer": r.layer,
                        "score": r.score,
                    }
                    for r in sr.records
                ],
            }
    finally:
        await close_adapters(adapters)

    return {"run_id": run_id, "persona_id": persona_id, "query": query, "results": results}


class DashboardHandler(BaseHTTPRequestHandler):
    dist_root: Path = DASHBOARD_DIST

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path) -> bool:
        if not path.is_file():
            return False
        content_type, _ = mimetypes.guess_type(str(path))
        content_type = content_type or "application/octet-stream"
        self._send_bytes(path.read_bytes(), content_type)
        return True

    def _cors_preflight(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self._cors_preflight()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/health":
            self._send_json(check_health())
            return

        if path == "/api/meta":
            self._send_json(
                {
                    "version": 3,
                    "features": [
                        "create_run",
                        "delete_run",
                        "jobs",
                        "debug_search",
                        "dataset",
                        "timem_sweep",
                        "timem_backfill",
                        "pipeline_t0",
                        "reference_baselines",
                        "efficiency_metrics",
                    ],
                }
            )
            return

        if path == "/api/reference-baselines":
            self._send_json(load_reference_baselines())
            return

        if path == "/api/personas":
            qs = parse_qs(parsed.query)
            use_fixture = (qs.get("use_fixture") or ["true"])[0].lower() in ("1", "true", "yes")
            try:
                count = int((qs.get("persona_count") or ["10"])[0])
            except ValueError:
                count = 10
            from benchmark_data.locomo_loader import load_locomo_personas

            personas = load_locomo_personas(persona_count=count, use_fixture=use_fixture)
            self._send_json(
                {
                    "personas": [
                        {"persona_id": p.persona_id, "session_count": len(p.sessions)}
                        for p in personas
                    ]
                }
            )
            return

        if path == "/api/runs":
            self._send_json({"runs": list_runs()})
            return

        if path == "/api/runs/new":
            qs = parse_qs(parsed.query)
            custom = (qs.get("run_id") or [""])[0].strip()
            try:
                run_id = validate_run_id(custom) if custom else new_run_id()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            job_manager.create_run(run_id)
            self._send_json({"run_id": run_id})
            return

        if path == "/api/runs/delete":
            qs = parse_qs(parsed.query)
            run_id = (qs.get("run_id") or [""])[0].strip()
            force = (qs.get("force") or ["false"])[0].lower() in ("1", "true", "yes")
            if not run_id:
                self._send_json({"error": "run_id required"}, 400)
                return
            try:
                delete_run(run_id, force=force)
                self._send_json({"deleted": run_id})
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, 409)
            except FileNotFoundError:
                self._send_json({"error": "not found"}, 404)
            return

        if path.startswith("/api/runs/"):
            rest = path.removeprefix("/api/runs/").strip("/")
            parts = [p for p in rest.split("/") if p]
            if not parts:
                self._send_json({"error": "invalid path"}, 400)
                return
            run_id = parts[0]
            if len(parts) == 1:
                data = load_run(run_id)
                if data is None:
                    self._send_json({"error": "not found"}, 404)
                    return
                self._send_json(data)
                return
            if len(parts) >= 2 and parts[1] == "job":
                job = job_manager.load_status(run_id)
                if job is None:
                    self._send_json({"run_id": run_id, "status": "idle", "step": "idle"})
                    return
                job = job_manager.reconcile_status(run_id) or job
                self._send_json(job)
                return
            if len(parts) >= 2 and parts[1] == "dataset":
                qs = parse_qs(parsed.query)
                uf = None
                pc = None
                if qs.get("use_fixture"):
                    uf = qs.get("use_fixture")[0].lower() in ("1", "true", "yes")
                if qs.get("persona_count"):
                    try:
                        pc = int(qs.get("persona_count")[0])
                    except ValueError:
                        pass
                self._send_json(load_dataset(run_id, use_fixture=uf, persona_count=pc))
                return
            self._send_json({"error": "not found"}, 404)
            return

        if path == "/api/dataset":
            qs = parse_qs(parsed.query)
            uf = (qs.get("use_fixture") or ["true"])[0].lower() in ("1", "true", "yes")
            try:
                pc = int((qs.get("persona_count") or ["1"])[0])
            except ValueError:
                pc = 1
            self._send_json(load_dataset(None, use_fixture=uf, persona_count=pc))
            return

        if not self._serve_static(path):
            self._send_json(
                {
                    "error": "dashboard not built",
                    "hint": "cd dashboard; npm install; npm run build",
                },
                503,
            )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        if path == "/api/runs":
            raw = body.get("run_id")
            try:
                run_id = validate_run_id(str(raw)) if raw else new_run_id()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            job_manager.create_run(run_id)
            self._send_json({"run_id": run_id})
            return

        if path == "/api/debug/search":
            try:
                result = asyncio.run(debug_search(body))
                self._send_json(result)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        if path.startswith("/api/runs/"):
            rest = path.removeprefix("/api/runs/").strip("/")
            parts = [p for p in rest.split("/") if p]
            if len(parts) == 2 and parts[1] == "delete":
                run_id = parts[0]
                force = bool(body.get("force"))
                try:
                    delete_run(run_id, force=force)
                    self._send_json({"deleted": run_id})
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, 400)
                except RuntimeError as exc:
                    self._send_json({"error": str(exc)}, 409)
                except FileNotFoundError:
                    self._send_json({"error": "not found"}, 404)
                return

            if len(parts) == 2 and parts[1] == "jobs":
                run_id = parts[0]
                job_type = body.get("type") or "full"
                if job_type not in ("full", "ingest", "retrieve", "timem_sweep", "backfill", "pipeline"):
                    self._send_json({"error": "invalid job type"}, 400)
                    return
                (REPORTS_DIR / run_id).mkdir(parents=True, exist_ok=True)
                if job_manager.load_status(run_id) is None:
                    job_manager.create_run(run_id)
                options = JobOptions.from_dict(body)
                try:
                    state = job_manager.start_job(run_id, job_type, options)
                    self._send_json(state)
                except RuntimeError as exc:
                    self._send_json({"error": str(exc)}, 409)
                return

        self._send_json({"error": "not found"}, 404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path.startswith("/api/runs/"):
            rest = path.removeprefix("/api/runs/").strip("/")
            parts = [p for p in rest.split("/") if p]
            if len(parts) != 1:
                self._send_json({"error": "invalid path"}, 400)
                return
            run_id = parts[0]
            qs = parse_qs(parsed.query)
            force = (qs.get("force") or ["false"])[0].lower() in ("1", "true", "yes")
            try:
                delete_run(run_id, force=force)
                self._send_json({"deleted": run_id})
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, 409)
            except FileNotFoundError:
                self._send_json({"error": "not found"}, 404)
            return

        self._send_json({"error": "not found"}, 404)

    def _serve_static(self, path: str) -> bool:
        if not self.dist_root.is_dir():
            return False
        rel = path.lstrip("/") or "index.html"
        file_path = (self.dist_root / rel).resolve()
        if not str(file_path).startswith(str(self.dist_root.resolve())):
            self._send_json({"error": "forbidden"}, 403)
            return True
        if file_path.is_file():
            self._send_file(file_path)
            return True
        index = self.dist_root / "index.html"
        if index.is_file():
            self._send_file(index)
            return True
        return False


def run_dashboard_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    *,
    kill_port: bool = True,
) -> None:
    from dashboard_build import ensure_dashboard_built
    from dashboard_port import free_port, verify_dashboard_api

    if kill_port:
        for attempt in range(3):
            stopped = free_port(port)
            if stopped:
                print(f"Cleared port {port} (stopped old PID(s): {', '.join(map(str, stopped))})")
            from dashboard_port import describe_dashboard_api, pids_listening_on_port

            if not pids_listening_on_port(port):
                break
            if attempt < 2:
                import time

                time.sleep(0.6)
        else:
            from dashboard_port import describe_dashboard_api, pids_listening_on_port

            remaining = pids_listening_on_port(port)
            if remaining:
                print(
                    f"ERROR: port {port} still held by PID(s) {sorted(remaining)}. "
                    f"API there: {describe_dashboard_api(host, port)}"
                )
                print(f"Run: taskkill /F /PID <pid>   then: python main.py dashboard --rebuild")
                raise SystemExit(1)

    ensure_dashboard_built()
    if not DASHBOARD_DIST.is_dir():
        print(
            "Note: dashboard/dist not found. API works; UI needs build:\n"
            "  cd dashboard; npm install; npm run build\n"
            "Or dev: python main.py dashboard --api-only  (then npm run dev in dashboard/)"
        )
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    url = f"http://{host}:{port}/"
    print(f"Benchmark dashboard: {url}")
    print(f"Reports directory: {REPORTS_DIR}")
    from dashboard_port import describe_dashboard_api

    import threading
    import time

    serve_thread = threading.Thread(target=server.serve_forever, name="dashboard-http", daemon=True)
    serve_thread.start()
    time.sleep(0.3)

    if not verify_dashboard_api(host, port):
        print(f"ERROR: API self-check failed on {url} — {describe_dashboard_api(host, port)}")
        print("Stale dashboard still on this port. Stop it and rerun: python main.py dashboard --rebuild")
        server.shutdown()
        raise SystemExit(1)
    print("API OK (timem_sweep supported)")
    if open_browser and DASHBOARD_DIST.is_dir():
        webbrowser.open(url)
    # Windows: bare Thread.join() ignores Ctrl+C until the thread ends.
    # Poll with a short timeout so KeyboardInterrupt can reach the main thread.
    try:
        while serve_thread.is_alive():
            serve_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()
        serve_thread.join(timeout=2.0)
