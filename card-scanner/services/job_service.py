"""SimpleJobService: an in-process ThreadPoolExecutor (default 1 worker) so heavy
OCR/matching/provider work stays out of the Flask request thread without adding
Redis/Celery. A hard per-task timeout prevents a hung scan from wedging clients.
"""
from __future__ import annotations

import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import Lock
from typing import Any, Callable, Dict, Optional

from utils.logger import get_logger

log = get_logger("jobs")


class SimpleJobService:
    def __init__(self, workers: int = 1, task_timeout_sec: float = 30.0):
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers))
        self._timeout = task_timeout_sec
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = Lock()

    def submit(self, fn: Callable[..., Any], *args, **kwargs) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {"job_id": job_id, "status": "queued", "result": None, "error": None}
        fut = self._pool.submit(self._run, job_id, fn, *args, **kwargs)
        with self._lock:
            self._futures[job_id] = fut
        return job_id

    def _run(self, job_id: str, fn, *args, **kwargs):
        with self._lock:
            self._jobs[job_id]["status"] = "running"
        try:
            result = fn(*args, **kwargs)
            with self._lock:
                self._jobs[job_id].update(status="finished", result=result)
            return result
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            with self._lock:
                self._jobs[job_id].update(status="failed", error=str(exc))
            raise

    def run_blocking(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        """Submit and wait up to the task timeout for the result."""
        job_id = self.submit(fn, *args, **kwargs)
        fut = self._futures[job_id]
        try:
            return fut.result(timeout=self._timeout)
        except FutureTimeout:
            with self._lock:
                self._jobs[job_id].update(status="failed", error="timeout")
            raise TimeoutError("scan task timed out")

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
