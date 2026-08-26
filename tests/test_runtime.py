"""Native runtime structural gate tests."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import struct
import sys
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlsplit

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.owlet_cam.api.cloud import OwletCloudClient
from custom_components.owlet_cam.api.exceptions import (
    OwletAuthenticationError,
    OwletCameraNotFoundError,
    OwletConnectionError,
    OwletRateLimitError,
)
from custom_components.owlet_cam.api.models import OwletCameraCredentials
from custom_components.owlet_cam.runtime.apk import OwletArchiveError
from custom_components.owlet_cam.runtime.downloader import (
    RELEASE_BASE_URL,
    OwletRuntimeDownloadError,
    OwletRuntimeInstallError,
    async_ensure_release_runtime,
    install_runtime_archive,
)
from custom_components.owlet_cam.runtime.elf import (
    EM_AARCH64,
    EM_X86_64,
    ElfInspectionError,
    inspect_elf,
)
from custom_components.owlet_cam.runtime.manager import (
    _PROCESS_SESSION,
    _VALIDATION_MARKER,
    OwletRuntimeError,
    OwletRuntimeManager,
    PreparedRuntime,
    RuntimeManifest,
    _has_validation_marker,
    _prepare_directories,
    _verify_runtime,
    _write_validation_marker,
)
from custom_components.owlet_cam.runtime.process import (
    HelperProcessResult,
    OwletHelperProcessError,
    OwletHelperProcessRunner,
    _consume_audio_frames,
)
from custom_components.owlet_cam.runtime.protocol import (
    OwletHelperProtocolError,
    OwletHelperReportedError,
    parse_frame_probe_output,
    parse_library_probe_output,
    parse_snapshot_capture_output,
)
from scripts.build_helper_runtime import build_runtime_archive


def _minimal_elf(
    *,
    machine: int = EM_AARCH64,
    writable_executable: bool = False,
    include_nobits: bool = False,
    symbol_defined: bool = True,
) -> bytes:
    program_offset = 64
    section_offset = 128
    section_count = 5 if include_nobits else 4
    string_offset = section_offset + section_count * 64
    strings = b"\0libc.so\0probe_symbol\0"
    symbol_offset = string_offset + len(strings)
    dynamic_offset = symbol_offset + 48
    total_size = dynamic_offset + 32
    data = bytearray(total_size)

    identifier = bytearray(16)
    identifier[:4] = b"\x7fELF"
    identifier[4] = 2
    identifier[5] = 1
    identifier[6] = 1
    struct.pack_into(
        "<16sHHIQQQIHHHHHH",
        data,
        0,
        bytes(identifier),
        3,
        machine,
        1,
        0,
        program_offset,
        section_offset,
        0,
        64,
        56,
        1,
        64,
        section_count,
        0,
    )
    flags = 7 if writable_executable else 5
    struct.pack_into(
        "<IIQQQQQQ",
        data,
        program_offset,
        1,
        flags,
        0,
        0,
        0,
        total_size,
        total_size,
        4096,
    )

    def section(
        index: int,
        section_type: int,
        offset: int,
        size: int,
        *,
        link: int = 0,
        entry_size: int = 0,
    ) -> None:
        struct.pack_into(
            "<IIQQQQIIQQ",
            data,
            section_offset + index * 64,
            0,
            section_type,
            0,
            0,
            offset,
            size,
            link,
            0,
            1,
            entry_size,
        )

    section(0, 0, 0, 0)
    section(1, 3, string_offset, len(strings))
    section(2, 11, symbol_offset, 48, link=1, entry_size=24)
    section(3, 6, dynamic_offset, 32, link=1, entry_size=16)
    if include_nobits:
        section(4, 8, total_size + 4096, 4096)
    data[string_offset : string_offset + len(strings)] = strings
    struct.pack_into(
        "<IBBHQQ", data, symbol_offset + 24, 9, 0, 0, int(symbol_defined), 0, 0
    )
    struct.pack_into("<QQ", data, dynamic_offset, 1, 1)
    struct.pack_into("<QQ", data, dynamic_offset + 16, 0, 0)
    return bytes(data)


def test_inspects_arm64_dependencies_and_symbols(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf())

    report = inspect_elf(library, required_symbols=frozenset({"probe_symbol"}))

    assert report.architecture == "AArch64"
    assert report.dependencies == ("libc.so",)
    assert report.required_symbols_present is True
    assert report.has_writable_executable_segment is False


def test_reports_missing_required_symbol(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf())

    report = inspect_elf(library, required_symbols=frozenset({"missing"}))

    assert report.required_symbols_present is False
    assert report.missing_required_symbols == ("missing",)


def test_does_not_count_undefined_import_as_export(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf(symbol_defined=False))

    report = inspect_elf(library, required_symbols=frozenset({"probe_symbol"}))

    assert report.required_symbols_present is False


def test_rejects_wrong_architecture(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf(machine=EM_X86_64))

    with pytest.raises(ElfInspectionError, match="expected AArch64"):
        inspect_elf(library)


def test_detects_writable_executable_segment(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf(writable_executable=True))

    report = inspect_elf(library)

    assert report.has_writable_executable_segment is True


def test_accepts_nobits_section_without_file_backing(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf(include_nobits=True))

    report = inspect_elf(library)

    assert report.architecture == "AArch64"


@pytest.mark.parametrize(
    ("content", "message"),
    [(b"not-elf", "not an ELF"), (b"\x7fELF" + b"\0" * 80, "not 64-bit")],
)
def test_rejects_malformed_elf(tmp_path: Path, content: bytes, message: str) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(content)

    with pytest.raises(ElfInspectionError, match=message):
        inspect_elf(library)


def test_parses_strict_frame_probe_result() -> None:
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
        "session_mode": "lan",
        "clean_shutdown": True,
    }

    result = parse_frame_probe_output(json.dumps(payload).encode())

    assert result.frames == 100
    assert result.width == 1920
    assert result.height == 1080
    assert result.session_mode == "lan"
    assert result.clean_shutdown


def test_rejects_secret_or_unknown_frame_fields() -> None:
    payload = {"event": "frame_probe", "ok": True, "uid": "secret"}

    with pytest.raises(OwletHelperProtocolError, match="unsafe"):
        parse_frame_probe_output(json.dumps(payload).encode())


def test_maps_fixed_native_error_without_response_content() -> None:
    payload = {
        "event": "frame_probe",
        "ok": False,
        "stage": "iotc_connect",
        "native_code": -13,
    }

    with pytest.raises(OwletHelperReportedError) as caught:
        parse_frame_probe_output(json.dumps(payload).encode())

    assert caught.value.stage == "iotc_connect"
    assert caught.value.native_code == -13


def test_parses_strict_snapshot_capture_result() -> None:
    payload = {
        "event": "snapshot_capture",
        "ok": True,
        "frames": 3,
        "bytes": 120_000,
        "capture_bytes": 80_000,
        "sps": 1,
        "pps": 1,
        "idr": 1,
        "width": 1920,
        "height": 1080,
        "estimated_fps": 12.5,
        "first_frame_ms": 200,
        "session_mode": "lan",
        "clean_shutdown": True,
    }

    result = parse_snapshot_capture_output(json.dumps(payload).encode())

    assert result.capture_bytes == 80_000
    assert result.width == 1920
    assert result.clean_shutdown


@pytest.mark.parametrize(
    "update",
    [
        {"capture_bytes": 0},
        {"capture_bytes": 4 * 1024 * 1024 + 1},
        {"uid": "forbidden"},
        {"sps": 0},
        {"clean_shutdown": False},
    ],
)
def test_rejects_invalid_snapshot_capture_result(update: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "event": "snapshot_capture",
        "ok": True,
        "frames": 3,
        "bytes": 120_000,
        "capture_bytes": 80_000,
        "sps": 1,
        "pps": 1,
        "idr": 1,
        "width": 1920,
        "height": 1080,
        "estimated_fps": 12.5,
        "first_frame_ms": 200,
        "session_mode": "lan",
        "clean_shutdown": True,
    }
    payload.update(update)

    with pytest.raises(OwletHelperProtocolError):
        parse_snapshot_capture_output(json.dumps(payload).encode())


def test_parses_complete_library_probe() -> None:
    libraries = (
        "libAVAPIs.so",
        "libIOTCAPIs.so",
        "libP2PTunnelAPIs.so",
        "libRDTAPIs.so",
        "libTUTKGlobalAPIs.so",
    )
    output = b"".join(
        json.dumps({"event": "library_probe", "library": name, "ok": True}).encode()
        + b"\n"
        for name in libraries
    )
    output += b'{"event":"probe_complete","ok":true,"failures":0}\n'

    result = parse_library_probe_output(output)

    assert result.compatible
    assert result.libraries == libraries


@pytest.mark.parametrize(
    "payload",
    [
        {"event": "frame_probe", "ok": False, "stage": "unknown", "native_code": -1},
        {"event": "frame_probe", "ok": True},
        {
            "event": "frame_probe",
            "ok": True,
            "frames": -1,
            "bytes": 1,
            "sps": 1,
            "pps": 1,
            "idr": 1,
            "width": 1,
            "height": 1,
            "estimated_fps": 1.0,
            "first_frame_ms": 1,
            "session_mode": "p2p",
            "clean_shutdown": True,
        },
        {
            "event": "frame_probe",
            "ok": True,
            "frames": 1,
            "bytes": 1,
            "sps": 1,
            "pps": 1,
            "idr": 1,
            "width": 1,
            "height": 1,
            "estimated_fps": True,
            "first_frame_ms": 1,
            "session_mode": "relay",
            "clean_shutdown": True,
        },
        {
            "event": "frame_probe",
            "ok": True,
            "frames": 1,
            "bytes": 1,
            "sps": 1,
            "pps": 1,
            "idr": 1,
            "width": 1,
            "height": 1,
            "estimated_fps": 1.0,
            "first_frame_ms": 1,
            "session_mode": "unknown",
            "clean_shutdown": True,
        },
    ],
)
def test_rejects_invalid_frame_probe_shapes(payload: dict[str, object]) -> None:
    with pytest.raises(OwletHelperProtocolError):
        parse_frame_probe_output(json.dumps(payload).encode())


@pytest.mark.parametrize("output", [b"\xff", b"{}\n{}\n", b""])
def test_rejects_invalid_library_probe_shapes(output: bytes) -> None:
    with pytest.raises(OwletHelperProtocolError):
        parse_library_probe_output(output)


def test_library_probe_maps_failed_load_to_safe_error() -> None:
    output = b'{"event":"library_probe","library":"libAVAPIs.so","ok":false}\n'

    with pytest.raises(OwletHelperReportedError) as caught:
        parse_library_probe_output(output)

    assert caught.value.stage == "probe_libraries"


async def test_process_runner_scrubs_stdin_and_bounds_output(tmp_path: Path) -> None:
    runner = OwletHelperProcessRunner()
    secret = bytearray(b"fixture-private-input")
    command = (
        sys.executable,
        "-c",
        "import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'{}')",
    )

    result = await runner.async_run(
        command, stdin=secret, timeout_seconds=5, cwd=tmp_path
    )

    assert result.returncode == 0
    assert result.stdout == b"{}"
    assert secret == bytearray(len(secret))
    assert not runner.running
    assert runner.diagnostics() == {
        "active": False,
        "started_count": 1,
        "reaped_count": 1,
        "all_reaped": True,
        "forced_kill_count": 0,
        "last_exit_reason": "exited",
    }


async def test_process_runner_applies_only_explicit_non_secret_environment(
    tmp_path: Path,
) -> None:
    runner = OwletHelperProcessRunner()
    command = (
        sys.executable,
        "-c",
        "import os; print(os.environ['LD_LIBRARY_PATH'])",
    )

    result = await runner.async_run(
        command,
        timeout_seconds=5,
        cwd=tmp_path,
        environment={"LD_LIBRARY_PATH": "/runtime/lib64:/libraries"},
    )

    assert result.stdout == b"/runtime/lib64:/libraries\n"


async def test_process_runner_does_not_drain_empty_stdin_for_fast_probe(
    tmp_path: Path,
) -> None:
    """A no-input helper may exit before an empty stdin drain completes."""
    runner = OwletHelperProcessRunner()
    stdout = asyncio.StreamReader()
    stderr = asyncio.StreamReader()
    stdout.feed_eof()
    stderr.feed_eof()
    stdin_pipe = MagicMock()
    stdin_pipe.drain = AsyncMock(
        side_effect=ConnectionResetError("fast helper already exited")
    )
    stdin_pipe.wait_closed = AsyncMock()
    process = SimpleNamespace(
        stdin=stdin_pipe,
        stdout=stdout,
        stderr=stderr,
        returncode=0,
        wait=AsyncMock(return_value=0),
    )

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        result = await runner.async_run(
            (tmp_path / "probe",), timeout_seconds=5, cwd=tmp_path
        )

    assert result.returncode == 0
    stdin_pipe.write.assert_not_called()
    stdin_pipe.drain.assert_not_awaited()
    stdin_pipe.close.assert_called_once_with()
    stdin_pipe.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("command", "timeout_seconds"),
    [
        ((), 1.0),
        (("probe",), 0.0),
    ],
)
async def test_process_runner_rejects_invalid_configuration(
    command: tuple[str, ...], timeout_seconds: float
) -> None:
    runner = OwletHelperProcessRunner()

    with pytest.raises(ValueError, match="Invalid helper process configuration"):
        await runner.async_run(command, timeout_seconds=timeout_seconds)


async def test_process_runner_tolerates_closed_secret_stdin(
    tmp_path: Path,
) -> None:
    """A helper exit while stdin closes must not retain the secret payload."""
    runner = OwletHelperProcessRunner()
    secret = bytearray(b"fixture-secret")
    stdout = asyncio.StreamReader()
    stderr = asyncio.StreamReader()
    stdout.feed_eof()
    stderr.feed_eof()
    stdin_pipe = MagicMock()
    stdin_pipe.drain = AsyncMock()
    stdin_pipe.wait_closed = AsyncMock(side_effect=ConnectionResetError)
    process = SimpleNamespace(
        stdin=stdin_pipe,
        stdout=stdout,
        stderr=stderr,
        returncode=0,
        wait=AsyncMock(return_value=0),
    )

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        result = await runner.async_run(
            (tmp_path / "probe",),
            stdin=secret,
            timeout_seconds=5,
            cwd=tmp_path,
        )

    assert result.returncode == 0
    assert secret == bytearray(len(secret))
    stdin_pipe.write.assert_called_once()
    stdin_pipe.drain.assert_awaited_once_with()


async def test_process_runner_times_out_and_reaps_child(tmp_path: Path) -> None:
    runner = OwletHelperProcessRunner()
    command = (sys.executable, "-c", "import time; time.sleep(30)")

    with pytest.raises(OwletHelperProcessError, match="timed out"):
        await runner.async_run(command, timeout_seconds=0.01, cwd=tmp_path)

    assert not runner.running
    assert runner.diagnostics()["all_reaped"] is True


async def test_process_runner_stops_active_probe(tmp_path: Path) -> None:
    runner = OwletHelperProcessRunner()
    command = (sys.executable, "-c", "import time; time.sleep(30)")
    task = asyncio.create_task(
        runner.async_run(command, timeout_seconds=30, cwd=tmp_path)
    )
    for _attempt in range(100):
        if runner.running:
            break
        await asyncio.sleep(0)

    await runner.async_stop()
    result = await task

    assert result.returncode < 0
    assert not runner.running


async def test_process_runner_rejects_excess_output(tmp_path: Path) -> None:
    runner = OwletHelperProcessRunner()
    command = (
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(b'x' * 70000)",
    )

    with pytest.raises(OwletHelperProcessError, match="exceeded"):
        await runner.async_run(command, timeout_seconds=5, cwd=tmp_path)


async def test_process_runner_reports_missing_executable_safely(tmp_path: Path) -> None:
    runner = OwletHelperProcessRunner()

    with pytest.raises(OwletHelperProcessError, match="could not be started"):
        await runner.async_run((tmp_path / "missing",), timeout_seconds=1, cwd=tmp_path)


async def test_process_runner_passes_only_explicit_media_descriptor(
    tmp_path: Path,
) -> None:
    runner = OwletHelperProcessRunner()
    read_descriptor, write_descriptor = os.pipe()
    command = (
        sys.executable,
        "-c",
        "import os,sys; os.write(int(sys.argv[1]), b'capture')",
        str(write_descriptor),
    )
    try:
        result = await runner.async_run(
            command,
            timeout_seconds=5,
            cwd=tmp_path,
            pass_fds=(write_descriptor,),
        )
        os.close(write_descriptor)
        write_descriptor = -1

        assert result.returncode == 0
        assert os.read(read_descriptor, 7) == b"capture"
    finally:
        os.close(read_descriptor)
        if write_descriptor >= 0:
            os.close(write_descriptor)


async def test_process_runner_streams_length_framed_media_and_scrubs_stdin(
    tmp_path: Path,
) -> None:
    runner = OwletHelperProcessRunner()
    payload = bytearray(b"fixture-secret\n")
    received: list[bytes] = []

    async def receive(frame: bytes) -> None:
        received.append(frame)

    command = (
        sys.executable,
        "-c",
        "import sys; sys.stdin.buffer.read(); data=b'\\x00\\x00\\x00\\x01\\x65frame'; "
        "sys.stdout.buffer.write(len(data).to_bytes(4,'big')+data); "
        "sys.stdout.buffer.flush(); sys.stderr.buffer.write(b'{\\\"ok\\\":true}\\n')",
    )

    status = await runner.async_stream(
        command,
        stdin=payload,
        no_frame_timeout=5,
        on_frame=receive,
        cwd=tmp_path,
    )

    assert received == [b"\x00\x00\x00\x01\x65frame"]
    assert status == b'{"ok":true}\n'
    assert payload == bytearray(len(payload))
    assert not runner.running


async def test_process_runner_drains_audio_from_a_separate_inherited_pipe(
    tmp_path: Path,
) -> None:
    runner = OwletHelperProcessRunner()
    payload = bytearray(b"fixture-secret\n")
    video: list[bytes] = []
    audio: list[tuple[int, bytes]] = []
    read_descriptor, write_descriptor = os.pipe()

    async def receive_video(frame: bytes) -> None:
        video.append(frame)

    async def receive_audio(codec_id: int, frame: bytes) -> None:
        audio.append((codec_id, frame))

    command = (
        sys.executable,
        "-c",
        "import os,sys; sys.stdin.buffer.read(); "
        "v=b'\\x00\\x00\\x00\\x01\\x65frame'; a=b'aac'; "
        "h=len(a).to_bytes(4,'big')+b'\\x00\\x86\\x00\\x00'; "
        "os.write(int(sys.argv[1]), h+a); "
        "os.close(int(sys.argv[1])); "
        "sys.stdout.buffer.write(len(v).to_bytes(4,'big')+v); "
        "sys.stdout.buffer.flush(); sys.stderr.buffer.write(b'{\\\"ok\\\":true}\\n')",
        str(write_descriptor),
    )

    status = await runner.async_stream(
        command,
        stdin=payload,
        no_frame_timeout=5,
        on_frame=receive_video,
        audio_pipe=(read_descriptor, write_descriptor),
        on_audio_frame=receive_audio,
        cwd=tmp_path,
    )

    assert video == [b"\x00\x00\x00\x01\x65frame"]
    assert audio == [(0x86, b"aac")]
    assert status == b'{"ok":true}\n'
    assert payload == bytearray(len(payload))
    assert runner.diagnostics()["all_reaped"] is True


async def test_malformed_audio_does_not_terminate_video_stream(tmp_path: Path) -> None:
    runner = OwletHelperProcessRunner()
    read_descriptor, write_descriptor = os.pipe()
    received: list[bytes] = []
    errors: list[str] = []

    async def receive(frame: bytes) -> None:
        received.append(frame)

    async def audio_error(code: str) -> None:
        errors.append(code)

    command = (
        sys.executable,
        "-c",
        "import os,sys; sys.stdin.buffer.read(); "
        "os.write(int(sys.argv[1]), b'\\xff\\xff\\xff\\xff\\x00\\x86\\x00\\x00'); "
        "os.close(int(sys.argv[1])); v=b'video'; "
        "sys.stdout.buffer.write(len(v).to_bytes(4,'big')+v); "
        "sys.stdout.buffer.flush()",
        str(write_descriptor),
    )

    await runner.async_stream(
        command,
        stdin=bytearray(b"secret\n"),
        no_frame_timeout=5,
        on_frame=receive,
        audio_pipe=(read_descriptor, write_descriptor),
        on_audio_frame=AsyncMock(),
        on_audio_error=audio_error,
        cwd=tmp_path,
    )

    assert received == [b"video"]
    assert errors == ["audio_invalid_frame"]


async def test_audio_consumer_reduces_callback_and_truncation_failures() -> None:
    callback_reader = asyncio.StreamReader()
    callback_reader.feed_data(
        b"\x00\x00\x00\x03\x00\x86\x00\x00aac\x00\x00\x00\x03\x00\x86\x00\x00aac"
    )
    callback_reader.feed_eof()
    callback_errors: list[str] = []

    async def record_callback_error(code: str) -> None:
        callback_errors.append(code)

    callback = AsyncMock(side_effect=RuntimeError("fixture failure"))
    await _consume_audio_frames(
        callback_reader,
        on_audio_frame=callback,
        on_audio_error=record_callback_error,
    )

    truncated_reader = asyncio.StreamReader()
    truncated_reader.feed_data(b"\x00\x00\x00\x03\x00\x86\x00\x00aa")
    truncated_reader.feed_eof()
    truncated_errors: list[str] = []

    async def record_truncated_error(code: str) -> None:
        truncated_errors.append(code)

    await _consume_audio_frames(
        truncated_reader,
        on_audio_frame=AsyncMock(),
        on_audio_error=record_truncated_error,
    )

    assert callback_errors == ["audio_publish_failed"]
    assert callback.await_count == 1
    assert truncated_errors == ["audio_incomplete_frame"]


async def test_process_runner_terminates_stream_after_no_frame_timeout(
    tmp_path: Path,
) -> None:
    runner = OwletHelperProcessRunner()
    payload = bytearray(b"fixture-secret\n")
    command = (
        sys.executable,
        "-c",
        "import sys,time; sys.stdin.buffer.read(); time.sleep(10)",
    )

    with pytest.raises(OwletHelperProcessError, match="no media frames") as caught:
        await runner.async_stream(
            command,
            stdin=payload,
            no_frame_timeout=0.01,
            on_frame=AsyncMock(),
            cwd=tmp_path,
        )

    assert payload == bytearray(len(payload))
    assert not runner.running
    assert caught.value.code == "stream_no_frames"
    assert runner.diagnostics()["all_reaped"] is True


def _library_probe_output() -> bytes:
    libraries = (
        "libAVAPIs.so",
        "libIOTCAPIs.so",
        "libP2PTunnelAPIs.so",
        "libRDTAPIs.so",
        "libTUTKGlobalAPIs.so",
    )
    output = b"".join(
        json.dumps({"event": "library_probe", "library": name, "ok": True}).encode()
        + b"\n"
        for name in libraries
    )
    return output + b'{"event":"probe_complete","ok":true,"failures":0}\n'


def _frame_probe_output() -> bytes:
    return json.dumps(
        {
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
            "session_mode": "p2p",
            "clean_shutdown": True,
        }
    ).encode()


def _snapshot_capture_output(capture_bytes: int) -> bytes:
    return json.dumps(
        {
            "event": "snapshot_capture",
            "ok": True,
            "frames": 3,
            "bytes": capture_bytes,
            "capture_bytes": capture_bytes,
            "sps": 1,
            "pps": 1,
            "idr": 1,
            "width": 1920,
            "height": 1080,
            "estimated_fps": 12.5,
            "first_frame_ms": 200,
            "session_mode": "lan",
            "clean_shutdown": True,
        }
    ).encode()


def _runtime_tree(root: Path) -> None:
    files = (
        "bin/frame_probe",
        "bin/probe_libraries",
        "bin/snapshot_capture",
        "runtime/bin/linker64",
        "runtime/lib64/libc.so",
        "runtime/lib64/libdl.so",
        "runtime/lib64/libm.so",
    )
    hashes: dict[str, str] = {}
    for index, relative in enumerate(files):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"fixture-runtime-{index}".encode()
        path.write_bytes(content)
        hashes[relative] = hashlib.sha256(content).hexdigest()
    (root / "runtime-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": "0.4.0-test",
                "architecture": "aarch64",
                "files": hashes,
            }
        )
    )


def test_verifies_checksum_pinned_runtime_tree(tmp_path: Path) -> None:
    root = tmp_path / "current"
    _runtime_tree(root)

    manifest = _verify_runtime(root)

    assert manifest.version == "0.4.0-test"
    assert manifest.architecture == "aarch64"


def test_rejects_symlinked_runtime_storage(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "userfiles"
    root.mkdir()
    (root / "uploads").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OwletRuntimeError) as caught:
        _prepare_directories(root)

    assert caught.value.code == "invalid_runtime_storage"


def test_rejects_runtime_checksum_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "current"
    _runtime_tree(root)
    (root / "bin/frame_probe").write_bytes(b"changed")

    with pytest.raises(OwletRuntimeError) as caught:
        _verify_runtime(root)

    assert caught.value.code == "runtime_checksum_mismatch"


async def test_runtime_manager_runs_gates_and_scrubs_on_unload(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime" / "current"
    _runtime_tree(runtime_root)
    prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.4.0-test", architecture="aarch64", root=runtime_root
        ),
        library_directory=tmp_path / "extracted",
        libraries=(),
        source_sha256="0" * 64,
    )
    sdk_key = bytearray(b"AQ" + b"x" * 40)
    runner = AsyncMock(spec=OwletHelperProcessRunner)
    runner.async_run.side_effect = (
        HelperProcessResult(returncode=0, stdout=_library_probe_output()),
        HelperProcessResult(returncode=0, stdout=_frame_probe_output()),
    )
    client = AsyncMock(spec=OwletCloudClient)
    client.async_get_camera_credentials.return_value = OwletCameraCredentials(
        uid="fixture-uid",
        auth_key="fixture-auth-key",
        av_password="fixture-av-password",  # noqa: S106 - sanitized fixture
    )
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=client,
        camera_identifier="OCD123456789",
        runner=runner,
    )

    with patch.object(manager, "_prepare_sync", return_value=(prepared, sdk_key)):
        libraries = await manager.async_prepare_and_probe_libraries()
    frame = await manager.async_run_frame_probe()

    assert libraries.compatible
    assert manager.frame_probe_available
    assert frame.frames == 100
    marker = tmp_path / "userfiles" / "state" / _VALIDATION_MARKER
    assert _has_validation_marker(marker)
    assert marker.stat().st_mode & 0o777 == 0o600
    assert frame.width == 1920
    for call in runner.async_run.await_args_list:
        command = call.args[0]
        assert "--library-path" not in command
        assert command[0].endswith("runtime/bin/linker64")
        assert set(call.kwargs["environment"]) == {"LD_LIBRARY_PATH"}
        assert "runtime/lib64" in call.kwargs["environment"]["LD_LIBRARY_PATH"]
    diagnostics = json.dumps(manager.diagnostics())
    for secret in (
        "fixture-uid",
        "fixture-auth-key",
        "fixture-av-password",
        sdk_key.decode(),
    ):
        assert secret not in diagnostics

    await manager.async_shutdown()

    runner.async_stop.assert_awaited_once()
    assert sdk_key == bytearray(len(sdk_key))
    assert manager.snapshot.status == "stopped"
    assert not manager.frame_probe_available


async def test_runtime_restore_requires_prior_explicit_validation(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """Only an exact private consent marker enables automatic revalidation."""
    root = tmp_path / "userfiles"
    manager = OwletRuntimeManager(
        hass,
        root=root,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )
    with patch.object(
        manager, "async_prepare_and_probe_libraries", new_callable=AsyncMock
    ) as restore:
        manager.async_schedule_previous_validation_restore()
        restore_task = manager._restore_task
        assert restore_task is not None
        await restore_task
    restore.assert_not_awaited()

    marker = root / "state" / _VALIDATION_MARKER
    _write_validation_marker(marker)
    assert _has_validation_marker(marker)
    marker.write_bytes(b'{"prior_explicit_runtime_validation":false}\n')
    assert not _has_validation_marker(marker)
    _write_validation_marker(marker)

    restored_manager = OwletRuntimeManager(
        hass,
        root=root,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )
    with patch.object(
        restored_manager,
        "async_prepare_and_probe_libraries",
        new_callable=AsyncMock,
    ) as restore:
        hass.set_state(CoreState.running)
        restored_manager.async_schedule_previous_validation_restore()
        restore_task = restored_manager._restore_task
        assert restore_task is not None
        await restore_task
    restore.assert_awaited_once_with()


async def test_runtime_restore_waits_for_home_assistant_start(
    hass: HomeAssistant, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Cold-start revalidation waits until constrained Core startup settles."""
    root = tmp_path / "userfiles"
    _write_validation_marker(root / "state" / _VALIDATION_MARKER)
    manager = OwletRuntimeManager(
        hass,
        root=root,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )
    hass.set_state(CoreState.starting)
    with patch.object(
        manager, "async_prepare_and_probe_libraries", new_callable=AsyncMock
    ) as restore:
        manager.async_schedule_previous_validation_restore()
        await asyncio.sleep(0)
        restore.assert_not_awaited()

        hass.set_state(CoreState.running)
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        restore_task = manager._restore_task
        assert restore_task is not None
        await restore_task

    restore.assert_awaited_once_with()
    assert "Unable to remove unknown job listener" not in caplog.text


