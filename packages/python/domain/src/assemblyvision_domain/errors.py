"""Domain error hierarchy.

Errors are converted to stable reason codes at subsystem boundaries. Raw
exceptions and stack traces belong in structured logs; inspection records
contain only reason codes (see reason_codes.py).
"""

from __future__ import annotations


class AssemblyVisionError(Exception):
    """Base class for all AssemblyVision domain errors."""


class ConfigError(AssemblyVisionError):
    """Raised when configuration, rule, or manifest input is invalid."""


class ImageReadError(AssemblyVisionError):
    """Raised when an image cannot be decoded."""


class DetectionError(AssemblyVisionError):
    """Raised when a detector cannot run or produces invalid output."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ROIGenerationError(AssemblyVisionError):
    """Raised when a valid product ROI cannot be produced."""


class RuleEvaluationError(AssemblyVisionError):
    """Raised when rule evaluation itself fails."""


class OutputError(AssemblyVisionError):
    """Raised when inspection evidence cannot be durably persisted."""
