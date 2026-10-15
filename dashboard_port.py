"""Free TCP port before starting the dashboard (avoid stale duplicate servers)."""

from __future__ import annotations

import subprocess
import sys
import time


def pids_listening_on_port(port: int) -> set[int]:
    pids: set[int] = set()
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                errors="ignore",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return pids
        needle = f":{port}"
        for line in out.splitlines():
            if "LISTENING" not in line.upper() or needle not in line:
                continue
            parts = line.split()
            if not parts:
                continue
            try:
                pids.add(int(parts[-1]))
            except ValueError:
                continue
        return pids

    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f":{port}"],
            text=True,
            errors="ignore",
        )
        for part in out.split():
            try:
                pids.add(int(part.strip()))
            except ValueError:
                pass
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return pids


def free_port(port: int, *, exclude_pid: int | None = None) -> list[int]:
    """Kill processes listening on `port`. Returns list of stopped PIDs."""
    my_pid = exclude_pid if exclude_pid is not None else os_getpid()
    stopped: list[int] = []
    for pid in pids_listening_on_port(port):
        if pid == my_pid or pid == 0:
            continue
        print(f"Port {port} in use by PID {pid}, stopping…")
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            subprocess.run(["kill", "-9", str(pid)], check=False)
        stopped.append(pid)
    if stopped:
        time.sleep(0.4)
    return stopped


def os_getpid() -> int:
    import os

    return os.getpid()


def _local_client():
    import httpx

    # Bypass HTTP_PROXY for 127.0.0.1 (otherwise self-check may 502/timeout).
    return httpx.Client(trust_env=False, timeout=5.0)


def verify_dashboard_api(host: str, port: int) -> bool:
    """Return True if server speaks the current JSON API (incl. timem_sweep).

    Only probes /api/meta. Do not call /api/health here: that endpoint may wait on
    TiMEM /health, and on Windows a down :8001 often SYN-times-out (~5s), which
    races the 5s client timeout and falsely reports a stale dashboard.
    """
    try:
        with _local_client() as client:
            meta = client.get(f"http://{host}:{port}/api/meta")
            if meta.status_code != 200:
                return False
            ct = meta.headers.get("content-type", "")
            if "json" not in ct:
                return False
            body = meta.json()
            features = body.get("features") or []
            return "timem_sweep" in features
    except Exception:
        return False


def describe_dashboard_api(host: str, port: int) -> str:
    """Human-readable API version on port (for startup diagnostics)."""
    try:
        with _local_client() as client:
            meta = client.get(f"http://{host}:{port}/api/meta")
            if meta.status_code != 200:
                return f"HTTP {meta.status_code}"
            body = meta.json()
            version = body.get("version", "?")
            features = body.get("features") or []
            return f"v{version}, features={features}"
    except Exception as exc:
        return str(exc)
