"""Strict, secret-safe boundary for one-shot native helper responses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, cast

MAX_HELPER_OUTPUT: Final = 64 * 1024
_FRAME_EVENT: Final = "frame_probe"
_SNAPSHOT_EVENT: Final = "snapshot_capture"
_FRAME_FIELDS: Final = frozenset(
    {
        "event",
        "ok",
        "stage",
        "native_code",
        "frames",
        "bytes",
        "sps",
        "pps",
        "idr",
        "width",
        "height",
        "estimated_fps",
        "first_frame_ms",
        "session_mode",
        "clean_shutdown",
    }
)
_SNAPSHOT_FIELDS: Final = _FRAME_FIELDS | {"capture_bytes"}
MAX_SNAPSHOT_CAPTURE: Final = 4 * 1024 * 1024
_ERROR_STAGES: Final = frozenset(
    {
        "invalid_input",
        "library_symbols",
        "set_license",
        "set_region",
        "iotc_initialize",
        "iotc_lan_search_port",
        "av_initialize",
        "session_id",
        "iotc_connect",
        "session_check",
        "av_authenticate",
        "start_video",
        "receive_frame",
        "no_frame_timeout",
        "capture_output",
    }
)
_LIBRARY_NAMES: Final = frozenset(
    {
        "libAVAPIs.so",
        "libIOTCAPIs.so",
        "libP2PTunnelAPIs.so",
        "libRDTAPIs.so",
        "libTUTKGlobalAPIs.so",
    }
)


class OwletHelperProtocolError(ValueError):
    """Raised when helper output is malformed or outside the safe schema."""


class OwletHelperReportedError(RuntimeError):
    """Raised for a structured native failure without retaining secrets."""

    def __init__(self, stage: str, native_code: int) -> None:
        super().__init__(f"Native helper failed during {stage}")
        self.stage = stage
        self.native_code = native_code


@dataclass(frozen=True, slots=True)
class FrameProbeResult:
    """Non-secret statistics from a bounded H.264 frame probe."""

    frames: int
    bytes_received: int
    sps: int
    pps: int
    idr: int
    width: int
    height: int
    estimated_fps: float
    first_frame_ms: int
    session_mode: str
    clean_shutdown: bool


@dataclass(frozen=True, slots=True)
class LibraryProbeResult:
    """Presence-only result from loading every required native library."""

    compatible: bool
    libraries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SnapshotCaptureResult:
    """Non-secret metadata for one captured decodable H.264 access unit."""

    frames: int
    capture_bytes: int
    sps: int
    pps: int
    idr: int
    width: int
    height: int
    session_mode: str
    clean_shutdown: bool


def parse_frame_probe_output(output: bytes) -> FrameProbeResult:
    """Parse exactly one fixed-schema frame result."""
    payload = _single_json_object(output)
    if set(payload) - _FRAME_FIELDS or payload.get("event") != _FRAME_EVENT:
        raise OwletHelperProtocolError("Native helper returned unsafe output")
    if payload.get("ok") is not True:
        stage = payload.get("stage")
        native_code = payload.get("native_code")
        if stage not in _ERROR_STAGES or not _is_int(native_code):
            raise OwletHelperProtocolError("Native helper returned invalid error data")
        raise OwletHelperReportedError(str(stage), cast(int, native_code))

    required = {
        "frames",
        "bytes",
        "sps",
        "pps",
        "idr",
        "width",
        "height",
        "estimated_fps",
        "first_frame_ms",
        "session_mode",
        "clean_shutdown",
    }
    if not required.issubset(payload):
        raise OwletHelperProtocolError("Native helper result is incomplete")
    integers = [
        payload[key]
        for key in (
            "frames",
            "bytes",
            "sps",
            "pps",
            "idr",
            "width",
            "height",
            "first_frame_ms",
        )
    ]
    if not all(_is_int(value) and value >= 0 for value in integers):
        raise OwletHelperProtocolError("Native helper returned invalid statistics")
    fps = payload["estimated_fps"]
    session_mode = payload["session_mode"]
    if not isinstance(fps, (int, float)) or isinstance(fps, bool):
        raise OwletHelperProtocolError("Native helper returned invalid statistics")
    if (
        not 0 <= float(fps) <= 240
        or session_mode not in {"lan", "p2p", "relay"}
        or payload["clean_shutdown"] is not True
    ):
        raise OwletHelperProtocolError("Native helper returned invalid statistics")
    return FrameProbeResult(
        frames=int(payload["frames"]),
        bytes_received=int(payload["bytes"]),
        sps=int(payload["sps"]),
        pps=int(payload["pps"]),
        idr=int(payload["idr"]),
        width=int(payload["width"]),
        height=int(payload["height"]),
        estimated_fps=float(fps),
        first_frame_ms=int(payload["first_frame_ms"]),
        session_mode=str(session_mode),
        clean_shutdown=True,
    )


def parse_library_probe_output(output: bytes) -> LibraryProbeResult:
    """Parse load booleans while discarding dynamic-linker error strings."""
    if not output or len(output) > MAX_HELPER_OUTPUT:
        raise OwletHelperProtocolError("Native helper output size is invalid")
    loaded: set[str] = set()
    complete = False
    try:
        lines = output.decode("utf-8").splitlines()
    except UnicodeDecodeError as err:
        raise OwletHelperProtocolError("Native helper output is not UTF-8") from err
    for line in lines:
        try:
            payload: object = json.loads(line)
        except json.JSONDecodeError as err:
            raise OwletHelperProtocolError(
                "Native helper returned malformed JSON"
            ) from err
        if not isinstance(payload, dict):
            raise OwletHelperProtocolError("Native helper returned invalid output")
        if payload.get("event") == "library_probe":
            name = payload.get("library")
            if name not in _LIBRARY_NAMES or payload.get("ok") is not True:
                raise OwletHelperReportedError("probe_libraries", -1)
            if set(payload) != {"event", "library", "ok"}:
                raise OwletHelperProtocolError("Native helper returned unsafe output")
            loaded.add(str(name))
        elif payload == {
            "event": "probe_complete",
            "ok": True,
            "failures": 0,
        }:
            complete = True
        else:
            raise OwletHelperProtocolError("Native helper returned unsafe output")
    if not complete or loaded != _LIBRARY_NAMES:
        raise OwletHelperProtocolError("Native helper result is incomplete")
    return LibraryProbeResult(compatible=True, libraries=tuple(sorted(loaded)))


def parse_snapshot_capture_output(output: bytes) -> SnapshotCaptureResult:
    """Parse one fixed-schema decodable-GOP capture result."""
    payload = _single_json_object(output)
    if set(payload) - _SNAPSHOT_FIELDS or payload.get("event") != _SNAPSHOT_EVENT:
        raise OwletHelperProtocolError("Native helper returned unsafe output")
    if payload.get("ok") is not True:
        stage = payload.get("stage")
        native_code = payload.get("native_code")
        if stage not in _ERROR_STAGES or not _is_int(native_code):
            raise OwletHelperProtocolError("Native helper returned invalid error data")
        raise OwletHelperReportedError(str(stage), cast(int, native_code))
    required = {
        "frames",
        "capture_bytes",
        "sps",
        "pps",
        "idr",
        "width",
        "height",
        "session_mode",
        "clean_shutdown",
    }
    if not required.issubset(payload):
        raise OwletHelperProtocolError("Native helper result is incomplete")
    integers = [
        payload[key]
        for key in ("frames", "capture_bytes", "sps", "pps", "idr", "width", "height")
    ]
    if not all(_is_int(value) and value >= 0 for value in integers):
        raise OwletHelperProtocolError("Native helper returned invalid statistics")
    if (
        not 1 <= payload["frames"] <= 100
        or not 1 <= payload["capture_bytes"] <= MAX_SNAPSHOT_CAPTURE
        or payload["sps"] < 1
        or payload["pps"] < 1
        or payload["idr"] < 1
        or not 160 <= payload["width"] <= 8192
        or not 120 <= payload["height"] <= 8192
        or payload["session_mode"] not in {"lan", "p2p", "relay"}
        or payload["clean_shutdown"] is not True
    ):
        raise OwletHelperProtocolError("Native helper returned invalid statistics")
    return SnapshotCaptureResult(
        frames=payload["frames"],
        capture_bytes=payload["capture_bytes"],
        sps=payload["sps"],
        pps=payload["pps"],
        idr=payload["idr"],
        width=payload["width"],
        height=payload["height"],
        session_mode=payload["session_mode"],
        clean_shutdown=True,
    )


def _single_json_object(output: bytes) -> dict[str, Any]:
    if not output or len(output) > MAX_HELPER_OUTPUT:
        raise OwletHelperProtocolError("Native helper output size is invalid")
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise OwletHelperProtocolError("Native helper returned invalid output")
    try:
        payload: object = json.loads(lines[0])
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise OwletHelperProtocolError("Native helper returned malformed JSON") from err
    if not isinstance(payload, dict):
        raise OwletHelperProtocolError("Native helper returned invalid output")
    return payload


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
