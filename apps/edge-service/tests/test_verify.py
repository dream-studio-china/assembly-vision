"""Tests for the verify command metrics and expected-label parsing."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.errors import AssemblyVisionError
from assemblyvision_domain.models import BusinessResult
from assemblyvision_edge.verify import (
    ExpectedResult,
    VerificationReport,
    VerifyRow,
    filename_expected,
    format_report,
    load_expected,
    run_verify,
)


def _row(expected_ok: bool, predicted_ok: bool) -> VerifyRow:
    return VerifyRow(image="x.png", expected_ok=expected_ok, predicted_ok=predicted_ok)


def test_metrics_all_matched() -> None:
    report = VerificationReport(
        rows=[_row(True, True), _row(True, True), _row(False, False), _row(False, False)]
    )
    assert report.ng_recall == pytest.approx(1.0)
    assert report.false_negative == 0
    assert report.false_positive == 0
    assert report.matched == 4


def test_metrics_with_false_negative() -> None:
    report = VerificationReport(rows=[_row(True, True), _row(False, False), _row(False, True)])
    assert report.false_negative == 1
    assert report.ng_recall == pytest.approx(0.5)
    assert report.fn_rate == pytest.approx(0.5)
    assert "DANGER" in format_report(report)


def test_metrics_with_false_positive() -> None:
    report = VerificationReport(rows=[_row(True, True), _row(True, False)])
    assert report.false_positive == 1
    assert report.fp_rate == pytest.approx(0.5)


def test_load_expected_parses_file(tmp_path: Path) -> None:
    expected = {
        "img016.png": {"ok": False, "present": ["boot"], "missing": ["chip"]},
        "img017.png": {"ok": True, "present": ["chip", "boot"], "missing": []},
    }
    path = tmp_path / "test-expected.json"
    path.write_text(json.dumps(expected), encoding="utf-8")
    loaded = load_expected(path)
    assert loaded["img016.png"].ok is False
    assert loaded["img016.png"].missing == frozenset({"chip"})
    assert loaded["img017.png"].ok is True


def test_load_expected_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_expected(tmp_path / "nope.json")


def test_load_expected_rejects_malformed_entries(tmp_path: Path) -> None:
    path = tmp_path / "bad-expected.json"
    path.write_text(json.dumps({"a.png": {"ok": "yes"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="boolean 'ok'"):
        load_expected(path)
    path.write_text(json.dumps({"a.png": "ng"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        load_expected(path)
    path.write_text(json.dumps({"a.png": {"ok": True, "present": "x"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="list 'present'"):
        load_expected(path)


def test_filename_expected() -> None:
    assert filename_expected("ok_001.png").ok is True  # type: ignore[union-attr]
    assert filename_expected("ng_missing_001.png").ok is False  # type: ignore[union-attr]
    assert filename_expected("plain.png") is None


def test_report_ignores_unlabeled_images() -> None:
    report = VerificationReport(rows=[])
    assert report.matched == 0
    assert report.ng_recall == 0.0
    assert report.has_gaps is True


class _FakePipeline:
    def __init__(
        self,
        failures: set[str],
        incomplete: set[str] | None = None,
        failure_reasons: set[str] | None = None,
    ) -> None:
        self._failures = failures
        self._incomplete = incomplete or set()
        self._failure_reasons = failure_reasons or set()

    def inspect_image(self, source: object, path: Path, writer: object) -> object:
        if path.name in self._failures:
            raise AssemblyVisionError("boom")
        if path.name in self._incomplete:
            return _FakeRecord(BusinessResult.NG, evidence_state="UNCERTAIN")
        if path.name in self._failure_reasons:
            return _FakeRecord(BusinessResult.NG, reason_codes=[rc.INFERENCE_ERROR])
        return _FakeRecord(BusinessResult.OK)


class _FakeRecord:
    def __init__(
        self,
        business_result: BusinessResult,
        evidence_state: str = "PRESENT",
        reason_codes: list[str] | None = None,
    ) -> None:
        self.decision = SimpleNamespace(
            business_result=business_result,
            reason_codes=reason_codes or [],
        )
        self.evidence = [SimpleNamespace(state=evidence_state)]


def _work(tmp_path: Path, names: list[str]) -> list[tuple[object, Path]]:
    for n in names:
        (tmp_path / n).touch()
    return [(None, tmp_path / n) for n in names]


def test_run_verify_counts_unlabeled_and_failed(tmp_path: Path) -> None:
    work = _work(tmp_path, ["ok_a.png", "ok_b.png", "plain.png"])
    report = run_verify(
        _FakePipeline(failures={"ok_b.png"}),  # type: ignore[arg-type]
        work,  # type: ignore[arg-type]
        expected={"ok_a.png": ExpectedResult(True), "ok_b.png": ExpectedResult(False)},
        writer=object(),  # type: ignore[arg-type]
    )
    assert len(report.rows) == 1
    assert report.unlabeled == 1
    assert report.failed == 1
    assert report.has_gaps is True


def test_run_verify_detects_unmatched_expected(tmp_path: Path) -> None:
    work = _work(tmp_path, ["ok_a.png"])
    report = run_verify(
        _FakePipeline(failures=set()),  # type: ignore[arg-type]
        work,  # type: ignore[arg-type]
        expected={"ok_a.png": ExpectedResult(True), "ghost.png": ExpectedResult(False)},
        writer=object(),  # type: ignore[arg-type]
    )
    assert report.unmatched_expected == 1
    assert report.has_gaps is True


def test_run_verify_complete_input_is_not_a_gap(tmp_path: Path) -> None:
    report = run_verify(
        _FakePipeline(failures=set()),  # type: ignore[arg-type]
        _work(tmp_path, ["ok_a.png"]),  # type: ignore[arg-type]
        expected={"ok_a.png": ExpectedResult(True)},
        writer=object(),  # type: ignore[arg-type]
    )
    assert len(report.rows) == 1
    assert report.unlabeled == 0
    assert report.failed == 0
    assert report.unmatched_expected == 0
    assert report.has_gaps is False


@pytest.mark.parametrize("failure_kind", ["incomplete", "reason"])
def test_run_verify_does_not_score_system_failure_as_expected_ng(
    tmp_path: Path, failure_kind: str
) -> None:
    kwargs = (
        {"incomplete": {"ng.png"}}
        if failure_kind == "incomplete"
        else {"failure_reasons": {"ng.png"}}
    )
    report = run_verify(
        _FakePipeline(failures=set(), **kwargs),  # type: ignore[arg-type]
        _work(tmp_path, ["ng.png"]),  # type: ignore[arg-type]
        expected={"ng.png": ExpectedResult(False)},
        writer=object(),  # type: ignore[arg-type]
    )

    assert report.rows == []
    assert report.failed == 1
    assert report.true_positive_ng == 0
    assert report.has_gaps is True