async def test_frame_probe_is_gated_until_libraries_pass(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )

    with pytest.raises(OwletRuntimeError) as caught:
        await manager.async_run_frame_probe()

    assert caught.value.code == "runtime_not_ready"


async def test_runtime_manager_captures_decodes_and_deletes_private_gop(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime" / "current"
    _runtime_tree(runtime_root)
    prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.5.0-test", architecture="aarch64", root=runtime_root
        ),
        library_directory=tmp_path / "extracted",
        libraries=(),
        source_sha256="0" * 64,
    )
    captured = b"\x00\x00\x00\x01\x67fixture-h264"
    runner = AsyncMock(spec=OwletHelperProcessRunner)

    async def run_helper(*_args: object, **kwargs: object) -> HelperProcessResult:
        descriptor = kwargs["pass_fds"][0]  # type: ignore[index]
        os.write(descriptor, captured)
        return HelperProcessResult(
            returncode=0, stdout=_snapshot_capture_output(len(captured))
        )

    runner.async_run.side_effect = run_helper
    client = AsyncMock(spec=OwletCloudClient)
    client.async_get_camera_credentials.return_value = OwletCameraCredentials(
        uid="fixture-uid",
        auth_key="fixture-auth-key",
        av_password="fixture-av-password",  # noqa: S106 - sanitized fixture
    )
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=client,
        camera_identifier="OCD123456789",
        runner=runner,
    )
    manager._prepared = prepared
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True
    manager.snapshot.status = "ready"
    capture_path: Path | None = None

    async def decode(path: Path) -> bytes:
        nonlocal capture_path
        capture_path = path
        contents = await hass.async_add_executor_job(path.read_bytes)
        mode = await hass.async_add_executor_job(lambda: path.stat().st_mode)
        assert contents == captured
        assert mode & 0o777 == 0o600
        return b"\xff\xd8fixture-jpeg\xff\xd9"

    image = await manager.async_capture_snapshot(decode)

    assert image == b"\xff\xd8fixture-jpeg\xff\xd9"
    assert capture_path is not None
    assert not await hass.async_add_executor_job(capture_path.exists)
    assert manager.snapshot.status == "ready"
    assert manager.snapshot.last_snapshot_width == 1920
    assert manager.snapshot.last_snapshot_height == 1080
    call = runner.async_run.await_args
    assert call.args[0][1].endswith("bin/snapshot_capture")
    assert call.kwargs["pass_fds"]
    command_line = " ".join(str(part) for part in call.args[0])
    environment = json.dumps(call.kwargs["environment"])
    for secret in (
        "fixture-uid",
        "fixture-auth-key",
        "fixture-av-password",
    ):
        assert secret not in command_line
        assert secret not in environment


