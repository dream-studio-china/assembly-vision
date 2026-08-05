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

from assemblyvision_domain.errors import AssemblyVisionError
from assemblyvision_domain.models import BusinessResult, InspectionRecord
from assemblyvision_vision.sources.folder_source import FolderSource

from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.pipeline import InspectionPipeline

log = logging.getLogger("assemblyvision.verify")


@dataclass(frozen=True)
class ExpectedResult:
    """Expected outcome for one held-out image."""

    ok: bool
    present: frozenset[str] = frozenset()
    missing: frozenset[str] = frozenset()


def load_expected(path: Path) -> dict[str, ExpectedResult]:
    """Load the expected-labels JSON file keyed by filename."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read expected labels {path}: {exc}") from exc
    expected: dict[str, ExpectedResult] = {}
    for name, info in raw.items():
        if not isinstance(info, dict):
            continue
        ok = bool(info.get("ok", False))
        present = frozenset(str(c) for c in info.get("present", []))
        missing = frozenset(str(c) for c in info.get("missing", []))
        expected[name] = ExpectedResult(ok=ok, present=present, missing=missing)
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


def run_verify(
    pipeline: InspectionPipeline,
    work: list[tuple[FolderSource, Path]],
    expected: dict[str, ExpectedResult],
    writer: OutputWriter,
    filename_fallback: bool = True,
) -> VerificationReport:
    rows: list[VerifyRow] = []
    for source, path in work:
        exp = expected.get(path.name)
        if exp is None and filename_fallback:
            exp = filename_expected(path.name)
        if exp is None:
            continue
        try:
            record = pipeline.inspect_image(source, path, writer)
        except AssemblyVisionError as exc:
            log.error("verify failed for %s: %s", path, exc)
            continue
        predicted_ok = record.decision.business_result is BusinessResult.OK
        rows.append(VerifyRow(str(path), exp.ok, predicted_ok, record))
    return VerificationReport(rows)


def format_report(report: VerificationReport) -> str:
    lines = [
        "=== Verification report ===",
        f"total            : {len(report.rows)}",
        f"expected OK      : {report.expected_ok}",
        f"expected NG      : {report.expected_ng}",
        f"matched          : {report.matched}/{len(report.rows)}",
        f"NG recall        : {report.ng_recall:.3f} ({report.true_positive_ng}/{report.expected_ng})",
        f"false negatives  : {report.false_negative}  (FN rate {report.fn_rate:.3f})",
        f"false positives  : {report.false_positive}  (FP rate {report.fp_rate:.3f})",
    ]
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
        reasons = ",".join(r.record.decision.reason_codes) if r.record and not r.predicted_ok else "-"
        lines.append(f"{r.image}\texpected={exp}\tpredicted={pred}\t{match}\t{reasons}")
    return "\n".join(lines)
