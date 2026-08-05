"""Tests for the verify command metrics and expected-label parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from assemblyvision_edge.verify import (
    VerificationReport,
    VerifyRow,
    filename_expected,
    format_report,
    load_expected,
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
    report = VerificationReport(
        rows=[_row(True, True), _row(False, False), _row(False, True)]
    )
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


def test_filename_expected() -> None:
    assert filename_expected("ok_001.png").ok is True  # type: ignore[union-attr]
    assert filename_expected("ng_missing_001.png").ok is False  # type: ignore[union-attr]
    assert filename_expected("plain.png") is None


def test_report_ignores_unlabeled_images() -> None:
    report = VerificationReport(rows=[])
    assert report.matched == 0
    assert report.ng_recall == 0.0
