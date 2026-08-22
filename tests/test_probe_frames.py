"""Tests for the local isolated frame-probe result boundary."""

import json

import pytest

from scripts.probe_cloud import ProbeConfigurationError
from scripts.probe_frames import _validated_helper_result


def test_validated_helper_result_accepts_fixed_safe_schema() -> None:
    payload = {
        "event": "frame_probe",
        "ok": True,
        "frames": 100,
        "bytes": 700_000,
        "sps": 7,
        "pps": 7,
        "idr": 7,
        "width": 1920,
        "height": 1080,
        "estimated_fps": 12.5,
        "first_frame_ms": 800,
        "clean_shutdown": True,
    }

    assert _validated_helper_result(json.dumps(payload).encode()) == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"event": "frame_probe", "ok": False, "stage": "unknown"},
        {"event": "frame_probe", "ok": True, "uid": "forbidden-value"},
        {"event": "unexpected", "ok": True},
    ],
)
def test_validated_helper_result_rejects_unknown_or_secret_fields(payload) -> None:
    with pytest.raises(ProbeConfigurationError):
        _validated_helper_result(json.dumps(payload).encode())


@pytest.mark.parametrize("output", [b"not-json\n", b"{}\n{}\n", b""])
def test_validated_helper_result_rejects_malformed_output(output) -> None:
    with pytest.raises(ProbeConfigurationError):
        _validated_helper_result(output)
