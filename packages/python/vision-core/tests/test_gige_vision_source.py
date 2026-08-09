"""Tests for the GigE Vision frame source (design 07.3, ADR-013).

A fake ``harvesters.core`` module drives the source so serial binding, GenTL
producer loading, GenICam node configuration, buffer copy/release ordering, and
pixel-format conversion are exercised without camera hardware or a GenTL
producer in CI.
"""

from __future__ import annotations

from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from assemblyvision_vision.sources import _harvester
from assemblyvision_vision.sources.frame_source import (
    CameraSettings,
    CapturedFrame,
    FrameStreamError,
)
from assemblyvision_vision.sources.gige_vision_source import (
    GigeReconnectPolicy,
    GigEVisionFrameSource,
)

_PRODUCER = "vendor_producer.cti"
_SERIAL = "SN-1234"


class FakeNode:
    def __init__(self, value: object) -> None:
        self._value = value

    @property
    def value(self) -> object:
        return self._value

    @value.setter
    def value(self, v: object) -> None:
        self._value = v


class RejectingNode:
    """A node that silently ignores writes, like a camera rejecting a value."""

    def __init__(self, value: object) -> None:
        self._value = value

    @property
    def value(self) -> object:
        return self._value

    @value.setter
    def value(self, v: object) -> None:
        return


class FakeCommandNode:
    def __init__(self) -> None:
        self.executions = 0

    def execute(self) -> None:
        self.executions += 1


class FakeNodeMap:
    def __init__(
        self,
        pixel_format: str = "Mono8",
        *,
        reject: set[str] | None = None,
        missing: set[str] | None = None,
    ) -> None:
        rejects = reject or set()
        self.Width = RejectingNode(640) if "Width" in rejects else FakeNode(640)
        self.Height = RejectingNode(480) if "Height" in rejects else FakeNode(480)
        self.PixelFormat = (
            RejectingNode(pixel_format) if "PixelFormat" in rejects else FakeNode(pixel_format)
        )
        self.AcquisitionMode = FakeNode("Continuous")
        self.TriggerSelector = FakeNode("AcquisitionStart")
        self.TriggerMode = FakeNode("Off")
        self.TriggerSource = FakeNode("Line0")
        self.TriggerActivation = FakeNode("RisingEdge")
        self.AcquisitionFrameRate = FakeNode(25.0)
        self.ExposureTime = FakeNode(5000.0)
        self.Gain = FakeNode(1.0)
        self.GevSCPSPacketSize = FakeNode(1500)
        self.DeviceFirmwareVersion = FakeNode("1.2.3")
        self.TriggerSoftware = FakeCommandNode()
        for name in missing or set():
            delattr(self, name)


class FakeBuffer:
    def __init__(self, data: np.ndarray, data_format: str, width: int, height: int) -> None:
        self.payload = SimpleNamespace(
            components=[
                SimpleNamespace(data=data, data_format=data_format, width=width, height=height)
            ]
        )
        self.queued = False

    def queue(self) -> None:
        self.queued = True


class FakeAcquirer:
    def __init__(
        self,
        node_map: FakeNodeMap,
        frames: list[FakeBuffer] | None = None,
        *,
        timeout_fetches: int = 0,
        start_error: Exception | None = None,
    ) -> None:
        self.remote_device = SimpleNamespace(node_map=node_map)
        self.frames = list(frames or [])
        self.timeout_fetches = timeout_fetches
        self.started = False
        self.stopped = False
        self.destroyed = False
        self.fetch_calls = 0
        self.timeouts_remaining = timeout_fetches
        self.start_error = start_error

    def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def destroy(self) -> None:
        self.destroyed = True

    def fetch(self, timeout: float | None = None) -> FakeBuffer:
        self.fetch_calls += 1
        if self.timeouts_remaining > 0:
            self.timeouts_remaining -= 1
            raise TimeoutError("no buffer within timeout")
        if not self.frames:
            raise RuntimeError("no buffers available")
        return self.frames.pop(0)