async def test_runtime_manager_rejects_missing_snapshot_output_and_cleans_file(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime" / "current"
    _runtime_tree(runtime_root)
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
        runner=AsyncMock(spec=OwletHelperProcessRunner),
    )
    manager._prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.5.0-test", architecture="aarch64", root=runtime_root
        ),
        library_directory=tmp_path / "extracted",
        libraries=(),
        source_sha256="0" * 64,
    )
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True
    manager.snapshot.status = "ready"
    manager._client.async_get_camera_credentials.return_value = OwletCameraCredentials(
        uid="fixture-uid",
        auth_key="fixture-auth-key",
        av_password="fixture-av-password",  # noqa: S106
    )
    manager._runner.async_run.return_value = HelperProcessResult(
        returncode=0, stdout=_snapshot_capture_output(100)
    )

    with pytest.raises(OwletRuntimeError) as caught:
        await manager.async_capture_snapshot(AsyncMock(return_value=b"unused"))

    assert caught.value.code == "snapshot_capture_failed"
    assert manager.snapshot.status == "ready"
    assert manager.snapshot_available
    snapshot_directory = tmp_path / "userfiles" / "tmp"
    files = await hass.async_add_executor_job(
        lambda: list(snapshot_directory.glob("snapshot-*.h264"))
    )
    assert not files


