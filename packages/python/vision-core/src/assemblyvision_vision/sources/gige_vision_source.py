"""GigE Vision / GenICam frame source via Harvester and a GenTL producer (design 07.3, ADR-013).

The production-preferred industrial camera path. The camera is bound by stable
serial number (never IP), the configured GenTL producer (``.cti``) is loaded at
open time, and only the pixel formats in :data:`SUPPORTED_PIXEL_FORMATS` are
converted deterministically to RGB; anything else raises
:class:`FrameStreamError` before it can become evidence (fail-safe). Buffers
are copied before the SDK buffer is requeued, so downstream code never holds a
view into the acquisition ring.

Continuous, software, and hardware trigger modes are configured through the
standard GenICam node map and verified by read-back. Hardware trigger uses
``Line0`` with ``RisingEdge`` activation when the camera exposes the node; some
cameras fix the activation polarity and omit it, which is accepted. Settings
that are explicitly configured (pixel format, exposure, gain, packet size)
must apply and verify, otherwise the source fails before inspection.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from threading import Event
from typing import Any, Literal

from PIL import Image

from assemblyvision_vision.sources._harvester import get_harvester
from assemblyvision_vision.sources._pacing import pace
from assemblyvision_vision.sources.frame_source import (
    AppliedSettings,
    CameraCapabilities,
    CameraSettings,
    CapturedFrame,
    FrameStreamError,
)

TriggerMode = Literal["continuous", "software", "hardware"]

#: Native formats converted deterministically to RGB. Extend deliberately only
#: after validating the conversion against production images; Bayer/YUV formats
#: stay unsupported rather than guessed.
SUPPORTED_PIXEL_FORMATS: frozenset[str] = frozenset({"Mono8", "RGB8", "BGR8"})

_TRIGGER_SELECTOR = "FrameStart"
_HARDWARE_TRIGGER_SOURCE = "Line0"
_HARDWARE_TRIGGER_ACTIVATION = "RisingEdge"


@dataclass(frozen=True)
class GigeReconnectPolicy:
    """Bounded exponential backoff for GigE Vision reconnects (design 07.7)."""

    initial_delay_ms: int = 250
    maximum_delay_ms: int = 10000


class _AcquisitionSession:
    """Owns one Harvester + ImageAcquirer pair for a single acquisition run."""

    def __init__(self, harvester: Any, acquirer: Any, node_map: Any, device_info: Any) -> None:
        self.harvester = harvester
        self.acquirer = acquirer
        self.node_map = node_map
        self.device_info = device_info
        self._closed = False
        self._running = False

    def start(self) -> None:
        try:
            self.acquirer.start()
        except Exception as exc:
            raise FrameStreamError("cannot start GigE Vision acquisition") from exc
        self._running = True

    def close(self) -> None:
        """Stop, destroy, and reset the session; idempotent (cleanup never masks errors)."""
        if self._closed:
            return
        self._closed = True
        # Cleanup never masks shutdown errors.
        with suppress(Exception):
            if self._running:
                self.acquirer.stop()
        with suppress(Exception):
            self.acquirer.destroy()
        with suppress(Exception):
            self.harvester.reset()


class GigEVisionFrameSource:
    """Yields frames from a GenICam GigE Vision camera, serial-bound (design 07.3)."""

    def __init__(
        self,
        serial: str,
        gentl_producer: str | Path,
        *,
        trigger_mode: TriggerMode = "continuous",
        pixel_format: str | None = None,
        exposure_us: float | None = None,
        gain_db: float | None = None,
        packet_size: int | None = None,
        fps: float | None = None,
        width: int | None = None,
        height: int | None = None,
        reconnect: GigeReconnectPolicy | None = None,
    ) -> None:
        if not serial or not serial.strip():
            raise FrameStreamError("gige-vision source requires a non-empty serial number")
        if trigger_mode not in ("continuous", "software", "hardware"):
            raise FrameStreamError(f"invalid trigger_mode {trigger_mode!r}")
        self._serial = serial
        self._gentl_producer = str(gentl_producer)
        self._trigger_mode = trigger_mode
        self._pixel_format = pixel_format
        self._exposure_us = exposure_us
        self._gain_db = gain_db
        self._packet_size = packet_size
        self._fps = fps
        self._width = width
        self._height = height
        self._reconnect = reconnect or GigeReconnectPolicy()
        self._sequence = count(1)
        self._session: _AcquisitionSession | None = None

    @property
    def fetch_timeout_s(self) -> float:
        """Fetch timeout long enough for the configured frame interval."""
        if self._fps and self._fps > 0:
            return max(2.0, 4.0 / self._fps)
        return 2.0

    def open(self) -> CameraCapabilities:
        with self._open_session() as session:
            width = self._read_int_node(session.node_map, "Width")
            height = self._read_int_node(session.node_map, "Height")
            pixel_format = self._reported_pixel_format(session.node_map)
            return CameraCapabilities(
                source_width=width,
                source_height=height,
                fps=self._fps,
                pixel_format=pixel_format,
                camera_serial=self._serial,
                camera_model=self._device_field(session.device_info, "model"),
                firmware_version=self._optional_node_value(
                    session.node_map, "DeviceFirmwareVersion"
                ),
                gentl_producer=self._gentl_producer,
                transport_parent=self._device_field(session.device_info, "parent"),
                trigger_mode=self._trigger_mode,
                exposure_us=self._optional_float_node_value(session.node_map, "ExposureTime"),
                gain_db=self._optional_float_node_value(session.node_map, "Gain"),
                packet_size=self._optional_int_node_value(session.node_map, "GevSCPSPacketSize"),
            )

    def configure(self, settings: CameraSettings) -> AppliedSettings:
        if settings.fps is not None:
            self._fps = settings.fps
        if settings.width is not None:
            self._width = settings.width
        if settings.height is not None:
            self._height = settings.height
        capabilities = self.open()
        return AppliedSettings(
            fps=self._fps,
            width=capabilities.source_width,
            height=capabilities.source_height,
        )

    def frames(self, stop: Event) -> Iterator[CapturedFrame]:
        """Yield frames, reconnecting with bounded backoff on disconnect.

        A hardware-trigger timeout means no external trigger arrived yet, so the
        loop keeps waiting; a software-trigger timeout or continuous-mode timeout
        is an acquisition failure. Deterministic configuration errors propagate as
        :class:`FrameStreamError` instead of being masked by backoff.
        """
        while not stop.is_set():
            session = self._open_retrying(stop)
            if session is None:
                return
            try:
                session.start()
                while not stop.is_set():
                    frame = self._fetch_frame(session)
                    if frame is None:
                        if stop.is_set():
                            return
                        if self._trigger_mode == "continuous":
                            break
                        continue
                    yield frame
                    if self._trigger_mode == "continuous":
                        pace(stop, self._fps)
            finally:
                session.close()
            self._backoff(stop)

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # -- acquisition -------------------------------------------------------

    @contextmanager
    def _open_session(self) -> Iterator[_AcquisitionSession]:
        session: _AcquisitionSession | None = None
        try:
            session = self._create_session()
            self._session = session
            yield session
        finally:
            if session is not None:
                session.close()
            self._session = None

    def _create_session(self) -> _AcquisitionSession:
        harvester = get_harvester().Harvester()
        try:
            harvester.add_file(self._gentl_producer)
            harvester.update()
            index, device_info = self._find_device(harvester)
            acquirer = harvester.create(index)
        except FrameStreamError:
            harvester.reset()
            raise
        except Exception as exc:
            harvester.reset()
            raise FrameStreamError(
                f"cannot open GigE Vision camera {self._serial!r} with "
                f"producer {self._gentl_producer!r}: {exc}"
            ) from exc
        try:
            node_map = acquirer.remote_device.node_map
            self._apply_configuration(node_map)
        except FrameStreamError:
            acquirer.destroy()
            harvester.reset()
            raise
        except Exception as exc:
            acquirer.destroy()
            harvester.reset()
            raise FrameStreamError(
                f"cannot configure GigE Vision camera {self._serial!r}: {exc}"
            ) from exc
        return _AcquisitionSession(
            harvester=harvester,
            acquirer=acquirer,
            node_map=node_map,
            device_info=device_info,
        )

    def _find_device(self, harvester: Any) -> tuple[int, Any]:
        matches = [
            index
            for index, info in enumerate(harvester.device_info_list)
            if self._device_field(info, "serial_number") == self._serial
        ]
        if not matches:
            raise FrameStreamError(
                f"no GigE Vision camera with serial number {self._serial!r} "
                f"found through producer {self._gentl_producer!r}"
            )
        if len(matches) > 1:
            raise FrameStreamError(
                f"multiple GigE Vision cameras with serial number {self._serial!r}; "
                "bind each instance to a distinct serial"
            )
        index = matches[0]
        return index, harvester.device_info_list[index]

    @staticmethod
    def _device_field(info: Any, key: str) -> str | None:
        try:
            value = getattr(info, key)
        except AttributeError:
            try:
                value = info[key]
            except (KeyError, TypeError):
                return None
        if value is None:
            return None
        return str(value)

    def _apply_configuration(self, node_map: Any) -> None:
        if self._width is not None:
            self._set_node(node_map, "Width", int(self._width))
        if self._height is not None:
            self._set_node(node_map, "Height", int(self._height))
        if self._pixel_format is not None:
            self._set_node(node_map, "PixelFormat", self._pixel_format)
        self._set_node(node_map, "AcquisitionMode", "Continuous")
        if self._trigger_mode == "continuous":
            self._set_node(node_map, "TriggerMode", "Off")
        else:
            self._set_node(node_map, "TriggerSelector", _TRIGGER_SELECTOR)
            self._set_node(node_map, "TriggerMode", "On")
            source = "Software" if self._trigger_mode == "software" else _HARDWARE_TRIGGER_SOURCE
            self._set_node(node_map, "TriggerSource", source)
            if self._trigger_mode == "hardware":
                # Some cameras fix the activation polarity and omit the node;
                # absence is accepted, a conflicting value is not.
                self._set_node_optional(node_map, "TriggerActivation", _HARDWARE_TRIGGER_ACTIVATION)
        if self._fps is not None:
            self._set_node_optional(node_map, "AcquisitionFrameRate", float(self._fps))
        if self._exposure_us is not None:
            self._set_node(node_map, "ExposureTime", float(self._exposure_us))
        if self._gain_db is not None:
            self._set_node(node_map, "Gain", float(self._gain_db))
        if self._packet_size is not None:
            self._set_node(node_map, "GevSCPSPacketSize", int(self._packet_size))

    def _fetch_frame(self, session: _AcquisitionSession) -> CapturedFrame | None:
        if self._trigger_mode == "software":
            self._software_trigger(session.node_map)
        try:
            buffer = session.acquirer.fetch(timeout=self.fetch_timeout_s)
        except TimeoutError as exc:
            if self._trigger_mode == "software":
                raise FrameStreamError(
                    f"software trigger timed out for camera {self._serial!r}"
                ) from exc
            return None
        except FrameStreamError:
            raise
        except Exception as exc:
            raise FrameStreamError(
                f"cannot fetch frame from camera {self._serial!r}: {exc}"
            ) from exc
        try:
            try:
                payload = buffer.payload.components[0]
                # Copy before the SDK buffer is requeued: downstream code must
                # never hold a view into the acquisition ring.
                data = self._copy_buffer(payload.data)
                width = int(payload.width)
                height = int(payload.height)
                data_format = str(payload.data_format)
            finally:
                buffer.queue()
            return self._frame(data, data_format, width, height)
        except FrameStreamError:
            raise
        except Exception as exc:
            raise FrameStreamError(
                f"cannot decode GigE Vision frame from camera {self._serial!r}: {exc}"
            ) from exc

    @staticmethod
    def _copy_buffer(data: Any) -> Any:
        import numpy as np  # required by the Harvester runtime

        return np.array(data, copy=True)

    def _frame(self, data: Any, data_format: str, width: int, height: int) -> CapturedFrame:
        return CapturedFrame(
            monotonic_ts_ns=time.monotonic_ns(),
            wall_clock_utc=datetime.now(UTC),
            sequence=next(self._sequence),
            pixel_format=data_format,
            status="OK",
            image=self._convert_buffer(data, data_format, width, height),
        )

    @staticmethod
    def _convert_buffer(data: Any, data_format: str, width: int, height: int) -> Image.Image:
        import numpy as np  # required by the Harvester runtime

        if data_format not in SUPPORTED_PIXEL_FORMATS:
            raise FrameStreamError(
                f"unsupported GigE Vision pixel format {data_format!r}; "
                f"supported formats: {sorted(SUPPORTED_PIXEL_FORMATS)}"
            )
        flat = np.asarray(data).reshape(-1)
        if data_format == "Mono8":
            expected = width * height
            if flat.size != expected:
                raise FrameStreamError(
                    f"malformed Mono8 buffer: expected {expected} bytes, got {flat.size}"
                )
            gray = np.ascontiguousarray(flat.reshape(height, width))
            return Image.fromarray(gray, mode="L").convert("RGB")
        expected = width * height * 3
        if flat.size != expected:
            raise FrameStreamError(
                f"malformed {data_format} buffer: expected {expected} bytes, got {flat.size}"
            )
        rgb = flat.reshape(height, width, 3)
        if data_format == "BGR8":
            rgb = rgb[:, :, ::-1]
        return Image.fromarray(np.ascontiguousarray(rgb), mode="RGB")

    # -- GenICam node access ------------------------------------------------

    @staticmethod
    def _node(node_map: Any, name: str) -> Any:
        try:
            return getattr(node_map, name)
        except AttributeError as exc:
            raise FrameStreamError(f"camera does not expose node {name!r}") from exc

    @staticmethod
    def _set_node(node_map: Any, name: str, value: Any) -> None:
        node = GigEVisionFrameSource._node(node_map, name)
        try:
            node.value = value
        except Exception as exc:
            raise FrameStreamError(f"cannot set camera node {name}={value!r}: {exc}") from exc
        applied = node.value
        if not GigEVisionFrameSource._values_match(applied, value):
            raise FrameStreamError(f"camera rejected node {name}={value!r} (applied {applied!r})")

    @staticmethod
    def _set_node_optional(node_map: Any, name: str, value: Any) -> None:
        try:
            node = getattr(node_map, name)
        except AttributeError:
            return
        try:
            node.value = value
        except Exception as exc:
            raise FrameStreamError(f"cannot set camera node {name}={value!r}: {exc}") from exc
        applied = node.value
        if not GigEVisionFrameSource._values_match(applied, value):
            raise FrameStreamError(f"camera rejected node {name}={value!r} (applied {applied!r})")

    @staticmethod
    def _values_match(applied: Any, expected: Any) -> bool:
        if isinstance(expected, float) and isinstance(applied, (int, float)):
            return abs(float(applied) - expected) <= max(1e-6, abs(expected) * 1e-6)
        return bool(applied == expected)

    @staticmethod
    def _software_trigger(node_map: Any) -> None:
        node = GigEVisionFrameSource._node(node_map, "TriggerSoftware")
        try:
            node.execute()
        except Exception as exc:
            raise FrameStreamError(f"cannot execute TriggerSoftware: {exc}") from exc

    @staticmethod
    def _read_int_node(node_map: Any, name: str) -> int:
        try:
            return int(getattr(node_map, name).value)
        except Exception as exc:
            raise FrameStreamError(f"cannot read camera node {name!r}: {exc}") from exc

    def _reported_pixel_format(self, node_map: Any) -> str:
        if self._pixel_format is not None:
            return self._pixel_format
        try:
            return str(node_map.PixelFormat.value)
        except Exception:
            return "unknown"

    @staticmethod
    def _optional_node_value(node_map: Any, name: str) -> str | None:
        try:
            value = getattr(node_map, name).value
        except Exception:
            return None
        return str(value) if value is not None else None

    @staticmethod
    def _optional_float_node_value(node_map: Any, name: str) -> float | None:
        try:
            return float(getattr(node_map, name).value)
        except Exception:
            return None

    @staticmethod
    def _optional_int_node_value(node_map: Any, name: str) -> int | None:
        try:
            return int(getattr(node_map, name).value)
        except Exception:
            return None

    # -- reconnect helpers ---------------------------------------------------

    def _open_retrying(self, stop: Event) -> _AcquisitionSession | None:
        delay_ms = self._reconnect.initial_delay_ms
        while not stop.is_set():
            try:
                session = self._create_session()
            except FrameStreamError:
                self._sleep_backoff(stop, delay_ms)
                delay_ms = min(delay_ms * 2, self._reconnect.maximum_delay_ms)
                continue
            self._session = session
            return session
        return None

    def _backoff(self, stop: Event) -> None:
        self._sleep_backoff(stop, self._reconnect.initial_delay_ms)

    @staticmethod
    def _sleep_backoff(stop: Event, delay_ms: int) -> None:
        deadline = time.monotonic() + delay_ms / 1000.0
        while time.monotonic() < deadline and not stop.is_set():
            time.sleep(min(0.05, deadline - time.monotonic()))