class FakeDeviceInfo:
    def __init__(
        self,
        serial_number: str,
        *,
        model: str = "FakeCam-4MP",
        parent: str = "eth0",
    ) -> None:
        self.serial_number = serial_number
        self.model = model
        self.parent = parent


class FakeHarvester:
    """Serves pre-planned Harvester instances to the source under test.

    The source constructs its own Harvester internally, so each test plans the
    instances (devices/acquirers/errors) that successive ``Harvester()`` calls
    should receive. One plan entry is consumed per acquisition session.
    """

    instances: list[FakeHarvester] = []
    planned: list[dict[str, object]] = []

    @classmethod
    def plan(
        cls,
        device_infos: list[object] | None = None,
        acquirers: list[FakeAcquirer] | None = None,
        *,
        add_file_error: Exception | None = None,
    ) -> None:
        cls.planned.append(
            {
                "device_infos": list(device_infos or []),
                "acquirers": list(acquirers or []),
                "add_file_error": add_file_error,
            }
        )

    def __init__(self) -> None:
        type(self).instances.append(self)
        spec = type(self).planned.pop(0) if type(self).planned else {}
        self.files: list[str] = []
        self.device_infos: list[object] = spec.get("device_infos", [])  # type: ignore[assignment]
        self.acquirers: list[FakeAcquirer] = spec.get("acquirers", [])  # type: ignore[assignment]
        self.add_file_error: Exception | None = spec.get("add_file_error")  # type: ignore[assignment]
        self.resets = 0
        self.updates = 0

    def add_file(self, path: str) -> None:
        if self.add_file_error is not None:
            raise self.add_file_error
        self.files.append(str(path))

    def update(self) -> None:
        self.updates += 1

    def create(self, index: int) -> FakeAcquirer:
        return self.acquirers[index]

    def reset(self) -> None:
        self.resets += 1

    @property
    def device_info_list(self) -> list[object]:
        return self.device_infos