@pytest.mark.parametrize(
    ("cloud_error", "expected_code"),
    [
        (OwletRateLimitError("limited"), "cloud_rate_limited"),
        (OwletAuthenticationError(), "reauthentication_required"),
        (OwletConnectionError(), "cloud_connection_failed"),
        (OwletCameraNotFoundError(), "camera_unavailable"),
    ],
)
async def test_snapshot_cloud_failure_is_safe_and_retryable(
    hass: HomeAssistant,
    tmp_path: Path,
    cloud_error: Exception,
    expected_code: str,
) -> None:
    runtime_root = tmp_path / "runtime" / "current"
    _runtime_tree(runtime_root)
    client = AsyncMock(spec=OwletCloudClient)
    client.async_get_camera_credentials.side_effect = cloud_error
    runner = AsyncMock(spec=OwletHelperProcessRunner)
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=client,
        camera_identifier="OCD123456789",
        runner=runner,
    )
    manager._prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.5.0-test", architecture="aarch64", root=runtime_root
        ),
        library_directory=tmp_path / "extracted",
        libraries=(),
        source_sha256="0" * 64,
    )
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True

    with pytest.raises(OwletRuntimeError) as caught:
        await manager.async_capture_snapshot(AsyncMock(return_value=b"unused"))

    assert caught.value.code == expected_code
    assert manager.snapshot.last_error_code == expected_code
    assert manager.snapshot.status == "ready"
    assert manager.snapshot_available
    runner.async_run.assert_not_called()
    snapshot_directory = tmp_path / "userfiles" / "tmp"
    assert not list(snapshot_directory.glob("snapshot-*.h264"))


