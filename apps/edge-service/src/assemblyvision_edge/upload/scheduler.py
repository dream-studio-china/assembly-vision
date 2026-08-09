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
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from assemblyvision_domain.models import UploadTask

from assemblyvision_edge.persistence.repository import ClaimedUploadTask, EdgeRepository

log = logging.getLogger("assemblyvision.upload")

# Bound for parsed receipt bodies; a central response larger than this is an
# integrity anomaly and never accepted as a receipt (PR-017 F5).
_MAX_RECEIPT_BYTES = 65536

# Token-bucket burst is capped at one second of tokens so a large backlog
# cannot burst past the configured ceiling (E3a).
_BUCKET_BURST_SECONDS = 1.0
_MBPS_TO_BYTES_PER_SECOND = 1_000_000 / 8


class _TokenBucket:
    """Bounds network upload bytes per second for the scheduler (E3a).

    A ``None`` rate disables throttling entirely. ``acquire`` blocks until
    ``amount`` bytes may be sent at the configured rate; tokens refill
    continuously and burst is capped at one second of tokens. Amounts larger
    than one burst are split into per-burst waits so a large media object can
    never deadlock against the burst cap (PR-022 F01).
    """

    def __init__(self, rate_bytes_per_second: float | None) -> None:
        self._rate = rate_bytes_per_second
        self._tokens = 0.0
        self._last = time.monotonic()

    def acquire(self, amount: int, *, on_wait: Callable[[], None] | None = None) -> None:
        """Block until ``amount`` bytes may be sent at the configured rate.

        ``on_wait`` runs on every refill wake-up; raising from it aborts the
        wait (e.g. worker stop or a lost upload lease, PR-022 F01).
        """
        rate = self._rate
        if rate is None or amount <= 0:
            return
        remaining = float(amount)
        while remaining > 0:
            chunk = min(remaining, rate * _BUCKET_BURST_SECONDS)
            self._wait_for(chunk, rate, on_wait)
            remaining -= chunk

    def _wait_for(self, amount: float, rate: float, on_wait: Callable[[], None] | None) -> None:
        """Sleep until ``amount`` tokens are available, honoring ``on_wait``."""
        while True:
            now = time.monotonic()
            self._tokens = min(
                self._tokens + (now - self._last) * rate,
                rate * _BUCKET_BURST_SECONDS,
            )
            self._last = now
            if self._tokens >= amount:
                self._tokens -= amount
                return
            deficit = amount - self._tokens
            # Wake frequently to refill, renew the lease, and stay responsive
            # to stop signals.
            time.sleep(min(deficit / rate, 0.25))
            if on_wait is not None:
                on_wait()


