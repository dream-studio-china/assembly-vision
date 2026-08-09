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

import contextlib
import errno
import logging
import os
import stat
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
        """Unlink one claimed artifact and finalize it; False on retryable failure.

        The fenced pre-unlink confirmation (PR-020 F02/F03) re-validates the
        full eligibility predicate and renews the lease immediately before any
        destructive I/O, so an expired holder or a hold/fault applied after the
        claim cannot delete evidence. Unlink runs through trusted directory
        file descriptors with no-follow semantics (PR-020 F04).
        """
        confirmed = self._repository.confirm_retention_claim(
            str(target.media_id), target.lease_owner, now_iso, self._lease_seconds
        )
        if confirmed is None:
            self._record_failure("CLAIM_INVALID")
            return False
        target = confirmed
        code, is_fault = unlink_media_safely(self._output_root, target)
        if code is not None:
            self._record_failure(code)
            if is_fault:
                self._repository.mark_media_integrity_fault(
                    str(target.media_id), target.lease_owner, code, now_iso
                )
            else:
                self._repository.record_media_delete_failure(
                    str(target.media_id), target.lease_owner, code, now_iso
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

    def _record_failure(self, code: str) -> None:
        with self._health_lock:
            self._failures += 1
            self._last_error_code = code


def unlink_media_safely(
    output_root: Path, target: ClaimedRetentionTarget
) -> tuple[str | None, bool]:
    """Unlink one media file through trusted directory fds (PR-020 F04).

    Returns ``(None, False)`` on success, ``(code, is_fault)`` on failure
    where ``is_fault`` marks a non-retryable integrity anomaly (unsafe path,
    missing evidence) and False marks a retryable unlink failure.

    Traversal and the final unlink are performed relative to directory file
    descriptors opened with ``O_NOFOLLOW``, so a concurrent symlink swap of an
    intermediate bundle directory cannot redirect deletion outside the trusted
    inspection bundle (E2 task invariant 9).
    """
    if not media_path_is_safe(output_root, str(target.inspection_id), target.relative_path):
        return "MEDIA_PATH_UNSAFE", True
    parts = Path(target.relative_path).parts
    if len(parts) < 2 or parts[0] != str(target.inspection_id):
        return "MEDIA_PATH_UNSAFE", True
    fds: list[int] = []
    try:
        try:
            fds.append(os.open(output_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        except OSError:
            return "MEDIA_PATH_UNSAFE", True
        try:
            fds.append(
                os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1])
            )
        except OSError:
            # The inspection bundle directory is missing: evidence is gone.
            return "MEDIA_EVIDENCE_MISSING", True
        for component in parts[1:-1]:
            try:
                fds.append(
                    os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1])
                )
            except OSError:
                return "MEDIA_PATH_UNSAFE", True
        parent_fd = fds[-1]
        name = parts[-1]
        try:
            st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return "MEDIA_EVIDENCE_MISSING", True
        except OSError:
            return "MEDIA_PATH_UNSAFE", True
        if not stat.S_ISREG(st.st_mode):
            # A directory or symlink at the final component is unsafe.
            return "MEDIA_PATH_UNSAFE", True
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError:
            return "MEDIA_EVIDENCE_MISSING", True
        except OSError as exc:
            return _unlink_error_code(exc), False
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            return "UNLINK_VERIFY_FAILED", False
        except FileNotFoundError:
            return None, False
    finally:
        for fd in reversed(fds):
            with contextlib.suppress(OSError):
                os.close(fd)


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