async def test_snapshot_decode_timeout_is_safe_and_retryable(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime" / "current"
    _runtime_tree(runtime_root)
    captured = b"\x00\x00\x00\x01\x67fixture-h264"
    runner = AsyncMock(spec=OwletHelperProcessRunner)

    async def run_helper(*_args: object, **kwargs: object) -> HelperProcessResult:
        os.write(kwargs["pass_fds"][0], captured)  # type: ignore[index]
        return HelperProcessResult(
            returncode=0, stdout=_snapshot_capture_output(len(captured))
        )

    runner.async_run.side_effect = run_helper
    client = AsyncMock(spec=OwletCloudClient)
    client.async_get_camera_credentials.return_value = OwletCameraCredentials(
        uid="fixture-uid",
        auth_key="fixture-auth-key",
        av_password="fixture-av-password",  # noqa: S106
    )
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=client,
        camera_identifier="OCD123456789",
        runner=runner,
    )
    manager._prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.5.0-test", architecture="aarch64", root=runtime_root
        ),
        library_directory=tmp_path / "extracted",
        libraries=(),
        source_sha256="0" * 64,
    )
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True

    with pytest.raises(OwletRuntimeError) as caught:
        await manager.async_capture_snapshot(
            AsyncMock(side_effect=TimeoutError("fixture timeout"))
        )

    assert caught.value.code == "snapshot_decode_timeout"
    assert manager.snapshot.last_error_code == "snapshot_decode_timeout"
    assert manager.snapshot.status == "ready"
    assert manager.snapshot_available


async def test_runtime_manager_fans_out_one_live_camera_session_and_idles(
    hass: HomeAssistant, tmp_path: Path, socket_enabled: None
) -> None:
    runtime_root = tmp_path / "runtime" / "current"
    _runtime_tree(runtime_root)
    release = asyncio.Event()
    started = asyncio.Event()
    runner = AsyncMock(spec=OwletHelperProcessRunner)

    async def stream_helper(*_args: object, **kwargs: object) -> bytes:
        started.set()
        on_frame = kwargs["on_frame"]
        await on_frame(
            b"\x00\x00\x00\x01\x67sps\x00\x00\x01\x68pps\x00\x00\x00\x01\x65idr"
        )
        await release.wait()
        return b'{"event":"stream_capture","ok":true}\n'

    async def stop_helper() -> None:
        release.set()

    runner.async_stream.side_effect = stream_helper
    runner.async_stop.side_effect = stop_helper
    client = AsyncMock(spec=OwletCloudClient)
    client.async_get_camera_credentials.return_value = OwletCameraCredentials(
        uid="fixture-uid",
        auth_key="fixture-auth-key",
        av_password="fixture-av-password",  # noqa: S106
    )
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=client,
        camera_identifier="OCD123456789",
        runner=runner,
        idle_disconnect_timeout=0,
        reconnect_backoff=0,
    )
    manager._prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.6.0-test",
            architecture="aarch64",
            root=runtime_root,
            files=frozenset({"bin/stream_capture"}),
        ),
        library_directory=tmp_path / "extracted",
        libraries=(),
        source_sha256="0" * 64,
        stream_helper_available=True,
    )
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True
    manager.snapshot.status = "ready"
    healthy = asyncio.Event()
    idle = asyncio.Event()

    def state_changed() -> None:
        if manager.snapshot.stream_healthy:
            healthy.set()
        if manager.snapshot.stream_status == "idle":
            idle.set()

    manager.async_add_listener(state_changed)

    url = await manager.async_get_stream_source()
    parsed = urlsplit(url)
    assert parsed.hostname == "127.0.0.1"
    first_reader, first_writer = await asyncio.open_connection("127.0.0.1", parsed.port)
    request = f"GET {parsed.path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
    first_writer.write(request)
    await first_writer.drain()
    assert b"200 OK" in await first_reader.readuntil(b"\r\n\r\n")
    async with asyncio.timeout(1):
        await started.wait()
        await healthy.wait()

    second_reader, second_writer = await asyncio.open_connection(
        "127.0.0.1", parsed.port
    )
    second_writer.write(request)
    await second_writer.drain()
    assert b"200 OK" in await second_reader.readuntil(b"\r\n\r\n")
    assert manager.snapshot.stream_status == "streaming"
    assert runner.async_stream.await_count == 1
    assert client.async_get_camera_credentials.await_count == 1

    diagnostics = json.dumps(manager.diagnostics())
    assert "127.0.0.1" in diagnostics
    assert parsed.path not in diagnostics
    for secret in (
        "fixture-uid",
        "fixture-auth-key",
        "fixture-av-password",
        manager._sdk_key.decode(),
    ):
        assert secret not in diagnostics

    first_writer.close()
    second_writer.close()
    await first_writer.wait_closed()
    await second_writer.wait_closed()
    async with asyncio.timeout(2):
        await idle.wait()
    assert not manager.snapshot.stream_active
    assert not manager.snapshot.stream_healthy
    runner.async_stop.assert_awaited_once()

    await manager.async_shutdown()
    assert manager.stream_source_url is None


