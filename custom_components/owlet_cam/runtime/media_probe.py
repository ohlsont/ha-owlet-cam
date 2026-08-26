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
_SAFE_TEXT_CHARACTERS: Final = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 /,._-"
)


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
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None


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


def media_probe_error_code(error: MediaProbeError) -> str:
    """Reduce a parser failure to a stable, secret-free diagnostic code."""
    return {
        "FFprobe output size is invalid": "stream_probe_output_size",
        "FFprobe returned malformed JSON": "stream_probe_malformed_json",
        "FFprobe result must be an object": "stream_probe_invalid_result",
        "FFprobe reported an invalid stream count": "stream_probe_stream_count",
        "FFprobe did not report exactly one video stream": "stream_probe_video_missing",
        "FFprobe video stream is invalid": "stream_probe_video_invalid",
        "The Core-local stream is not H.264": "stream_probe_video_codec",
        "FFprobe reported an invalid resolution": "stream_probe_resolution",
        "No bounded media was observed": "stream_probe_no_media",
        "FFprobe did not count decoded video frames": "stream_probe_video_frame_count",
        "FFprobe reported an invalid frame rate": "stream_probe_frame_rate",
        "FFprobe did not recognize the MPEG-TS container": "stream_probe_container",
        "FFprobe reported multiple audio streams": "stream_probe_audio_stream_count",
        "The Core-local audio stream is not AAC": "stream_probe_audio_codec",
        "The Core-local AAC format is unsupported": "stream_probe_audio_format",
        "FFprobe did not find the enabled audio stream": "stream_probe_audio_missing",
    }.get(str(error), "stream_probe_invalid_result")


def safe_media_probe_observation(payload: bytes) -> dict[str, Any] | None:
    """Return a bounded allowlist of non-secret FFprobe fields for diagnostics."""
    if not payload or len(payload) > _MAX_PROBE_OUTPUT:
        return None
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    streams = document.get("streams")
    if not isinstance(streams, list):
        return None

    safe_streams: list[dict[str, str | int]] = []
    for stream in streams[:3]:
        if not isinstance(stream, dict):
            continue
        safe_stream: dict[str, str | int] = {}
        for key in (
            "codec_type",
            "codec_name",
            "profile",
            "level",
            "width",
            "height",
            "avg_frame_rate",
            "nb_read_frames",
            "sample_rate",
            "channels",
        ):
            value = _safe_probe_scalar(stream.get(key))
            if value is not None:
                safe_stream[key] = value
        safe_streams.append(safe_stream)

    observation: dict[str, Any] = {
        "stream_count": len(streams),
        "streams": safe_streams,
    }
    format_section = document.get("format")
    if isinstance(format_section, dict):
        format_name = _safe_probe_scalar(format_section.get("format_name"))
        if format_name is not None:
            observation["format_name"] = format_name
    return observation


def parse_media_probe_output(
    payload: bytes,
    *,
    observed_frames: int,
    observed_bytes: int,
    observed_seconds: float,
    expect_audio: bool = False,
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
    if not isinstance(streams, list) or not 1 <= len(streams) <= 3:
        raise MediaProbeError("FFprobe reported an invalid stream count")
    video_streams = [
        item
        for item in streams
        if isinstance(item, dict)
        and (item.get("codec_type") == "video" or item.get("codec_name") == "h264")
    ]
    if len(video_streams) != 1:
        raise MediaProbeError("FFprobe did not report exactly one video stream")
    stream = video_streams[0]
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

    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    audio_streams = [
        item
        for item in streams
        if isinstance(item, dict) and item.get("codec_type") == "audio"
    ]
    if len(audio_streams) > 1:
        raise MediaProbeError("FFprobe reported multiple audio streams")
    if audio_streams:
        audio = audio_streams[0]
        audio_codec_value = audio.get("codec_name")
        sample_rate_value = audio.get("sample_rate")
        channels_value = audio.get("channels")
        if audio_codec_value not in ("aac", "aac_latm"):
            raise MediaProbeError("The Core-local audio stream is not AAC")
        if isinstance(sample_rate_value, str) and sample_rate_value.isdecimal():
            sample_rate_value = int(sample_rate_value)
        if sample_rate_value != 8000 or channels_value != 1:
            raise MediaProbeError("The Core-local AAC format is unsupported")
        audio_codec = audio_codec_value
        audio_sample_rate = sample_rate_value
        audio_channels = channels_value
    elif expect_audio:
        raise MediaProbeError("FFprobe did not find the enabled audio stream")

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
        audio_codec=audio_codec,
        audio_sample_rate=audio_sample_rate,
        audio_channels=audio_channels,
    )


def _positive_int(value: Any) -> int | None:
    """Return one strictly positive integer from FFprobe JSON."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdecimal():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _safe_probe_scalar(value: Any) -> str | int | None:
    """Allow only small numeric or constrained text values from FFprobe JSON."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value if -(2**31) <= value <= 2**31 - 1 else None
    if (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and all(character in _SAFE_TEXT_CHARACTERS for character in value)
    ):
        return value
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