@dataclass(frozen=True)
class UploadReceipt:
    """Server-confirmed receipt for one uploaded task payload (design 13.3/13.4).

    A task may only become ``SUCCEEDED`` when the central response echoes the
    idempotency key, object identity, kind, byte size, and checksum of the
    payload that was actually sent. The verified receipt and central object
    identifier are persisted so retention can later gate on verified uploads.
    """

    idempotency_key: str
    object_id: str
    kind: str
    checksum_sha256: str | None = None
    size_bytes: int | None = None
    central_object_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class UploadResult:
    """Outcome of one sink attempt, classified for the scheduler.

    ``payload_bytes_sent`` is the serialized request-body bytes actually
    handed to the transport (PR-022 F02); None means no network body was sent
    (transport failure before sending, or a non-network sink).
    """

    status: Literal["SUCCEEDED", "RETRYABLE", "PERMANENT"]
    receipt: UploadReceipt | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = None
    payload_bytes_sent: int | None = None


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
        return UploadResult(
            status="SUCCEEDED",
            receipt=UploadReceipt(
                idempotency_key=task.idempotency_key,
                object_id=str(task.object_id),
                kind=task.kind,
                checksum_sha256=task.checksum_sha256,
                size_bytes=len(payload),
                central_object_id=task.idempotency_key,
            ),
        )


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
        body = self._build_body(task, payload)
        try:
            response = self._client.post(
                f"{self._base_url}/inspection-uploads",
                content=body,
                headers=headers,
            )
        except Exception:  # noqa: BLE001 - any transport failure is retryable
            return UploadResult(status="RETRYABLE", error_code="TRANSPORT_ERROR")
        if 200 <= response.status_code < 300:
            # A 2xx is only a verified success when the receipt matches the
            # task and the payload that was actually sent (PR-017 F5).
            receipt = self._parse_receipt(response, task, len(payload))
            if receipt is None:
                return UploadResult(status="PERMANENT", error_code="INVALID_RECEIPT")
            return UploadResult(status="SUCCEEDED", receipt=receipt, payload_bytes_sent=len(body))
        retry_after: float | None = None
        raw = response.headers.get("Retry-After")
        if raw is not None and raw.isdigit():
            retry_after = float(raw)
        if response.status_code in (408, 429) or response.status_code >= 500:
            return UploadResult(
                status="RETRYABLE",
                error_code=f"HTTP_{response.status_code}",
                retry_after_seconds=retry_after,
                payload_bytes_sent=len(body),
            )
        return UploadResult(
            status="PERMANENT",
            error_code=f"HTTP_{response.status_code}",
            payload_bytes_sent=len(body),
        )

    def wire_size(self, task: UploadTask, payload: bytes) -> int:
        """Serialized request-body bytes for one payload (PR-022 F02).

        The scheduler throttles this count, not the raw source bytes: the
        JSON envelope carries a Base64 payload, so its wire size exceeds the
        media bytes by roughly one third plus metadata.
        """
        return len(self._build_body(task, payload))

    @staticmethod
    def _build_body(task: UploadTask, payload: bytes) -> bytes:
        """Serialize the JSON upload envelope once (PR-022 F02)."""
        body = {
            "idempotency_key": task.idempotency_key,
            "kind": task.kind,
            "object_id": str(task.object_id),
            "inspection_id": str(task.inspection_id) if task.inspection_id else None,
            "checksum_sha256": task.checksum_sha256,
            "size_bytes": len(payload),
            "payload_b64": base64.b64encode(payload).decode("ascii"),
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _parse_receipt(response: Any, task: UploadTask, size_bytes: int) -> UploadReceipt | None:
        """Parse and validate a 2xx receipt against the task and sent payload.

        Returns ``None`` for malformed, oversized, or mismatched responses so
        the task is never marked successful without a verified receipt.
        """
        raw = response.content
        if not raw or len(raw) > _MAX_RECEIPT_BYTES:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            receipt = UploadReceipt(
                idempotency_key=str(data["idempotency_key"]),
                object_id=str(data["object_id"]),
                kind=str(data["kind"]),
                checksum_sha256=data.get("checksum_sha256"),
                size_bytes=data.get("size_bytes"),
                central_object_id=data.get("central_object_id"),
            )
        except (KeyError, TypeError):
            return None
        if (
            receipt.idempotency_key != task.idempotency_key
            or receipt.object_id != str(task.object_id)
            or receipt.kind != task.kind
        ):
            return None
        if receipt.size_bytes != size_bytes:
            return None
        if task.checksum_sha256 is None or receipt.checksum_sha256 != task.checksum_sha256:
            return None
        if task.kind == "MEDIA" and not receipt.central_object_id:
            return None
        return receipt


class _PermanentPayloadError(Exception):
    """Local evidence is missing or corrupt; the task cannot be uploaded."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _ThrottleAborted(Exception):
    """Throttle wait interrupted by worker stop or a lost upload lease.

    The task stays leased (or is reclaimed by the lease-recovery path) and no
    terminal transition is written, so recovery never loses the task
    (PR-022 F01).
    """


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


@dataclass(frozen=True)
class SchedulerHealth:
    """Process-local worker health counters (design 13.9, E1).

    Counters reset on scheduler start; queue truth lives in the repository.
    ``bytes_sent`` and ``bandwidth_mbps`` expose the enforced upload ceiling
    and actual volume for operators (E3a).
    """

    attempts: int
    successes: int
    failures: int
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_error_code: str | None = None
    bytes_sent: int = 0
    bandwidth_mbps: float | None = None
    # Circuit-breaker liveness (design 13.5, E3b): CLOSED / OPEN / HALF_OPEN.
    circuit_state: str = "CLOSED"
    circuit_last_change_at: str | None = None

    @property
    def failure_rate(self) -> float:
        return (self.failures / self.attempts) if self.attempts else 0.0


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
        maximum_bandwidth_mbps: float | None = None,
        circuit_failure_threshold: int = 5,
        circuit_open_seconds: float = 60.0,
        now: Callable[[], datetime] | None = None,
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
        self._bandwidth_mbps = maximum_bandwidth_mbps
        rate = (
            maximum_bandwidth_mbps * _MBPS_TO_BYTES_PER_SECOND
            if maximum_bandwidth_mbps is not None
            else None
        )
        self._bucket = _TokenBucket(rate)
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_open_seconds = circuit_open_seconds
        # Injected clock for deterministic retry-deadline tests (PR-017 F8).
        self._now = now or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Process-local health counters for device status (E1).
        self._health_lock = threading.Lock()
        self._attempts = 0
        self._successes = 0
        self._failures = 0
        self._bytes_sent = 0
        self._last_attempt_at: str | None = None
        self._last_success_at: str | None = None
        self._last_error_code: str | None = None
        # Circuit-breaker state (E3b).
        self._circuit_state = "CLOSED"
        self._circuit_last_change_at: str | None = None
        self._circuit_opened_at: str | None = None
        self._consecutive_failures = 0

    def health(self) -> SchedulerHealth:
        with self._health_lock:
            return SchedulerHealth(
                attempts=self._attempts,
                successes=self._successes,
                failures=self._failures,
                last_attempt_at=self._last_attempt_at,
                last_success_at=self._last_success_at,
                last_error_code=self._last_error_code,
                bytes_sent=self._bytes_sent,
                bandwidth_mbps=self._bandwidth_mbps,
                circuit_state=self._circuit_state,
                circuit_last_change_at=self._circuit_last_change_at,
            )

    def _record_attempt(self, when: str) -> None:
        with self._health_lock:
            self._attempts += 1
            self._last_attempt_at = when

    def _record_bytes(self, amount: int) -> None:
        """Count payload bytes handed to the sink (E3a)."""
        with self._health_lock:
            self._bytes_sent += amount

    def _record_success(self, when: str) -> None:
        with self._health_lock:
            self._successes += 1
            self._last_success_at = when
            self._last_error_code = None

    def _record_failure(self, when: str, code: str) -> None:
        with self._health_lock:
            self._failures += 1
            self._last_error_code = code

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
        """Process one batch; returns the number of tasks handled.

        An open circuit stops all attempts (no hot-looping, E3b); a half-open
        circuit allows exactly one probe task before judging recovery.
        """
        now_iso = self._now().isoformat()
        state = self._effective_circuit_state(now_iso)
        if state == "OPEN":
            return 0
        limit = 1 if state == "HALF_OPEN" else self._batch_size
        claimed = self._repository.claim_upload_tasks(limit, self._lease_seconds, now_iso)
        for item in claimed:
            try:
                self._process(item)
            except Exception:  # noqa: BLE001 - never lose the task over a bug
                log.exception("upload task %s failed unexpectedly", item.task.upload_task_id)
                failure_time = self._now()
                self._record_failure(failure_time.isoformat(), "SCHEDULER_ERROR")
                self._repository.mark_upload_retry(
                    str(item.task.upload_task_id),
                    item.lease_owner,
                    "SCHEDULER_ERROR",
                    (failure_time + timedelta(seconds=self._base_retry_seconds)).isoformat(),
                    failure_time.isoformat(),
                )
        return len(claimed)

    def _effective_circuit_state(self, now_iso: str) -> str:
        """Return the effective circuit state, advancing OPEN -> HALF_OPEN."""
        with self._health_lock:
            if self._circuit_state != "OPEN" or self._circuit_opened_at is None:
                return self._circuit_state
            opened = datetime.fromisoformat(self._circuit_opened_at)
            elapsed = (datetime.fromisoformat(now_iso) - opened).total_seconds()
            if elapsed >= self._circuit_open_seconds:
                self._circuit_state = "HALF_OPEN"
                self._circuit_last_change_at = now_iso
            return self._circuit_state

    def _on_transient_outcome(self, failed: bool, now_iso: str) -> None:
        """Update the circuit from a retryable outcome (E3b).

        Consecutive retryable failures open the circuit; a half-open probe
        success closes it and a probe failure reopens it. Permanent failures
        never count toward the circuit because they are not outage traffic.
        """
        with self._health_lock:
            if not failed:
                self._consecutive_failures = 0
                self._circuit_opened_at = None
                if self._circuit_state == "HALF_OPEN":
                    self._circuit_state = "CLOSED"
                    self._circuit_last_change_at = now_iso
                return
            if self._circuit_state == "CLOSED":
                self._consecutive_failures += 1
                if self._consecutive_failures >= self._circuit_failure_threshold:
                    self._circuit_state = "OPEN"
                    self._circuit_last_change_at = now_iso
                    self._circuit_opened_at = now_iso
                return
            if self._circuit_state == "HALF_OPEN":
                self._circuit_state = "OPEN"
                self._circuit_last_change_at = now_iso
                self._circuit_opened_at = now_iso

    def _lease_guard(self, task_id: str, lease_owner: str) -> Callable[[], None]:
        """Return a throttle-wait callback that aborts on stop or lease loss.

        While a throttled transfer waits, the active upload lease is renewed
        so the claim cannot expire mid-transfer; if the worker stopped or the
        lease was lost (reclaimed by another worker), the wait aborts without
        a terminal transition (PR-022 F01).
        """

        def guard() -> None:
            if self._stop.is_set():
                raise _ThrottleAborted()
            if not self._repository.renew_upload_lease(
                task_id, lease_owner, self._lease_seconds, self._now().isoformat()
            ):
                raise _ThrottleAborted()

        return guard

    def _process(self, claimed: ClaimedUploadTask) -> None:
        task = claimed.task
        lease_owner = claimed.lease_owner
        attempt_time = self._now().isoformat()
        self._record_attempt(attempt_time)
        try:
            payload = self._load_payload(task)
        except _PermanentPayloadError as exc:
            self._record_failure(self._now().isoformat(), exc.code)
            self._repository.mark_upload_permanent_failure(
                str(task.upload_task_id), lease_owner, exc.code, self._now().isoformat()
            )
            return
        # Throttle to the configured ceiling before any network attempt (E3a).
        # The budget covers the serialized request body the HTTP sink will
        # send, not the raw source bytes, and the wait renews the active lease
        # or aborts on stop/lease loss; local persistence is never gated
        # (PR-022 F01/F02).
        wire = (
            self._sink.wire_size(task, payload) if isinstance(self._sink, HttpUploadSink) else None
        )
        if wire is not None:
            try:
                self._bucket.acquire(
                    wire, on_wait=self._lease_guard(str(task.upload_task_id), lease_owner)
                )
            except _ThrottleAborted:
                return
        result = self._sink.upload(task, payload)
        self._record_bytes(
            result.payload_bytes_sent if result.payload_bytes_sent is not None else 0
        )
        # Anchor the transition to the response/failure time, not the batch
        # start, so a slow request cannot erode Retry-After (PR-017 F8).
        outcome_time = self._now()
        now_iso = outcome_time.isoformat()
        if result.status == "SUCCEEDED":
            if result.receipt is None:
                # A sink claiming success without a verified receipt is an
                # integrity violation; never mark the task successful
                # (PR-017 F5).
                self._record_failure(now_iso, "RECEIPT_MISSING")
                self._repository.mark_upload_permanent_failure(
                    str(task.upload_task_id), lease_owner, "RECEIPT_MISSING", now_iso
                )
                return
            self._record_success(now_iso)
            self._on_transient_outcome(False, now_iso)
            self._repository.mark_upload_succeeded(
                str(task.upload_task_id),
                lease_owner,
                now_iso,
                central_object_id=result.receipt.central_object_id,
                receipt_json=result.receipt.to_json(),
            )
            return
        if result.status == "PERMANENT":
            self._record_failure(now_iso, result.error_code or "PERMANENT")
            self._repository.mark_upload_permanent_failure(
                str(task.upload_task_id), lease_owner, result.error_code or "PERMANENT", now_iso
            )
            return
        self._record_failure(now_iso, result.error_code or "RETRYABLE")
        self._on_transient_outcome(True, now_iso)
        backoff = _full_jitter_backoff(
            task.attempt_count,
            base_seconds=self._base_retry_seconds,
            maximum_seconds=self._maximum_retry_seconds,
            exponent_cap=self._exponent_cap,
        )
        retry_after = result.retry_after_seconds or 0.0
        next_attempt = outcome_time + timedelta(seconds=max(backoff, retry_after))
        self._repository.mark_upload_retry(
            str(task.upload_task_id),
            lease_owner,
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
            payload = record.model_dump(mode="json")
            # Mutable synchronization state is not evidence; excluding it keeps
            # the uploaded payload byte-identical to the size recorded at
            # enqueue (PR-020 F12).
            payload.pop("synchronization_status", None)
            return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if task.kind == "MEDIA":
            media = self._repository.get_media(str(task.object_id))
            if media is None:
                raise _PermanentPayloadError("MEDIA_EVIDENCE_MISSING")
            media_metadata, _inspection_id = media
            path = self._output_root / media_metadata.relative_path
            if not path.is_file():
                raise _PermanentPayloadError("MEDIA_EVIDENCE_MISSING")
            data = path.read_bytes()
            if len(data) != media_metadata.size_bytes:
                raise _PermanentPayloadError("MEDIA_SIZE_MISMATCH")
            expected = task.checksum_sha256 or media_metadata.checksum_sha256
            if expected and hashlib.sha256(data).hexdigest() != expected:
                raise _PermanentPayloadError("MEDIA_CHECKSUM_MISMATCH")
            return data
        raise _PermanentPayloadError("UNSUPPORTED_TASK_KIND")
