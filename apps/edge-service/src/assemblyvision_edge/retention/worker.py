"""Receipt-gated retention cleanup worker (design 12.6/12.7, E2 task E2b).

A supervised in-process worker, separate from the upload scheduler, drains
reconciled retention candidates: it claims an artifact under an inter-process
SQLite lease with a per-artifact fencing token, resolves and revalidates the
trusted media path, unlinks the file, verifies absence, and only then finalizes
the artifact as ``PURGED`` (an audit tombstone). Missing files are integrity
faults, never successful deletions; unlink failures are retryable and
observable. Without an approved retention policy the worker performs no
filesystem mutation at all.
"""

from __future__ import annotations

import errno
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from assemblyvision_edge.persistence.reconcile import media_path_is_safe
from assemblyvision_edge.persistence.repository import (
    ClaimedRetentionTarget,
    EdgeRepository,
)
from assemblyvision_edge.retention.policy import RetentionPolicy

log = logging.getLogger("assemblyvision.retention")


@dataclass(frozen=True)
class CleanupHealth:
    """Process-local cleanup worker health (E2b).

    Counters reset on worker start; the durable cleanup state lives in the
    repository (:class:`RetentionMetrics`).
    """

    runs: int
    purged_count: int
    reclaimed_bytes: int
    failure_count: int
    last_run_at: str | None = None
    last_error_code: str | None = None


class RetentionCleanupWorker:
    """Background worker that deletes only receipt-verified, hold-elapsed media."""

    def __init__(
        self,
        repository: EdgeRepository,
        output_root: Path,
        policy: RetentionPolicy | None,
        *,
        interval_seconds: float = 60.0,
        batch_size: int = 16,
        lease_seconds: int = 300,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._output_root = output_root
        self._policy = policy
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._health_lock = threading.Lock()
        self._runs = 0
        self._purged = 0
        self._reclaimed_bytes = 0
        self._failures = 0
        self._last_run_at: str | None = None
        self._last_error_code: str | None = None

    @property
    def enabled(self) -> bool:
        """Cleanup runs only under an explicitly approved retention policy."""
        return self._policy is not None

    def health(self) -> CleanupHealth:
        with self._health_lock:
            return CleanupHealth(
                runs=self._runs,
                purged_count=self._purged,
                reclaimed_bytes=self._reclaimed_bytes,
                failure_count=self._failures,
                last_run_at=self._last_run_at,
                last_error_code=self._last_error_code,
            )

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="retention-cleanup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - one bad cycle must not kill the worker
                log.exception("retention cleanup cycle failed")
            self._stop.wait(self._interval_seconds)

    def run_once(self) -> int:
        """Process one batch of claimed candidates; returns the number handled.

        When no approved policy is configured the worker is inert and never
        touches the filesystem (E2 task E2b exit criteria).
        """
        if not self.enabled:
            return 0
        now_iso = self._now().isoformat()
        with self._health_lock:
            self._runs += 1
            self._last_run_at = now_iso
        claimed = self._repository.claim_retention_batch(
            self._batch_size, self._lease_seconds, now_iso
        )
        handled = 0
        for target in claimed:
            try:
                if self._process(target, now_iso):
                    handled += 1
            except Exception:  # noqa: BLE001 - never lose a claim over a bug
                log.exception("cleanup failed unexpectedly for media %s", target.media_id)
                self._record_failure("SCHEDULER_ERROR")
                self._repository.record_media_delete_failure(
                    str(target.media_id), target.lease_owner, "SCHEDULER_ERROR", now_iso
                )
        return handled

    def _process(self, target: ClaimedRetentionTarget, now_iso: str) -> bool:
        """Unlink one claimed artifact and finalize it; False on retryable failure."""
        path = self._resolve_path(target)
        if path is None:
            self._record_failure("MEDIA_PATH_UNSAFE")
            # An unsafe path is an integrity anomaly, not a retryable unlink.
            self._repository.mark_media_integrity_fault(
                str(target.media_id), target.lease_owner, "MEDIA_PATH_UNSAFE", now_iso
            )
            return False
        if not path.is_file():
            # Missing evidence is an integrity fault, never a successful purge
            # (E2 task invariant 4/8, E2b exit criteria).
            self._record_failure("MEDIA_EVIDENCE_MISSING")
            self._repository.mark_media_integrity_fault(
                str(target.media_id), target.lease_owner, "MEDIA_EVIDENCE_MISSING", now_iso
            )
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            self._record_failure("MEDIA_EVIDENCE_MISSING")
            self._repository.mark_media_integrity_fault(
                str(target.media_id), target.lease_owner, "MEDIA_EVIDENCE_MISSING", now_iso
            )
            return False
        except OSError as exc:
            code = _unlink_error_code(exc)
            self._record_failure(code)
            self._repository.record_media_delete_failure(
                str(target.media_id), target.lease_owner, code, now_iso
            )
            return False
        if path.exists():
            self._record_failure("UNLINK_VERIFY_FAILED")
            self._repository.record_media_delete_failure(
                str(target.media_id), target.lease_owner, "UNLINK_VERIFY_FAILED", now_iso
            )
            return False
        # The file is gone: finalize the audit tombstone. A lost lease here
        # means another worker owns the artifact; we must not overwrite it.
        finalized = self._repository.finalize_media_purge(
            str(target.media_id), target.lease_owner, now_iso, "retention"
        )
        if finalized == 0:
            self._record_failure("LEASE_LOST")
            return False
        with self._health_lock:
            self._purged += 1
            self._reclaimed_bytes += target.size_bytes
        log.info(
            "retention cleanup purged media %s (%d bytes)",
            target.media_id,
            target.size_bytes,
        )
        return True

    def _resolve_path(self, target: ClaimedRetentionTarget) -> Path | None:
        """Return the trusted media path or None when it escapes its bundle.

        SQLite metadata is never authorization to remove an arbitrary path; the
        path must resolve inside the artifact's own inspection bundle inside the
        configured output root (E2 task invariant 9).
        """
        if not media_path_is_safe(
            self._output_root, str(target.inspection_id), target.relative_path
        ):
            return None
        path = self._output_root / target.relative_path
        try:
            resolved = path.resolve()
        except OSError:
            return None
        root = self._output_root.resolve()
        if not resolved.is_relative_to(root):
            return None
        return path

    def _record_failure(self, code: str) -> None:
        with self._health_lock:
            self._failures += 1
            self._last_error_code = code


def _unlink_error_code(exc: OSError) -> str:
    """Map a filesystem error to a stable, log-safe error code."""
    if exc.errno in (errno.EACCES, errno.EPERM):
        return "EACCES"
    if exc.errno == errno.EROFS:
        return "EROFS"
    if exc.errno == errno.ENOSPC:
        return "ENOSPC"
    if exc.errno in (errno.EISDIR,):
        return "EISDIR"
    return "UNLINK_FAILED"


def cleanup_path_is_safe(output_root: Path, target: ClaimedRetentionTarget) -> bool:
    """Public predicate mirroring the worker's path containment check (tests)."""
    return media_path_is_safe(output_root, str(target.inspection_id), target.relative_path)
