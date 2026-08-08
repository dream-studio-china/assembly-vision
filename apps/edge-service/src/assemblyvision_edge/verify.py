"""Held-out verification: compare inspection decisions with expected labels.

The expected labels file mirrors ``test-expected.json`` produced by
scripts/adapt-roboflow-dataset.py:

    {"img016.png": {"ok": false, "present": [...], "missing": ["chip"]}, ...}

When no expected file is supplied, a filename fallback treats names containing
``ok`` as OK and ``ng`` as NG.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.errors import AssemblyVisionError
from assemblyvision_domain.models import BusinessResult, InspectionRecord
from assemblyvision_vision.sources.folder_source import FolderSource

from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.pipeline import InspectionPipeline

log = logging.getLogger("assemblyvision.verify")

_UNEVALUABLE_REASON_CODES = frozenset(
    {
        rc.IMAGE_READ_ERROR,
        rc.INFERENCE_ERROR,
        rc.ROI_INVALID,
        rc.RULE_EVALUATION_ERROR,
        rc.CONFIG_INVALID,
        rc.VERSION_INCOMPATIBLE,
    }
)


@dataclass(frozen=True)
class ExpectedResult:
    """Expected outcome for one held-out image."""

    ok: bool
    present: frozenset[str] = frozenset()
    missing: frozenset[str] = frozenset()


def load_expected(path: Path) -> dict[str, ExpectedResult]:
    """Load the expected-labels JSON file keyed by filename.

    Entries are validated strictly so a missing or malformed expected label
    cannot be silently coerced into a more permissive outcome.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read expected labels {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"expected labels file {path} must contain an object")
    expected: dict[str, ExpectedResult] = {}
    for name, info in raw.items():
        if not isinstance(info, dict):
            raise ValueError(f"expected label for {name!r} must be an object")
        ok = info.get("ok")
        if not isinstance(ok, bool):
            raise ValueError(f"expected label for {name!r} must include a boolean 'ok'")
        present = info.get("present", [])
        missing = info.get("missing", [])
        if not isinstance(present, list) or not isinstance(missing, list):
            raise ValueError(f"expected label for {name!r} must have list 'present' and 'missing'")
        expected[name] = ExpectedResult(
            ok=ok,
            present=frozenset(str(c) for c in present),
            missing=frozenset(str(c) for c in missing),
        )
    return expected


def filename_expected(name: str) -> ExpectedResult | None:
    """Fallback: infer expected outcome from the filename.

    Tokenizes on non-alphanumeric boundaries so extensions like ``.png``
    cannot be misread as ``ng``.
    """
    import re

    tokens = {t for t in re.split(r"[^a-zA-Z0-9]+", name.lower()) if t}
    if "ng" in tokens or "missing" in tokens:
        return ExpectedResult(ok=False)
    if "ok" in tokens:
        return ExpectedResult(ok=True)
    return None


@dataclass
class VerifyRow:
    """One image's expected vs predicted outcome."""

    image: str
    expected_ok: bool
    predicted_ok: bool
    record: InspectionRecord | None = None


@dataclass
class VerificationReport:
    rows: list[VerifyRow] = field(default_factory=list)
    unlabeled: int = 0
    failed: int = 0
    unmatched_expected: int = 0

    @property
    def has_gaps(self) -> bool:
        """True when the report cannot be trusted to represent the expected set."""
        return (
            self.unlabeled > 0
            or self.failed > 0
            or self.unmatched_expected > 0
            or len(self.rows) == 0
        )

    @property
    def expected_ng(self) -> int:
        return sum(1 for r in self.rows if not r.expected_ok)

    @property
    def expected_ok(self) -> int:
        return sum(1 for r in self.rows if r.expected_ok)

    @property
    def true_positive_ng(self) -> int:
        return sum(1 for r in self.rows if not r.expected_ok and not r.predicted_ok)

    @property
    def false_negative(self) -> int:
        return sum(1 for r in self.rows if not r.expected_ok and r.predicted_ok)

    @property
    def false_positive(self) -> int:
        return sum(1 for r in self.rows if r.expected_ok and not r.predicted_ok)

    @property
    def matched(self) -> int:
        return sum(1 for r in self.rows if r.expected_ok == r.predicted_ok)

    @property
    def ng_recall(self) -> float:
        if self.expected_ng == 0:
            return 0.0
        return self.true_positive_ng / self.expected_ng

    @property
    def fn_rate(self) -> float:
        if self.expected_ng == 0:
            return 0.0
        return self.false_negative / self.expected_ng

    @property
    def fp_rate(self) -> float:
        if self.expected_ok == 0:
            return 0.0
        return self.false_positive / self.expected_ok


