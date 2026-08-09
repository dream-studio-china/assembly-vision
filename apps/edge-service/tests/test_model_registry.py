"""E4c shared model weight cache tests (ADR-013 Phase 3, E4 task invariant 6).

Proves the process-wide ModelRegistry loads each immutable artifact once and
keeps distinct artifacts/devices separate, and that detectors wired with the
registry reuse the cached handle instead of reloading YOLO weights.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_edge.detection.product_detector import ProductDetector
from assemblyvision_edge.detection.registry import ModelRegistry, model_weight_key
from assemblyvision_vision.manifests import load_model_manifest

from tests.conftest import COMPONENT_MANIFEST, PRODUCT_MANIFEST
from tests.test_detectors import (
    _component_settings,
    _components,
    _FakeUltralyticsModel,
    _product_settings,
)


def _fake_yolo(calls: list[int]) -> _FakeUltralyticsModel:
    calls.append(1)
    return _FakeUltralyticsModel()


class TestModelRegistry:
    def test_same_key_loads_once(self) -> None:
        registry = ModelRegistry()
        calls: list[int] = []

        def factory() -> object:
            calls.append(1)
            return object()

        first = registry.load("k", factory)
        second = registry.load("k", factory)
        assert first is second
        assert len(calls) == 1
        assert registry.size() == 1

    def test_distinct_keys_load_separately(self) -> None:
        registry = ModelRegistry()
        a = registry.load("a", lambda: object())
        b = registry.load("b", lambda: object())
        assert a is not b
        assert registry.size() == 2

    def test_clear_resets(self) -> None:
        registry = ModelRegistry()
        registry.load("k", lambda: object())
        registry.clear()
        assert registry.size() == 0

    def test_concurrent_loads_share_one_handle(self) -> None:
        import threading

        registry = ModelRegistry()
        barrier = threading.Barrier(8)
        handles: list[object] = []
        lock = threading.Lock()
        calls: list[int] = []

        def factory() -> object:
            calls.append(1)
            return object()

        def worker() -> None:
            barrier.wait()
            handle = registry.load("shared", factory)
            with lock:
                handles.append(handle)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len({id(handle) for handle in handles}) == 1
        assert len(calls) == 1


class TestModelWeightKey:
    def test_key_binds_artifact_checksum_and_device(self) -> None:
        manifest = load_model_manifest(PRODUCT_MANIFEST)
        key_cpu = model_weight_key(manifest, None)
        key_gpu = model_weight_key(manifest, "cuda:0")
        assert key_cpu != key_gpu
        assert key_cpu.endswith(":default")


class TestDetectorRegistryIntegration:
    def test_product_detector_reuses_cached_weights(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        weights = tmp_path / "model.pt"
        weights.write_bytes(b"weights")
        manifest = load_model_manifest(PRODUCT_MANIFEST)
        registry = ModelRegistry()
        calls: list[int] = []

        monkeypatch.setattr(
            "assemblyvision_edge.detection.product_detector.verify_manifest_artifact",
            lambda manifest, path: weights,
        )
        monkeypatch.setattr(
            "assemblyvision_edge.detection.product_detector.verify_model_class_map",
            lambda names, manifest: None,
        )
        monkeypatch.setattr(
            "ultralytics.YOLO",
            lambda path: _fake_yolo(calls),
        )
        ProductDetector.from_manifest(
            manifest, _product_settings(), tmp_path / "m.json", registry=registry
        )
        ProductDetector.from_manifest(
            manifest, _product_settings(), tmp_path / "m.json", registry=registry
        )
        assert len(calls) == 1

    def test_component_manifest_is_a_distinct_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        weights = tmp_path / "model.pt"
        weights.write_bytes(b"weights")
        registry = ModelRegistry()
        calls: list[int] = []

        def install(target: str) -> None:
            monkeypatch.setattr(
                f"assemblyvision_edge.detection.{target}.verify_manifest_artifact",
                lambda manifest, path: weights,
            )
            monkeypatch.setattr(
                f"assemblyvision_edge.detection.{target}.verify_model_class_map",
                lambda names, manifest: None,
            )

        install("product_detector")
        install("component_detector")
        monkeypatch.setattr(
            "ultralytics.YOLO",
            lambda path: _fake_yolo(calls),
        )
        product = load_model_manifest(PRODUCT_MANIFEST)
        component = load_model_manifest(COMPONENT_MANIFEST)
        # The checked-in fixtures share a placeholder artifact checksum, so
        # give the component manifest a distinct artifact identity to prove
        # distinct weights are never merged.
        component = component.model_copy(
            update={"artifacts": [component.artifacts[0].model_copy(update={"sha256": "1" * 64})]}
        )
        ProductDetector.from_manifest(
            product, _product_settings(), tmp_path / "m.json", registry=registry
        )
        from assemblyvision_edge.detection.component_detector import ComponentDetector

        ComponentDetector.from_manifest(
            component, _component_settings(), _components(), tmp_path / "m.json", registry=registry
        )
        # Two different manifests never merge into one cached handle.
        assert len(calls) == 2
        assert registry.size() == 2