async def test_runtime_manager_tracks_audio_without_changing_video_health(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
        runner=AsyncMock(spec=OwletHelperProcessRunner),
        enable_audio=True,
    )
    await manager._stream_server.async_publish(
        b"\x00\x00\x00\x01\x67sps\x00\x00\x01\x68pps\x00\x00\x00\x01\x65idr"
    )

    await manager._async_publish_stream_audio(0x86, b"raw-aac")

    assert manager.snapshot.stream_healthy is False
    assert manager._stream_server.healthy is True
    assert manager.snapshot.audio_status == "streaming"
    assert manager.snapshot.audio_codec_id == 0x86
    assert manager.snapshot.audio_frames == 1
    assert manager.diagnostics()["stream"]["audio"] == {
        "enabled": True,
        "status": "streaming",
        "codec_id": "0x0086",
        "codec": "aac_raw",
        "sample_rate": 8000,
        "channels": 1,
        "frames": 1,
        "bytes": 7,
        "last_frame_at": manager.snapshot.audio_last_frame_at.isoformat(),
        "last_error_code": None,
    }

    await manager._async_publish_stream_audio(0x8A, b"unsupported")
    assert manager.snapshot.audio_status == "unavailable"
    assert manager.snapshot.audio_codec_id == 0x8A
    assert manager.snapshot.audio_last_error_code == "audio_codec_unsupported"
    assert manager.diagnostics()["stream"]["audio"] == {
        "enabled": True,
        "status": "unavailable",
        "codec_id": "0x008a",
        "codec": None,
        "sample_rate": None,
        "channels": None,
        "frames": 1,
        "bytes": 7,
        "last_frame_at": manager.snapshot.audio_last_frame_at.isoformat(),
        "last_error_code": "audio_codec_unsupported",
    }
    assert manager._stream_server.healthy is True

    await manager._async_publish_stream_audio(0x88, b"latm-labelled-raw-aac")
    assert manager.snapshot.audio_status == "streaming"
    assert manager.snapshot.audio_codec_id == 0x88
    assert manager.snapshot.audio_frames == 2
    assert manager.diagnostics()["stream"]["audio"]["codec"] == "aac_latm"


async def test_live_stream_requires_the_versioned_stream_helper(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )
    manager._prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.5.0-test", architecture="aarch64", root=tmp_path
        ),
        library_directory=tmp_path,
        libraries=(),
        source_sha256="0" * 64,
    )
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True
    manager.snapshot.status = "ready"

    assert manager.snapshot_available
    assert not manager.stream_available
    with pytest.raises(OwletRuntimeError) as caught:
        await manager.async_get_stream_source()
    assert caught.value.code == "stream_runtime_missing"
    await manager.async_shutdown()
    assert not list((tmp_path / "userfiles" / "tmp").glob("snapshot-*.h264"))


async def test_core_stream_probe_uses_bounded_secret_free_ffprobe(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    runner = AsyncMock(spec=OwletHelperProcessRunner)
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
        runner=runner,
    )
    manager._prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.6.0-test", architecture="aarch64", root=tmp_path
        ),
        library_directory=tmp_path,
        libraries=(),
        source_sha256="0" * 64,
        stream_helper_available=True,
    )
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True
    manager.snapshot.status = "ready"
    source = "http://127.0.0.1:43210/owlet-cam.ts"
    process = MagicMock()
    process.returncode = 0

    async def communicate() -> tuple[bytes, bytes]:
        manager.snapshot.stream_frames += 112
        manager.snapshot.stream_bytes += 750_000
        return (
            json.dumps(
                {
                    "streams": [
                        {
                            "codec_name": "h264",
                            "profile": "High",
                            "level": 40,
                            "width": 1920,
                            "height": 1080,
                            "avg_frame_rate": "14/1",
                            "nb_read_frames": "112",
                        }
                    ],
                    "format": {"format_name": "mpegts"},
                }
            ).encode(),
            b"",
        )

    process.communicate = AsyncMock(side_effect=communicate)
    process.wait = AsyncMock()
    manager.async_get_stream_source = AsyncMock(return_value=source)  # type: ignore[method-assign]

    with (
        patch(
            "custom_components.owlet_cam.runtime.manager.get_ffmpeg_manager",
            return_value=SimpleNamespace(binary="/usr/bin/ffmpeg"),
        ),
        patch(
            "custom_components.owlet_cam.runtime.manager.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ) as create_process,
    ):
        result = await manager.async_run_stream_probe()

    assert result.codec == "h264"
    assert result.profile == "High"
    assert result.bitrate_kbps > 0
    assert manager.snapshot.last_stream_probe == result
    assert manager.snapshot.last_stream_probe_at is not None
    assert manager.snapshot.last_stream_probe_observation == {
        "stream_count": 1,
        "streams": [
            {
                "codec_name": "h264",
                "profile": "High",
                "level": 40,
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "14/1",
                "nb_read_frames": "112",
            }
        ],
        "format_name": "mpegts",
    }
    assert manager.snapshot.status == "ready"
    command = create_process.await_args.args
    assert command[0] == "/usr/bin/ffprobe"
    assert source in command
    serialized = repr(create_process.await_args)
    for secret in ("fixture-uid", "fixture-auth-key", manager._sdk_key.decode()):
        assert secret not in serialized
    runner.async_stop.assert_awaited_once()


async def test_stream_probe_status_does_not_reject_its_first_consumer(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    runner = AsyncMock(spec=OwletHelperProcessRunner)
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
        runner=runner,
    )
    manager._prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.6.0-test", architecture="aarch64", root=tmp_path
        ),
        library_directory=tmp_path,
        libraries=(),
        source_sha256="0" * 64,
        stream_helper_available=True,
    )
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True
    manager.snapshot.status = "stream_probe_running"
    manager._async_stream_loop = AsyncMock()  # type: ignore[method-assign]

    assert not manager.stream_available
    await manager._async_stream_client_connected()
    await asyncio.sleep(0)

    manager._async_stream_loop.assert_awaited_once()
    assert not manager._stream_server.healthy
    await manager.async_stop_stream()


async def test_live_stream_recovers_after_helper_failure_with_fresh_credentials(
    hass: HomeAssistant,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime_root = tmp_path / "runtime" / "current"
    _runtime_tree(runtime_root)
    release = asyncio.Event()
    healthy = asyncio.Event()
    runner = AsyncMock(spec=OwletHelperProcessRunner)
    attempts = 0

    async def recovered_stream(*_args: object, **kwargs: object) -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OwletHelperProcessError(
                "Native stream helper failed", code="stream_helper_failed"
            )
        await kwargs["on_frame"](
            b"\x00\x00\x00\x01\x67sps\x00\x00\x01\x68pps\x00\x00\x00\x01\x65idr"
        )
        healthy.set()
        await release.wait()
        return b'{"event":"stream_capture","ok":true}\n'

    runner.async_stream.side_effect = recovered_stream
    runner.async_stop.side_effect = lambda: release.set()
    client = AsyncMock(spec=OwletCloudClient)
    client.async_get_camera_credentials.return_value = OwletCameraCredentials(
        uid="fixture-uid",
        auth_key="fixture-auth-key",
        av_password="fixture-av-password",  # noqa: S106
    )
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=client,
        camera_identifier="OCD123456789",
        runner=runner,
        reconnect_backoff=0,
    )
    manager._prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.6.0-test", architecture="aarch64", root=runtime_root
        ),
        library_directory=tmp_path / "extracted",
        libraries=(),
        source_sha256="0" * 64,
        stream_helper_available=True,
    )
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True
    manager.snapshot.status = "ready"
    caplog.set_level("WARNING", logger="custom_components.owlet_cam.runtime.manager")

    await manager._async_stream_client_connected()
    async with asyncio.timeout(1):
        await healthy.wait()

    assert runner.async_stream.await_count == 2
    assert client.async_get_camera_credentials.await_count == 2
    assert manager.snapshot.stream_reconnect_count == 1
    assert manager.snapshot.stream_healthy
    assert manager.snapshot.last_error_code is None
    assert manager.snapshot.stream_last_interruption_code == "stream_helper_failed"
    assert manager.snapshot.stream_last_interruption_at is not None
    assert manager.snapshot.stream_last_recovery_at is not None
    assert manager.snapshot.stream_session_count == 2
    assert "stream_helper_failed" in caplog.text
    diagnostics = manager.diagnostics()
    assert diagnostics["stream"]["last_interruption_code"] == ("stream_helper_failed")
    assert "pid" not in json.dumps(diagnostics).lower()

    await manager.async_stop_stream()
    assert manager.snapshot.stream_status == "idle"
    await manager.async_shutdown()


