"""Strict parsing for bounded, Core-local FFprobe results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

_MAX_PROBE_OUTPUT: Final = 64 * 1024
_MAX_FAILURE_OUTPUT: Final = 8 * 1024
_MAX_DIMENSION: Final = 16_384
_MAX_FPS: Final = 240.0


class MediaProbeError(ValueError):
    """Raised when FFprobe output is absent, malformed, or implausible."""


@dataclass(frozen=True, slots=True)
class MediaProbeResult:
    """Redacted facts observed from the live Core-local media source."""

    codec: str
    profile: str | None
    level: int | None
    width: int
    height: int
    fps: float
    bitrate_kbps: float
    frames: int
    container: str


def ffprobe_binary(ffmpeg_binary: str) -> str:
    """Return the sibling FFprobe name without searching the filesystem."""
    path = Path(ffmpeg_binary)
    return str(path.with_name("ffprobe"))


def ffprobe_failure_code(stderr: bytes) -> str:
    """Classify bounded FFprobe stderr without retaining or returning it."""
    message = stderr[:_MAX_FAILURE_OUTPUT].decode("utf-8", errors="ignore").lower()
    if "404 not found" in message or "server returned 404" in message:
        return "stream_probe_http_not_found"
    if "503 service unavailable" in message or "server returned 503" in message:
        return "stream_probe_producer_unavailable"
    if "server returned 5xx" in message or "http error 5" in message:
        return "stream_probe_producer_unavailable"
    if "server returned 4xx" in message or "http error 4" in message:
        return "stream_probe_http_rejected"
    if "connection refused" in message:
        return "stream_probe_connection_refused"
    if "connection reset" in message:
        return "stream_probe_connection_reset"
    if "option not found" in message or "unrecognized option" in message:
        return "stream_probe_ffprobe_incompatible"
    if "timed out" in message or "timeout" in message:
        return "stream_probe_timeout"
    if (
        "invalid data found" in message
        or "could not find codec parameters" in message
        or "could not detect ts packet size" in message
    ):
        return "stream_probe_invalid_media"
    if "end of file" in message:
        return "stream_probe_empty_stream"
    if "error opening input" in message:
        return "stream_probe_open_failed"
    if "input/output error" in message:
        return "stream_probe_io_error"
    if "invalid argument" in message:
        return "stream_probe_invalid_argument"
    if "permission denied" in message or "operation not permitted" in message:
        return "stream_probe_permission_denied"
    return "stream_probe_ffprobe_exit"


def parse_media_probe_output(
    payload: bytes,
    *,
    observed_frames: int,
    observed_bytes: int,
    observed_seconds: float,
) -> MediaProbeResult:
    """Parse only the bounded fields requested from FFprobe."""
    if not payload or len(payload) > _MAX_PROBE_OUTPUT:
        raise MediaProbeError("FFprobe output size is invalid")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise MediaProbeError("FFprobe returned malformed JSON") from err
    if not isinstance(document, dict):
        raise MediaProbeError("FFprobe result must be an object")
    streams = document.get("streams")
    if not isinstance(streams, list) or len(streams) != 1:
        raise MediaProbeError("FFprobe did not report exactly one video stream")
    stream = streams[0]
    if not isinstance(stream, dict):
        raise MediaProbeError("FFprobe video stream is invalid")

    codec = stream.get("codec_name")
    width = stream.get("width")
    height = stream.get("height")
    if codec != "h264":
        raise MediaProbeError("The Core-local stream is not H.264")
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not 1 <= width <= _MAX_DIMENSION
        or not isinstance(height, int)
        or isinstance(height, bool)
        or not 1 <= height <= _MAX_DIMENSION
    ):
        raise MediaProbeError("FFprobe reported an invalid resolution")
    if observed_frames <= 0 or observed_bytes <= 0 or observed_seconds <= 0:
        raise MediaProbeError("No bounded media was observed")

    counted_frames = _positive_int(stream.get("nb_read_frames"))
    if counted_frames is None:
        raise MediaProbeError("FFprobe did not count decoded video frames")
    fps = _parse_rate(stream.get("avg_frame_rate"))
    if fps is None:
        fps = observed_frames / observed_seconds
    if not 0 < fps <= _MAX_FPS:
        raise MediaProbeError("FFprobe reported an invalid frame rate")

    profile = stream.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        profile = None
    level = _positive_int(stream.get("level"))
    format_section = document.get("format")
    container = (
        format_section.get("format_name") if isinstance(format_section, dict) else None
    )
    if not isinstance(container, str) or "mpegts" not in container.split(","):
        raise MediaProbeError("FFprobe did not recognize the MPEG-TS container")

    return MediaProbeResult(
        codec=codec,
        profile=profile,
        level=level,
        width=width,
        height=height,
        fps=round(fps, 3),
        bitrate_kbps=round(observed_bytes * 8 / observed_seconds / 1000, 1),
        frames=counted_frames,
        container="mpegts",
    )


def _positive_int(value: Any) -> int | None:
    """Return one strictly positive integer from FFprobe JSON."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdecimal():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _parse_rate(value: Any) -> float | None:
    """Parse a bounded FFprobe rational without evaluating arbitrary text."""
    if not isinstance(value, str):
        return None
    try:
        rate = float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if 0 < rate <= _MAX_FPS else None
