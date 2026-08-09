"""Upload sinks and the persistent upload scheduler (design 13, ADR-005).

The scheduler consumes the transactional upload outbox created by
``EdgeRepository.enqueue_inspection_uploads``: it leases due tasks, hands each
payload to an :class:`UploadSink`, and records the outcome durably. Retryable
failures schedule exponential backoff with full jitter (design 13.5); permanent
failures (missing local media, checksum mismatch, server idempotency conflict)
preserve local evidence and stop retrying.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from assemblyvision_domain.models import UploadTask

from assemblyvision_edge.persistence.repository import EdgeRepository

log = logging.getLogger("assemblyvision.upload")


@dataclass(frozen=True)
class UploadResult:
    """Outcome of one sink attempt, classified for the scheduler."""

    status: Literal["SUCCEEDED", "RETRYABLE", "PERMANENT"]
    receipt: str | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = None


class UploadSink(Protocol):
    """Sends one upload task payload to the central endpoint."""

    def upload(self, task: UploadTask, payload: bytes) -> UploadResult: ...


class DirectoryUploadSink:
    """Development/local sink that writes each payload to a directory.

    Used when no central endpoint is configured and in tests: the receipt is
    the idempotency key, so replays write the same file and are idempotent.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def upload(self, task: UploadTask, payload: bytes) -> UploadResult:
        target = self._root / task.kind.lower() / f"{task.idempotency_key}.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{threading.get_ident()}.tmp")
        try:
            tmp.write_bytes(payload)
            tmp.rename(target)
        except OSError:
            tmp.unlink(missing_ok=True)
            return UploadResult(status="PERMANENT", error_code="SINK_WRITE_FAILED")
        return UploadResult(status="SUCCEEDED", receipt=task.idempotency_key)


class HttpUploadSink:
    """POSTs each payload to ``{base_url}/inspection-uploads`` with httpx.

    Classifies outcomes per design 13.9: 2xx succeeds, 408/429/5xx and network
    errors are retryable, other 4xx (including 409 content conflicts) are
    permanent. A numeric ``Retry-After`` header bounds the next attempt. A
    custom ``client`` may be injected for tests.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        connect_timeout_seconds: float = 5.0,
        request_timeout_seconds: float = 30.0,
        client: Any = None,
    ) -> None:
        import httpx

        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(request_timeout_seconds, connect=connect_timeout_seconds)
        )

    def upload(self, task: UploadTask, payload: bytes) -> UploadResult:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        body = {
            "idempotency_key": task.idempotency_key,
            "kind": task.kind,
            "object_id": str(task.object_id),
            "inspection_id": str(task.inspection_id) if task.inspection_id else None,
            "checksum_sha256": task.checksum_sha256,
            "size_bytes": len(payload),
            "payload_b64": base64.b64encode(payload).decode("ascii"),
        }
        try:
            response = self._client.post(
                f"{self._base_url}/inspection-uploads",
                json=body,
                headers=headers,
            )
        except Exception:  # noqa: BLE001 - any transport failure is retryable
            return UploadResult(status="RETRYABLE", error_code="TRANSPORT_ERROR")
        if 200 <= response.status_code < 300:
            return UploadResult(status="SUCCEEDED", receipt=response.text or task.idempotency_key)
        retry_after: float | None = None
        raw = response.headers.get("Retry-After")
        if raw is not None and raw.isdigit():
            retry_after = float(raw)
        if response.status_code in (408, 429) or response.status_code >= 500:
            return UploadResult(
                status="RETRYABLE",
                error_code=f"HTTP_{response.status_code}",
                retry_after_seconds=retry_after,
            )
        return UploadResult(status="PERMANENT", error_code=f"HTTP_{response.status_code}")


class _PermanentPayloadError(Exception):
    """Local evidence is missing or corrupt; the task cannot be uploaded."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _full_jitter_backoff(
    attempt: int,
    *,
    base_seconds: float,
    maximum_seconds: float,
    exponent_cap: int,
) -> float:
    """Design 13.5: ``random(0, min(max, base * 2 ** min(attempt, cap)))``."""
    exponent = min(attempt, exponent_cap)
    # int ** int is typed Any by typeshed (overflow to float), so convert the
    # factor to float before mixing it into the bound computation.
    upper = min(maximum_seconds, base_seconds * float(2**exponent))
    # Jitter is a scheduling delay, not a security primitive (design 13.5).
    jitter: float = random.random()  # noqa: S311
    return jitter * upper