def test_native_helper_arms_linux_parent_death_supervision() -> None:
    """A Core crash must not leave a newly built native helper orphaned."""
    source = (
        Path(__file__).parents[1] / "helper" / "src" / "frame_probe.c"
    ).read_text()

    assert "PR_SET_PDEATHSIG" in source
    assert "arm_parent_death_signal()" in source
    assert 'emit_error("parent_supervision", -1)' in source


async def test_frame_probe_cloud_failure_has_safe_error_state(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime" / "current"
    _runtime_tree(runtime_root)
    client = AsyncMock(spec=OwletCloudClient)
    client.async_get_camera_credentials.side_effect = OwletRateLimitError("limited")
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=client,
        camera_identifier="OCD123456789",
        runner=AsyncMock(spec=OwletHelperProcessRunner),
    )
    manager._prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.5.0-test", architecture="aarch64", root=runtime_root
        ),
        library_directory=tmp_path / "extracted",
        libraries=(),
        source_sha256="0" * 64,
    )
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True

    with pytest.raises(OwletRuntimeError) as caught:
        await manager.async_run_frame_probe()

    assert caught.value.code == "cloud_rate_limited"
    assert manager.snapshot.last_error_code == "cloud_rate_limited"
    assert manager.snapshot.status == "error"


async def test_runtime_shutdown_during_snapshot_cannot_restore_ready_state(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime" / "current"
    _runtime_tree(runtime_root)
    runner = AsyncMock(spec=OwletHelperProcessRunner)
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def run_helper(*_args: object, **_kwargs: object) -> HelperProcessResult:
        started.set()
        await stopped.wait()
        raise OwletHelperProcessError("stopped")

    async def stop_helper() -> None:
        stopped.set()

    runner.async_run.side_effect = run_helper
    runner.async_stop.side_effect = stop_helper
    client = AsyncMock(spec=OwletCloudClient)
    client.async_get_camera_credentials.return_value = OwletCameraCredentials(
        uid="fixture-uid",
        auth_key="fixture-auth-key",
        av_password="fixture-av-password",  # noqa: S106
    )
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path / "userfiles",
        client=client,
        camera_identifier="OCD123456789",
        runner=runner,
    )
    manager._prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.5.0-test", architecture="aarch64", root=runtime_root
        ),
        library_directory=tmp_path / "extracted",
        libraries=(),
        source_sha256="0" * 64,
    )
    manager._sdk_key = bytearray(b"AQ" + b"x" * 40)
    manager.snapshot.libraries_compatible = True
    task = asyncio.create_task(
        manager.async_capture_snapshot(
            AsyncMock(return_value=b"\xff\xd8fixture-jpeg\xff\xd9")
        )
    )
    await started.wait()

    await manager.async_shutdown()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.snapshot.status == "stopped"
    assert not manager.snapshot_available


def test_yellow_architecture_alias_is_supported(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )

    with patch("platform.machine", return_value="arm64"):
        assert manager.supported_architecture


def test_runtime_preparation_cleans_only_previous_process_extractions(
    tmp_path: Path,
) -> None:
    temporary = tmp_path / "tmp"
    stale = temporary / "extract-previous-process"
    current = temporary / f"extract-{_PROCESS_SESSION}-active"
    unrelated = temporary / "owned-by-user"
    for path in (stale, current, unrelated):
        path.mkdir(parents=True, exist_ok=True)
        (path / "fixture").write_text("fixture")

    _prepare_directories(tmp_path)

    assert not stale.exists()
    assert current.is_dir()
    assert unrelated.is_dir()


def test_helper_runtime_archive_is_reproducible_and_proprietary_free(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime-source"
    for relative in (
        "bin/linker64",
        "lib64/libc.so",
        "lib64/libdl.so",
        "lib64/libm.so",
    ):
        path = runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"open-source-{relative}".encode())
    frame_probe = tmp_path / "frame_probe"
    snapshot_capture = tmp_path / "snapshot_capture"
    stream_capture = tmp_path / "stream_capture"
    library_probe = tmp_path / "probe_libraries"
    notice = tmp_path / "NOTICE.html.gz"
    frame_probe.write_bytes(b"clean-room-frame-helper")
    snapshot_capture.write_bytes(b"clean-room-snapshot-helper")
    stream_capture.write_bytes(b"clean-room-stream-helper")
    library_probe.write_bytes(b"clean-room-library-helper")
    notice.write_bytes(b"open-source-notices")
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    first_hash = build_runtime_archive(
        version="0.7.0-test",
        frame_probe=frame_probe,
        snapshot_capture=snapshot_capture,
        stream_capture=stream_capture,
        library_probe=library_probe,
        runtime_root=runtime,
        aosp_notice=notice,
        output=first,
    )
    second_hash = build_runtime_archive(
        version="0.7.0-test",
        frame_probe=frame_probe,
        snapshot_capture=snapshot_capture,
        stream_capture=stream_capture,
        library_probe=library_probe,
        runtime_root=runtime,
        aosp_notice=notice,
        output=second,
    )

    assert first_hash == second_hash
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first, "r:gz") as archive:
        names = set(archive.getnames())
        assert "runtime-manifest.json" in names
        assert "LICENSES/AOSP-NOTICE.html.gz" in names
        assert not any(
            forbidden in name.casefold()
            for name in names
            for forbidden in ("apk", "authkey", "av_password", "sdk_key")
        )
        destination = tmp_path / "installed"
        archive.extractall(destination, filter="data")

    manifest = _verify_runtime(destination)
    assert manifest.architecture == "aarch64"

    installed = install_runtime_archive(
        first,
        expected_sha256=first_hash,
        runtime_parent=tmp_path / "runtime-install",
    )
    assert installed.root.name == "current"
    assert installed.version == "0.7.0-test"


def test_runtime_installer_rejects_bad_checksum_and_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        content = b"unsafe"
        member = tarfile.TarInfo("../escape")
        member.size = len(content)
        output.addfile(member, io.BytesIO(content))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()

    with pytest.raises(OwletRuntimeInstallError, match="checksum"):
        install_runtime_archive(
            archive,
            expected_sha256="0" * 64,
            runtime_parent=tmp_path / "bad-checksum",
        )
    with pytest.raises(OwletRuntimeInstallError, match="unsafe"):
        install_runtime_archive(
            archive,
            expected_sha256=checksum,
            runtime_parent=tmp_path / "traversal",
        )

    assert not (tmp_path / "escape").exists()