@pytest.fixture
def install_fake_harvester(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a fake ``harvesters.core`` module and reset its plan/instance logs."""
    FakeHarvester.instances = []
    FakeHarvester.planned = []
    monkeypatch.setattr(_harvester, "_harvester", SimpleNamespace(Harvester=FakeHarvester))


def _mono8_frame(width: int = 2, height: int = 2) -> FakeBuffer:
    return FakeBuffer(np.arange(width * height, dtype=np.uint8), "Mono8", width, height)


def _source(
    *,
    trigger_mode: str = "continuous",
    pixel_format: str | None = None,
    exposure_us: float | None = None,
    gain_db: float | None = None,
    packet_size: int | None = None,
    fps: float | None = None,
) -> GigEVisionFrameSource:
    return GigEVisionFrameSource(
        _SERIAL,
        _PRODUCER,
        trigger_mode=trigger_mode,  # type: ignore[arg-type]
        pixel_format=pixel_format,
        exposure_us=exposure_us,
        gain_db=gain_db,
        packet_size=packet_size,
        fps=fps,
        reconnect=GigeReconnectPolicy(initial_delay_ms=1, maximum_delay_ms=2),
    )


def _run(source: GigEVisionFrameSource, n: int) -> list[CapturedFrame]:
    stop = Event()
    iterator = source.frames(stop)
    frames = [next(iterator) for _ in range(n)]
    stop.set()
    with pytest.raises(StopIteration):
        next(iterator)
    return frames


# -- constructor validation --------------------------------------------------


def test_gige_requires_non_empty_serial() -> None:
    with pytest.raises(FrameStreamError, match="serial"):
        GigEVisionFrameSource("  ", _PRODUCER)


def test_gige_rejects_invalid_trigger_mode() -> None:
    with pytest.raises(FrameStreamError, match="trigger_mode"):
        GigEVisionFrameSource(_SERIAL, _PRODUCER, trigger_mode="floppy")  # type: ignore[arg-type]


# -- open / capabilities -----------------------------------------------------


def test_gige_open_reports_capabilities(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    acquirer = FakeAcquirer(node_map)
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[acquirer])
    source = _source()
    capabilities = source.open()
    assert capabilities.source_width == 640
    assert capabilities.source_height == 480
    assert capabilities.pixel_format == "Mono8"
    assert capabilities.camera_serial == _SERIAL
    assert capabilities.camera_model == "FakeCam-4MP"
    assert capabilities.firmware_version == "1.2.3"
    assert capabilities.gentl_producer == _PRODUCER
    assert capabilities.transport_parent == "eth0"
    assert capabilities.trigger_mode == "continuous"
    assert capabilities.exposure_us == 5000.0
    assert capabilities.gain_db == 1.0
    assert capabilities.packet_size == 1500
    # The session is closed after open: destroy + reset ran exactly once.
    assert acquirer.destroyed
    assert FakeHarvester.instances[0].resets == 1
    # The GenTL producer was loaded on the Harvester instance.
    assert FakeHarvester.instances[0].files == [_PRODUCER]


def test_gige_open_applies_pixel_format(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap(pixel_format="Mono8")
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    source = _source(pixel_format="RGB8")
    capabilities = source.open()
    assert capabilities.pixel_format == "RGB8"
    assert node_map.PixelFormat.value == "RGB8"


def test_gige_open_no_device_raises(install_fake_harvester: None) -> None:
    FakeHarvester.plan(device_infos=[])
    with pytest.raises(FrameStreamError, match="no GigE Vision camera"):
        _source().open()


def test_gige_open_ambiguous_serial_raises(install_fake_harvester: None) -> None:
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL), FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(FakeNodeMap())],
    )
    with pytest.raises(FrameStreamError, match="multiple GigE Vision cameras"):
        _source().open()


def test_gige_open_supports_dict_device_info(install_fake_harvester: None) -> None:
    FakeHarvester.plan(
        device_infos=[{"serial_number": _SERIAL}],
        acquirers=[FakeAcquirer(FakeNodeMap())],
    )
    capabilities = _source().open()
    assert capabilities.source_width == 640


def test_gige_open_producer_failure_raises(install_fake_harvester: None) -> None:
    FakeHarvester.plan(device_infos=[], add_file_error=RuntimeError("invalid cti"))
    with pytest.raises(FrameStreamError, match="cannot open GigE Vision camera"):
        _source().open()


def test_gige_open_missing_node_raises(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap(missing={"ExposureTime"})
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    with pytest.raises(FrameStreamError, match="does not expose node 'ExposureTime'"):
        _source(exposure_us=5000.0).open()


def test_gige_open_rejected_node_raises(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap(pixel_format="Mono8", reject={"PixelFormat"})
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    with pytest.raises(FrameStreamError, match="rejected node PixelFormat"):
        _source(pixel_format="RGB8").open()


def test_gige_open_optional_node_absence_accepted(install_fake_harvester: None) -> None:
    # TriggerActivation and AcquisitionFrameRate are optional; absence is fine.
    node_map = FakeNodeMap(missing={"TriggerActivation", "AcquisitionFrameRate"})
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    capabilities = _source(trigger_mode="hardware", fps=25.0).open()
    assert capabilities.fps == 25.0


def test_gige_configure_applies_fps_and_dims(install_fake_harvester: None) -> None:
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(FakeNodeMap())],
    )
    source = _source()
    applied = source.configure(CameraSettings(fps=12.0, width=320, height=240))
    assert applied.fps == 12.0
    # Requested dimensions are applied to the camera and reported back.
    assert applied.width == 320
    assert applied.height == 240
    assert source.fetch_timeout_s == max(2.0, 4.0 / 12.0)


# -- trigger node configuration ----------------------------------------------


def test_gige_continuous_disables_trigger(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    _source(trigger_mode="continuous").open()
    assert node_map.TriggerMode.value == "Off"
    assert node_map.AcquisitionMode.value == "Continuous"


def test_gige_software_trigger_configures_nodes(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    _source(trigger_mode="software").open()
    assert node_map.TriggerSelector.value == "FrameStart"
    assert node_map.TriggerMode.value == "On"
    assert node_map.TriggerSource.value == "Software"


def test_gige_hardware_trigger_configures_nodes(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    _source(trigger_mode="hardware").open()
    assert node_map.TriggerSelector.value == "FrameStart"
    assert node_map.TriggerMode.value == "On"
    assert node_map.TriggerSource.value == "Line0"
    assert node_map.TriggerActivation.value == "RisingEdge"


def test_gige_hardware_trigger_accepts_missing_activation(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap(missing={"TriggerActivation"})
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    _source(trigger_mode="hardware").open()
    assert node_map.TriggerSource.value == "Line0"


def test_gige_trigger_mode_requires_frame_start_selector(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap(missing={"TriggerSelector"})
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    with pytest.raises(FrameStreamError, match="does not expose node 'TriggerSelector'"):
        _source(trigger_mode="hardware").open()


def test_gige_exposure_gain_packet_applied(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    _source(
        exposure_us=8000.0,
        gain_db=2.5,
        packet_size=9000,
    ).open()
    assert node_map.ExposureTime.value == 8000.0
    assert node_map.Gain.value == 2.5
    assert node_map.GevSCPSPacketSize.value == 9000


def test_gige_zero_gain_applied(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[FakeAcquirer(node_map)])
    _source(gain_db=0.0).open()
    assert node_map.Gain.value == 0.0


# -- frame streaming ---------------------------------------------------------


def test_gige_frames_mono8_converted_to_rgb(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    buffer = _mono8_frame()
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(node_map, frames=[buffer])],
    )
    frames = _run(_source(), 1)
    frame = frames[0]
    assert frame.sequence == 1
    assert frame.pixel_format == "Mono8"
    assert frame.width == 2 and frame.height == 2
    assert frame.image.mode == "RGB"
    assert frame.image.getpixel((0, 0)) == (0, 0, 0)
    assert frame.image.getpixel((1, 1)) == (3, 3, 3)
    # The SDK buffer was requeued after the frame was copied.
    assert buffer.queued


def test_gige_frames_rgb8_passthrough(install_fake_harvester: None) -> None:
    data = np.array([[[10, 20, 30], [40, 50, 60]], [[70, 80, 90], [100, 110, 120]]], np.uint8)
    buffer = FakeBuffer(data, "RGB8", 2, 2)
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(FakeNodeMap(pixel_format="RGB8"), frames=[buffer])],
    )
    frame = _run(_source(pixel_format="RGB8"), 1)[0]
    assert frame.image.getpixel((0, 0)) == (10, 20, 30)
    assert frame.image.getpixel((1, 1)) == (100, 110, 120)


def test_gige_frames_bgr8_channels_swapped(install_fake_harvester: None) -> None:
    # Each pixel is BGR in the buffer; the output must be RGB.
    data = np.array([[[10, 20, 30], [40, 50, 60]]], np.uint8).reshape(1, 2, 3)
    buffer = FakeBuffer(data, "BGR8", 2, 1)
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(FakeNodeMap(pixel_format="BGR8"), frames=[buffer])],
    )
    frame = _run(_source(pixel_format="BGR8"), 1)[0]
    assert frame.image.getpixel((0, 0)) == (30, 20, 10)
    assert frame.image.getpixel((1, 0)) == (60, 50, 40)


def test_gige_frames_sequence_increments(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(node_map, frames=[_mono8_frame(), _mono8_frame()])],
    )
    frames = _run(_source(), 2)
    assert [frame.sequence for frame in frames] == [1, 2]


def test_gige_frames_unsupported_format_raises(install_fake_harvester: None) -> None:
    buffer = FakeBuffer(np.zeros(4, np.uint8), "BayerRG8", 2, 2)
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(FakeNodeMap(), frames=[buffer])],
    )
    stop = Event()
    with pytest.raises(FrameStreamError, match="unsupported GigE Vision pixel format"):
        next(_source().frames(stop))
    stop.set()


def test_gige_frames_malformed_buffer_raises(install_fake_harvester: None) -> None:
    buffer = FakeBuffer(np.zeros(3, np.uint8), "Mono8", 2, 2)
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(FakeNodeMap(), frames=[buffer])],
    )
    stop = Event()
    with pytest.raises(FrameStreamError, match="malformed Mono8 buffer"):
        next(_source().frames(stop))
    stop.set()


def test_gige_software_trigger_executes_before_fetch(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    trigger = node_map.TriggerSoftware
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(node_map, frames=[_mono8_frame()])],
    )
    frames = _run(_source(trigger_mode="software"), 1)
    assert frames[0].sequence == 1
    assert trigger.executions == 1
    assert node_map.TriggerSelector.value == "FrameStart"


def test_gige_software_trigger_timeout_is_stream_error(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    acquirer = FakeAcquirer(node_map, frames=[_mono8_frame()], timeout_fetches=1)
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[acquirer])
    stop = Event()
    with pytest.raises(FrameStreamError, match="software trigger timed out"):
        next(_source(trigger_mode="software").frames(stop))
    assert acquirer.fetch_calls == 1
    assert acquirer.stopped


def test_gige_hardware_trigger_does_not_pace_frames(
    install_fake_harvester: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_vision.sources import gige_vision_source

    calls: list[float | None] = []
    monkeypatch.setattr(gige_vision_source, "pace", lambda stop, fps: calls.append(fps))
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(FakeNodeMap(), frames=[_mono8_frame(), _mono8_frame()])],
    )
    _run(_source(trigger_mode="hardware", fps=25.0), 2)
    assert calls == []


def test_gige_start_failure_is_frame_stream_error(install_fake_harvester: None) -> None:
    acquirer = FakeAcquirer(FakeNodeMap(), start_error=RuntimeError("camera busy"))
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[acquirer])
    stop = Event()
    with pytest.raises(FrameStreamError, match="cannot start GigE Vision acquisition"):
        next(_source().frames(stop))


def test_gige_payload_failure_is_frame_stream_error(install_fake_harvester: None) -> None:
    buffer = FakeBuffer(np.zeros(4, np.uint8), "Mono8", 2, 2)
    buffer.payload.components = []
    FakeHarvester.plan(
        device_infos=[FakeDeviceInfo(_SERIAL)],
        acquirers=[FakeAcquirer(FakeNodeMap(), frames=[buffer])],
    )
    stop = Event()
    with pytest.raises(FrameStreamError, match="cannot decode GigE Vision frame"):
        next(_source().frames(stop))
    assert buffer.queued


def test_gige_continuous_timeout_reconnects(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    first = FakeAcquirer(node_map, timeout_fetches=1)
    second = FakeAcquirer(node_map, frames=[_mono8_frame()])
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[first])
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[second])
    frames = _run(_source(), 1)
    assert frames[0].sequence == 1
    assert first.destroyed and second.started
    assert len(FakeHarvester.instances) == 2


def test_gige_open_failure_backs_off_then_streams(install_fake_harvester: None) -> None:
    acquirer = FakeAcquirer(FakeNodeMap(), frames=[_mono8_frame()])
    # First discovery sees no camera; the line appears afterwards.
    FakeHarvester.plan(device_infos=[])
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[acquirer])
    frames = _run(_source(), 1)
    assert frames[0].sequence == 1
    assert len(FakeHarvester.instances) == 2


def test_gige_close_stops_active_session(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    acquirer = FakeAcquirer(node_map, frames=[_mono8_frame(), _mono8_frame()])
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[acquirer])
    source = _source()
    stop = Event()
    iterator = source.frames(stop)
    first = next(iterator)
    assert first.sequence == 1
    source.close()  # close() while streaming destroys the active session
    assert acquirer.destroyed
    stop.set()
    with pytest.raises(StopIteration):
        next(iterator)
    source.close()  # idempotent


def test_gige_stop_ends_stream(install_fake_harvester: None) -> None:
    node_map = FakeNodeMap()
    acquirer = FakeAcquirer(node_map, frames=[_mono8_frame(), _mono8_frame()])
    FakeHarvester.plan(device_infos=[FakeDeviceInfo(_SERIAL)], acquirers=[acquirer])
    stop = Event()
    stop.set()
    iterator = _source().frames(stop)
    with pytest.raises(StopIteration):
        next(iterator)