class UploadScheduler:
    """Background worker that drains the upload outbox (design 13.4)."""

    def __init__(
        self,
        repository: EdgeRepository,
        sink: UploadSink,
        *,
        output_root: Path,
        interval_seconds: float = 1.0,
        batch_size: int = 4,
        lease_seconds: int = 120,
        base_retry_seconds: float = 2.0,
        maximum_retry_seconds: float = 900.0,
        exponent_cap: int = 8,
    ) -> None:
        self._repository = repository
        self._sink = sink
        self._output_root = output_root
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._base_retry_seconds = base_retry_seconds
        self._maximum_retry_seconds = maximum_retry_seconds
        self._exponent_cap = exponent_cap
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="upload-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - one bad batch must not kill the worker
                log.exception("upload scheduler batch failed")
            self._stop.wait(self._interval_seconds)

    def run_once(self) -> int:
        """Process one batch; returns the number of tasks handled."""
        now = datetime.now(UTC)
        tasks = self._repository.claim_upload_tasks(
            self._batch_size, self._lease_seconds, now.isoformat()
        )
        for task in tasks:
            try:
                self._process(task, now)
            except Exception:  # noqa: BLE001 - never lose the task over a bug
                log.exception("upload task %s failed unexpectedly", task.upload_task_id)
                self._repository.mark_upload_retry(
                    str(task.upload_task_id),
                    "SCHEDULER_ERROR",
                    (now + timedelta(seconds=self._base_retry_seconds)).isoformat(),
                    datetime.now(UTC).isoformat(),
                )
        return len(tasks)

    def _process(self, task: UploadTask, now: datetime) -> None:
        try:
            payload = self._load_payload(task)
        except _PermanentPayloadError as exc:
            self._repository.mark_upload_permanent_failure(
                str(task.upload_task_id), exc.code, datetime.now(UTC).isoformat()
            )
            return
        result = self._sink.upload(task, payload)
        now_iso = datetime.now(UTC).isoformat()
        if result.status == "SUCCEEDED":
            self._repository.mark_upload_succeeded(str(task.upload_task_id), now_iso)
            return
        if result.status == "PERMANENT":
            self._repository.mark_upload_permanent_failure(
                str(task.upload_task_id), result.error_code or "PERMANENT", now_iso
            )
            return
        backoff = _full_jitter_backoff(
            task.attempt_count,
            base_seconds=self._base_retry_seconds,
            maximum_seconds=self._maximum_retry_seconds,
            exponent_cap=self._exponent_cap,
        )
        retry_after = result.retry_after_seconds or 0.0
        next_attempt = now + timedelta(seconds=max(backoff, retry_after))
        self._repository.mark_upload_retry(
            str(task.upload_task_id),
            result.error_code or "RETRYABLE",
            next_attempt.isoformat(),
            now_iso,
        )

    def _load_payload(self, task: UploadTask) -> bytes:
        """Load the immutable payload for one task from local evidence.

        Raises :class:`_PermanentPayloadError` when the local evidence is
        missing or fails its checksum so the task is marked permanently failed
        (design 13.9) instead of retrying forever.
        """
        if task.kind == "INSPECTION":
            if task.inspection_id is None:
                raise _PermanentPayloadError("INSPECTION_EVIDENCE_MISSING")
            record = self._repository.get_inspection_full(str(task.inspection_id))
            if record is None:
                raise _PermanentPayloadError("INSPECTION_EVIDENCE_MISSING")
            payload = json.dumps(
                record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            )
            return payload.encode("utf-8")
        if task.kind == "MEDIA":
            media = self._repository.get_media(str(task.object_id))
            if media is None:
                raise _PermanentPayloadError("MEDIA_EVIDENCE_MISSING")
            media_metadata, _inspection_id = media
            path = self._output_root / media_metadata.relative_path
            if not path.is_file():
                raise _PermanentPayloadError("MEDIA_EVIDENCE_MISSING")
            data = path.read_bytes()
            expected = task.checksum_sha256 or media_metadata.checksum_sha256
            if expected and hashlib.sha256(data).hexdigest() != expected:
                raise _PermanentPayloadError("MEDIA_CHECKSUM_MISMATCH")
            return data
        raise _PermanentPayloadError("UNSUPPORTED_TASK_KIND")