def _release_runtime_archive(
    tmp_path: Path, *, version: str = "0.7.0", architecture: str = "aarch64"
) -> tuple[Path, str]:
    archive_path = tmp_path / "owlet-cam-helper-aarch64.tar.gz"
    files = {
        name: f"open-source:{name}".encode()
        for name in (
            "LICENSES/AOSP-NOTICE.html.gz",
            "LICENSES/OWLET-CAM-MIT.txt",
            "bin/frame_probe",
            "bin/probe_libraries",
            "bin/snapshot_capture",
            "bin/stream_capture",
            "runtime/bin/linker64",
            "runtime/lib64/libc.so",
            "runtime/lib64/libdl.so",
            "runtime/lib64/libm.so",
        )
    }
    manifest = {
        "schema_version": 1,
        "version": version,
        "architecture": architecture,
        "files": {
            name: hashlib.sha256(content).hexdigest() for name, content in files.items()
        },
    }
    files["runtime-manifest.json"] = json.dumps(manifest).encode()
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return archive_path, hashlib.sha256(archive_path.read_bytes()).hexdigest()


async def test_downloads_checksum_pinned_release_runtime(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    tmp_path: Path,
) -> None:
    archive, checksum = _release_runtime_archive(tmp_path)
    release = f"{RELEASE_BASE_URL}/v0.7.0"
    aioclient_mock.get(
        f"{release}/checksums.txt",
        text=f"{checksum}  owlet-cam-helper-aarch64.tar.gz\n",
    )
    aioclient_mock.get(
        f"{release}/owlet-cam-helper-aarch64.tar.gz",
        content=archive.read_bytes(),
    )

    installed = await async_ensure_release_runtime(
        hass,
        async_get_clientsession(hass),
        version="0.7.0",
        architecture="aarch64",
        runtime_parent=tmp_path / "installed",
    )

    assert installed.version == "0.7.0"
    assert installed.architecture == "aarch64"
    assert installed.root.name == "current"
    assert not list((tmp_path / "installed").glob("*.partial"))


async def test_release_runtime_rejects_checksum_and_version_mismatch(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    tmp_path: Path,
) -> None:
    archive, _checksum = _release_runtime_archive(tmp_path, version="0.6.0")
    release = f"{RELEASE_BASE_URL}/v0.7.0"
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    aioclient_mock.get(
        f"{release}/checksums.txt",
        text=f"{'0' * 64}  owlet-cam-helper-aarch64.tar.gz\n",
    )
    aioclient_mock.get(
        f"{release}/owlet-cam-helper-aarch64.tar.gz",
        content=archive.read_bytes(),
    )
    with pytest.raises(OwletRuntimeInstallError, match="checksum"):
        await async_ensure_release_runtime(
            hass,
            async_get_clientsession(hass),
            version="0.7.0",
            architecture="aarch64",
            runtime_parent=tmp_path / "bad-checksum",
        )

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{release}/checksums.txt",
        text=f"{actual}  owlet-cam-helper-aarch64.tar.gz\n",
    )
    aioclient_mock.get(
        f"{release}/owlet-cam-helper-aarch64.tar.gz",
        content=archive.read_bytes(),
    )
    with pytest.raises(OwletRuntimeInstallError, match="does not match"):
        await async_ensure_release_runtime(
            hass,
            async_get_clientsession(hass),
            version="0.7.0",
            architecture="aarch64",
            runtime_parent=tmp_path / "bad-version",
        )


async def test_release_runtime_reports_unavailable_without_url_leak(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    tmp_path: Path,
) -> None:
    release = f"{RELEASE_BASE_URL}/v0.7.0"
    aioclient_mock.get(f"{release}/checksums.txt", status=404)

    with pytest.raises(OwletRuntimeDownloadError) as caught:
        await async_ensure_release_runtime(
            hass,
            async_get_clientsession(hass),
            version="0.7.0",
            architecture="aarch64",
            runtime_parent=tmp_path / "unavailable",
        )

    assert "github" not in str(caught.value).casefold()
    assert "http" not in str(caught.value).casefold()


def test_manager_prepares_and_reuses_safe_user_extraction(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    root = tmp_path / "userfiles"
    uploads = root / "uploads"
    uploads.mkdir(parents=True)
    _runtime_tree(root / "runtime" / "current")
    archive = uploads / "user-supplied.xapk"
    sdk_key = b"AQ" + b"x" * 40
    with zipfile.ZipFile(archive, "w") as package:
        for name in (
            "libAVAPIs.so",
            "libIOTCAPIs.so",
            "libP2PTunnelAPIs.so",
            "libRDTAPIs.so",
            "libTUTKGlobalAPIs.so",
        ):
            package.writestr(f"lib/arm64-v8a/{name}", _minimal_elf())
        package.writestr("classes.dex", b"\0" + sdk_key + b"\0")
    manager = OwletRuntimeManager(
        hass,
        root=root,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )
    elf_report = SimpleNamespace(
        architecture="AArch64",
        required_symbols_present=True,
        has_writable_executable_segment=False,
    )

    with (
        patch("platform.machine", return_value="aarch64"),
        patch(
            "custom_components.owlet_cam.runtime.manager.inspect_elf",
            return_value=elf_report,
        ) as inspect,
    ):
        prepared, first_key = manager._prepare_sync()
        reused, second_key = manager._prepare_sync()
        archive.unlink()
        persisted, third_key = manager._prepare_sync()

    assert prepared.source_sha256 == reused.source_sha256
    assert len(prepared.libraries) == 5
    assert persisted.source_sha256 == prepared.source_sha256
    assert inspect.call_count == 15
    assert first_key == sdk_key
    assert second_key == sdk_key
    assert third_key == sdk_key
    assert not archive.exists()
    assert (
        prepared.library_directory.parent / ".sdk-key"
    ).stat().st_mode & 0o777 == 0o600
    assert (
        prepared.library_directory.parent / "application.json"
    ).stat().st_mode & 0o777 == 0o600
    assert all(
        path.stat().st_mode & 0o777 == 0o500
        for path in prepared.library_directory.iterdir()
    )


async def test_manager_deletes_only_proprietary_material(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    root = tmp_path / "userfiles"
    for name in ("uploads", "extracted", "runtime", "logs", "state", "tmp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "uploads" / "fixture.apk").write_bytes(b"private")
    (root / "extracted" / "hash" / "arm64-v8a").mkdir(parents=True)
    (root / "extracted" / "hash" / ".sdk-key").write_bytes(b"private")
    (root / "runtime" / "open-source-helper").write_bytes(b"retain")
    manager = OwletRuntimeManager(
        hass,
        root=root,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )
    manager._sdk_key = bytearray(b"fixture-private-key")

    await manager.async_delete_proprietary_files()

    assert not list((root / "uploads").iterdir())
    assert not list((root / "extracted").iterdir())
    assert (root / "runtime" / "open-source-helper").read_bytes() == b"retain"
    assert manager._sdk_key is None
    assert manager.snapshot.proprietary_files_present is False


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (
            OwletRuntimeError("invalid_runtime_storage", "safe"),
            "invalid_runtime_storage",
        ),
        (OwletArchiveError("safe"), "invalid_apk"),
        (ElfInspectionError("safe"), "library_incompatible"),
    ],
)
async def test_manager_records_safe_runtime_probe_failures(
    hass: HomeAssistant,
    tmp_path: Path,
    failure: Exception,
    code: str,
) -> None:
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )
    with patch.object(manager, "_prepare_sync", side_effect=failure):
        with pytest.raises(OwletRuntimeError):
            await manager.async_prepare_and_probe_libraries()

    assert manager.snapshot.status == "error"
    assert manager.snapshot.last_error_code == code


async def test_manager_fetches_release_when_runtime_is_missing(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )
    prepared = PreparedRuntime(
        manifest=RuntimeManifest(
            version="0.6.0-test", architecture="aarch64", root=tmp_path
        ),
        library_directory=tmp_path,
        libraries=(),
        source_sha256="0" * 64,
    )
    expected = (prepared, bytearray(b"fixture-sdk-key"))
    with (
        patch.object(
            manager,
            "_prepare_sync",
            side_effect=[OwletRuntimeError("missing_runtime", "safe"), expected],
        ),
        patch.object(
            manager, "_async_install_release_runtime", new=AsyncMock()
        ) as install,
    ):
        result = await manager._async_prepare_runtime_files()

    assert result == expected
    install.assert_awaited_once_with()
