"""Core-local FFprobe parsing tests."""

from __future__ import annotations

import json

import pytest

from custom_components.owlet_cam.runtime.media_probe import (
    MediaProbeError,
    ffprobe_binary,
    ffprobe_failure_code,
    parse_media_probe_output,
)


def _payload(**overrides: object) -> bytes:
    stream: dict[str, object] = {
        "codec_name": "h264",
        "profile": "High",
        "level": 40,
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "14/1",
        "nb_read_frames": "112",
    }
    stream.update(overrides)
    return json.dumps(
        {"streams": [stream], "format": {"format_name": "mpegts"}}
    ).encode()


def test_media_probe_parses_only_safe_bounded_facts() -> None:
    result = parse_media_probe_output(
        _payload(),
        observed_frames=112,
        observed_bytes=750_000,
        observed_seconds=8.0,
    )

    assert result.codec == "h264"
    assert result.profile == "High"
    assert result.level == 40
    assert (result.width, result.height) == (1920, 1080)
    assert result.fps == 14.0
    assert result.bitrate_kbps == 750.0
    assert result.frames == 112
    assert result.container == "mpegts"


@pytest.mark.parametrize(
    ("payload", "frames", "byte_count"),
    [
        (b"not-json", 100, 1000),
        (_payload(codec_name="hevc"), 100, 1000),
        (_payload(width=0), 100, 1000),
        (_payload(nb_read_frames="N/A"), 100, 1000),
        (_payload(), 0, 1000),
        (_payload(), 100, 0),
    ],
)
def test_media_probe_rejects_malformed_or_unobserved_media(
    payload: bytes, frames: int, byte_count: int
) -> None:
    with pytest.raises(MediaProbeError):
        parse_media_probe_output(
            payload,
            observed_frames=frames,
            observed_bytes=byte_count,
            observed_seconds=8.0,
        )


def test_ffprobe_uses_the_configured_ffmpeg_sibling() -> None:
    assert ffprobe_binary("/usr/bin/ffmpeg") == "/usr/bin/ffprobe"
    assert ffprobe_binary("ffmpeg") == "ffprobe"


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (b"Server returned 404 Not Found", "stream_probe_http_not_found"),
        (b"HTTP error 503 Service Unavailable", "stream_probe_producer_unavailable"),
        (
            b"Server returned 5XX Server Error reply",
            "stream_probe_producer_unavailable",
        ),
        (b"Server returned 4XX Client Error reply", "stream_probe_http_rejected"),
        (b"Connection refused", "stream_probe_connection_refused"),
        (b"Connection reset by peer", "stream_probe_connection_reset"),
        (b"Connection timed out", "stream_probe_timeout"),
        (b"Invalid data found when processing input", "stream_probe_invalid_media"),
        (b"Error opening input: End of file", "stream_probe_empty_stream"),
        (b"Error opening input file", "stream_probe_open_failed"),
        (b"Input/output error", "stream_probe_io_error"),
        (b"Invalid argument", "stream_probe_invalid_argument"),
        (b"Operation not permitted", "stream_probe_permission_denied"),
        (b"Unrecognized option 'rw_timeout'", "stream_probe_ffprobe_incompatible"),
        (b"sensitive-looking unknown detail", "stream_probe_ffprobe_exit"),
    ],
)
def test_ffprobe_failure_is_reduced_to_a_safe_code(
    stderr: bytes, expected: str
) -> None:
    assert ffprobe_failure_code(stderr) == expected