def _is_evaluable(record: InspectionRecord) -> bool:
    """Return whether a record is valid evidence for held-out scoring.

    A fail-safe NG caused by unreadable input, invalid inference, or uncertain
    evidence is not a true positive for a missing-component test case.
    """
    if not record.evidence:
        return False
    if any(reason in _UNEVALUABLE_REASON_CODES for reason in record.decision.reason_codes):
        return False
    return all(evidence.state != "UNCERTAIN" for evidence in record.evidence)


def run_verify(
    pipeline: InspectionPipeline,
    work: list[tuple[FolderSource, Path]],
    expected: dict[str, ExpectedResult],
    writer: OutputWriter,
    filename_fallback: bool = True,
) -> VerificationReport:
    rows: list[VerifyRow] = []
    unlabeled = 0
    failed = 0
    seen: set[str] = set()
    for source, path in work:
        name = path.name
        if name in seen:
            failed += 1
            log.error("verify rejected duplicate work identity %s", name)
            continue
        exp = expected.get(name)
        if exp is None and filename_fallback:
            exp = filename_expected(name)
        if exp is None:
            unlabeled += 1
            continue
        seen.add(name)
        try:
            record = pipeline.inspect_image(source, path, writer)
        except AssemblyVisionError as exc:
            failed += 1
            log.error("verify failed for %s: %s", path, exc)
            continue
        if not _is_evaluable(record):
            failed += 1
            log.error("verify cannot score incomplete inspection evidence for %s", path)
            continue
        predicted_ok = record.decision.business_result is BusinessResult.OK
        rows.append(VerifyRow(str(path), exp.ok, predicted_ok, record))
    unmatched_expected = len(set(expected) - seen)
    return VerificationReport(
        rows=rows,
        unlabeled=unlabeled,
        failed=failed,
        unmatched_expected=unmatched_expected,
    )


def format_report(report: VerificationReport) -> str:
    lines = [
        "=== Verification report ===",
        f"total            : {len(report.rows)}",
        f"expected OK      : {report.expected_ok}",
        f"expected NG      : {report.expected_ng}",
        f"unlabeled        : {report.unlabeled}",
        f"failed           : {report.failed}",
        f"unmatched expect.: {report.unmatched_expected}",
        f"matched          : {report.matched}/{len(report.rows)}",
        f"NG recall        : {report.ng_recall:.3f} ({report.true_positive_ng}/{report.expected_ng})",
        f"false negatives  : {report.false_negative}  (FN rate {report.fn_rate:.3f})",
        f"false positives  : {report.false_positive}  (FP rate {report.fp_rate:.3f})",
    ]
    if report.has_gaps:
        lines.append("")
        lines.append(
            "DANGER: verification did not cover the full expected set (see unlabeled/failed/unmatched)."
        )
    fns = [r for r in report.rows if not r.expected_ok and r.predicted_ok]
    if fns:
        lines.append("")
        lines.append("DANGER: NG predicted as OK (false negatives):")
        for r in fns:
            lines.append(f"  - {r.image}")
    return "\n".join(lines)


def format_per_image(report: VerificationReport) -> str:
    lines = []
    for r in report.rows:
        match = "match" if r.expected_ok == r.predicted_ok else "MISMATCH"
        exp = "OK" if r.expected_ok else "NG"
        pred = "OK" if r.predicted_ok else "NG"
        reasons = (
            ",".join(r.record.decision.reason_codes) if r.record and not r.predicted_ok else "-"
        )
        lines.append(f"{r.image}\texpected={exp}\tpredicted={pred}\t{match}\t{reasons}")
    return "\n".join(lines)
