"""One owned child per admitted job; fixed error categories and measured resource use."""

import json
import multiprocessing
import os
import resource
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ontology_platform.execution.config import ExecutionSettings


def peak_memory_bytes() -> int:
    if sys.platform == "linux":
        # ru_maxrss survives exec on Linux and can include the controller's pre-exec
        # footprint. VmHWM belongs to this executable's memory map instead.
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
        raise RuntimeError("Linux process high-water memory accounting unavailable")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def configure_child() -> None:
    # Trusted adapters need local paths and budgets, never controller credentials.
    allowed_environment = {"PATH", "PYTHONPATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ"}
    for variable in tuple(os.environ):
        if variable not in allowed_environment:
            del os.environ[variable]
    os.environ["POLARS_MAX_THREADS"] = "2"
    if sys.platform == "linux":
        # Keep native arenas inside the address-space budget before loading libraries.
        os.environ["_RJEM_MALLOC_CONF"] = "narenas:2,background_thread:false,retain:false"
        os.environ["ARROW_DEFAULT_MEMORY_POOL"] = "system"
        os.environ["ARROW_IO_THREADS"] = "2"


def dataset_child(path: str, output: str, format: str) -> None:
    # This target must live outside datasets.parser: importing that module first loads
    # native allocators before the child can bound their arena/thread configuration.
    configure_child()
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    try:
        from ontology_platform.datasets.parser import InvalidDataset
        from ontology_platform.datasets.streaming import validate_path

        try:
            result = validate_path(Path(path), format, ExecutionSettings())
        except InvalidDataset as exc:
            result = {"error": "invalid_dataset", "message": str(exc)}
    except Exception:
        result = {
            "error": "invalid_dataset",
            "message": "Content violates format or validation limits",
        }
    Path(output).write_text(json.dumps(result, allow_nan=False))


def child(
    operation: str, request: dict[str, Any], directory: str, limits: ExecutionSettings
) -> None:
    configure_child()
    # Native parser diagnostics can contain private values; only the bounded JSON result leaves.
    sink = os.open(os.devnull, os.O_WRONLY)
    os.dup2(sink, 1)
    os.dup2(sink, 2)
    os.close(sink)
    parent_pid = os.getppid()

    def parent_watch() -> None:
        while True:
            time.sleep(0.5)
            if os.getppid() != parent_pid:
                os._exit(125)  # Only this owned child; never signal another process.

    threading.Thread(target=parent_watch, daemon=True).start()
    scratch = Path(directory) / "scratch"
    scratch.mkdir(mode=0o700, exist_ok=True)
    os.environ["POLARS_TEMP_DIR"] = str(scratch)
    os.environ["TMPDIR"] = str(scratch)
    tempfile.tempdir = str(scratch)
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.temporary_bytes, limits.temporary_bytes))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (limits.address_bytes, limits.address_bytes))
    started = time.monotonic()
    try:
        if operation == "validation":
            from ontology_platform.datasets.streaming import validate_path

            result = validate_path(Path(request["path"]), request["format"], limits)
        elif operation == "function":
            from ontology_platform.functions.engine import execute

            result = execute(request)
        elif operation == "media":
            from ontology_platform.media.parser import extract

            result = extract(request, Path(directory))
        elif operation == "mapping":
            from ontology_platform.mappings.engine import stage

            result = stage(request, Path(directory), limits)
        else:
            from ontology_platform.pipelines.engine import PolarsEngine

            result = PolarsEngine().execute(request, Path(directory), limits)
    except Exception:
        # Native errors may contain source values or local paths.
        result = {"error": "invalid_data_or_plan", "message": "Content or plan violates limits"}
    result["metrics"] = {
        "seconds": time.monotonic() - started,
        "peak_memory_bytes": peak_memory_bytes(),
    }
    Path(directory, "result.json").write_text(json.dumps(result, allow_nan=False))


def isolated(
    operation: str,
    request: dict[str, Any],
    directory: Path,
    limits: ExecutionSettings,
    heartbeat: Callable[[], bool] = lambda: True,
) -> dict[str, Any]:
    if sum(p.stat().st_size for p in directory.rglob("*") if p.is_file()) > limits.temporary_bytes:
        return {"error": "temporary_limit", "message": "Temporary disk budget exhausted"}
    process = multiprocessing.get_context("spawn").Process(
        target=child, args=(operation, request, str(directory), limits)
    )
    process.start()
    deadline, next_heartbeat = time.monotonic() + limits.wall_seconds, time.monotonic()
    reason, peak, disk = "execution_limit", 0, 0
    try:
        while process.is_alive() and time.monotonic() < deadline:
            process.join(0.2)
            if time.monotonic() >= next_heartbeat:
                if not heartbeat():
                    reason = "cancelled"
                    break
                next_heartbeat = time.monotonic() + 2
                disk = max(disk, sum(p.stat().st_size for p in directory.rglob("*") if p.is_file()))
                if disk > limits.temporary_bytes:
                    reason = "temporary_limit"
                    break
                if process.is_alive():
                    # RSS is a development watchdog on Darwin; Linux additionally uses RLIMIT_AS.
                    resident = 0
                    if sys.platform == "linux":
                        try:
                            status = Path(f"/proc/{process.pid}/status").read_text()
                            resident = next(
                                (
                                    int(line.split()[1]) * 1024
                                    for line in status.splitlines()
                                    if line.startswith("VmRSS:")
                                ),
                                0,
                            )
                        except FileNotFoundError:
                            pass  # Child exited between liveness check and proc read.
                    else:
                        usage = subprocess.run(
                            ["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                            capture_output=True,
                            text=True,
                            timeout=1,
                            check=False,
                        )
                        if usage.returncode == 0:
                            resident = int(usage.stdout.strip() or "0") * 1024
                    peak = max(peak, resident)
                    if peak > limits.memory_bytes:
                        reason = "memory_limit"
                        break
    finally:
        if process.is_alive():
            process.kill()
        process.join()
    output = directory / "result.json"
    if process.exitcode != 0 or not output.exists():
        return {"error": reason, "message": "Worker stopped before completion"}
    result: dict[str, Any] = json.loads(output.read_text())
    metrics = result.setdefault("metrics", {})
    metrics["peak_memory_bytes"] = max(metrics.get("peak_memory_bytes", 0), peak)
    metrics["temporary_bytes"] = max(
        disk, sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
    )
    if metrics["peak_memory_bytes"] > limits.memory_bytes:
        return {
            "error": "memory_limit",
            "message": "Worker exceeded memory budget",
            "metrics": metrics,
        }
    return result
