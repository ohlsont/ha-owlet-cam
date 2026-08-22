"""Native runtime structural gate tests."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import struct
import sys
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.owlet_cam.api.cloud import OwletCloudClient
from custom_components.owlet_cam.api.models import OwletCameraCredentials
from custom_components.owlet_cam.runtime.apk import OwletArchiveError
from custom_components.owlet_cam.runtime.downloader import (
    OwletRuntimeInstallError,
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
    OwletRuntimeError,
    OwletRuntimeManager,
    PreparedRuntime,
    RuntimeManifest,
    _prepare_directories,
    _verify_runtime,
)
from custom_components.owlet_cam.runtime.process import (
    HelperProcessResult,
    OwletHelperProcessError,
    OwletHelperProcessRunner,
)
from custom_components.owlet_cam.runtime.protocol import (
    OwletHelperProtocolError,
    OwletHelperReportedError,
    parse_frame_probe_output,
    parse_library_probe_output,
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


async def test_process_runner_times_out_and_reaps_child(tmp_path: Path) -> None:
    runner = OwletHelperProcessRunner()
    command = (sys.executable, "-c", "import time; time.sleep(30)")

    with pytest.raises(OwletHelperProcessError, match="timed out"):
        await runner.async_run(command, timeout_seconds=0.01, cwd=tmp_path)

    assert not runner.running


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


def _runtime_tree(root: Path) -> None:
    files = (
        "bin/frame_probe",
        "bin/probe_libraries",
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
    library_probe = tmp_path / "probe_libraries"
    notice = tmp_path / "NOTICE.html.gz"
    frame_probe.write_bytes(b"clean-room-frame-helper")
    library_probe.write_bytes(b"clean-room-library-helper")
    notice.write_bytes(b"open-source-notices")
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    first_hash = build_runtime_archive(
        frame_probe=frame_probe,
        library_probe=library_probe,
        runtime_root=runtime,
        aosp_notice=notice,
        output=first,
    )
    second_hash = build_runtime_archive(
        frame_probe=frame_probe,
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
    assert installed.version == "0.4.0-dev"


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

    assert prepared.source_sha256 == reused.source_sha256
    assert len(prepared.libraries) == 5
    assert inspect.call_count == 10
    assert first_key == sdk_key
    assert second_key == sdk_key
    assert archive.stat().st_mode & 0o777 == 0o600
    assert all(
        path.stat().st_mode & 0o777 == 0o500
        for path in prepared.library_directory.iterdir()
    )


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (OwletRuntimeError("missing_runtime", "safe"), "missing_runtime"),
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
