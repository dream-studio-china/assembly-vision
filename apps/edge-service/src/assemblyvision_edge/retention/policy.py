"""Retention policy for local media (design 12.7, E2 task).

A policy maps each media kind to a minimum local hold duration. Media kinds
absent from the policy (or an entirely absent policy) are never eligible for
deletion, which is the production-safe default: cleanup can run only after an
approved retention policy is configured (E2 task sections 3/4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class RetentionPolicy:
    """Approved minimum local hold durations by media kind.

    ``durations`` maps :class:`MediaMetadata.kind` values (``KEY_FRAME``,
    ``ANNOTATED_FRAME``, ``PRODUCT_ROI``, ``NG_CLIP``, ``ROLLING_VIDEO``) to
    their minimum local hold before receipt-gated deletion may run. Kinds
    without an entry are protected forever.
    """

    durations: dict[str, timedelta] = field(default_factory=dict)

    def eligible_at(self, kind: str, created_at: datetime) -> datetime | None:
        """Return the earliest UTC deletion time, or None when never eligible."""
        duration = self.durations.get(kind)
        if duration is None:
            return None
        return created_at + duration
