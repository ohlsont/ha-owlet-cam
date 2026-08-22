#!/usr/bin/env python3
"""Run the isolated local frame probe without exposing camera secrets."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.owlet_cam.api.cloud import (  # noqa: E402
    OwletCloudClient,
)
from custom_components.owlet_cam.api.exceptions import OwletCamError  # noqa: E402
from custom_components.owlet_cam.runtime.apk import (  # noqa: E402
    REQUIRED_LIBRARIES,
    OwletArchiveError,
    extract_owlet_application,
)
from scripts.probe_cloud import (  # noqa: E402
    ENV_FILE,
    ProbeConfigurationError,
    load_probe_env,
    normalize_probe_region,
    safe_error_report,
)
from scripts.probe_firestore import (  # noqa: E402
    _FIRESTORE_PROJECTS,
    _get_document,
    _map_keys_field,
    _string_field,
)

UPLOADS: Final = ROOT / "custom_components/owlet_cam/userfiles/uploads"
PINNED_BUILD_IMAGE: Final = (
    "sha256:1710bde34461551a19a47c787885ec9ad7058d9a5bead2affb8d088fa2f8502b"
)
ADB: Final = Path.home() / "Library/Android/sdk/platform-tools/adb"
ADB_PROBE_DIR: Final = "/data/local/tmp/owlet-frame-probe"
SAFE_EVENTS: Final = frozenset({"frame_probe"})
SAFE_STAGES: Final = frozenset(
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
    }
)
SAFE_RESULT_FIELDS: Final = frozenset(
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


def _select_archive(explicit: Path | None) -> Path:
    """Select an archive without displaying its potentially private filename."""
    if explicit is not None:
        return explicit.resolve()
    candidates = [
        path
        for path in UPLOADS.iterdir()
        if path.is_file() and path.suffix.lower() in {".apk", ".apkm", ".xapk", ".zip"}
    ]
    if not candidates:
        raise ProbeConfigurationError("No Owlet application archive was found")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns).resolve()


async def _discover_internal_dsn(
    session: aiohttp.ClientSession,
    client: OwletCloudClient,
    *,
    region: str,
    token: str,
) -> str:
    """Follow only directly authorized Firestore references in memory."""
    account_id = client._account_id
    if account_id is None:
        raise ProbeConfigurationError("Authentication did not return an account")
    account_status, account_document = await _get_document(
        session,
        project=_FIRESTORE_PROJECTS[region],
        collection="accounts",
        document_id=account_id,
        token=token,
    )
    if account_status != 200:
        raise ProbeConfigurationError("The Owlet account document is unavailable")
    service_keys = _map_keys_field(account_document.get("fields"), "serviceKeys")
    device_keys: list[str] = []
    for service_key in service_keys:
        status, document = await _get_document(
            session,
            project=_FIRESTORE_PROJECTS[region],
            collection="services",
            document_id=service_key,
            token=token,
        )
        if status == 200:
            device_key = _string_field(document.get("fields"), "deviceKey")
            if device_key is not None:
                device_keys.append(device_key)
    dsns: list[str] = []
    for device_key in device_keys:
        status, document = await _get_document(
            session,
            project=_FIRESTORE_PROJECTS[region],
            collection="devices",
            document_id=device_key,
            token=token,
        )
        if status == 200:
            dsn = _string_field(document.get("fields"), "dsn")
            if dsn is not None:
                dsns.append(dsn.strip().upper())
    if len(dsns) != 1:
        raise ProbeConfigurationError(
            "The account must resolve to exactly one camera for this local probe"
        )
    return dsns[0]


def _validated_helper_result(stdout: bytes) -> dict[str, Any]:
    """Accept only the helper's fixed, non-secret result schema."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ProbeConfigurationError("The isolated helper returned invalid output")
    try:
        payload: object = json.loads(lines[0])
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProbeConfigurationError(
            "The isolated helper returned malformed output"
        ) from error
    if not isinstance(payload, dict) or payload.get("event") not in SAFE_EVENTS:
        raise ProbeConfigurationError("The isolated helper returned invalid output")
    if not set(payload).issubset(SAFE_RESULT_FIELDS):
        raise ProbeConfigurationError("The isolated helper returned unsafe output")
    stage = payload.get("stage")
    if stage is not None and stage not in SAFE_STAGES:
        raise ProbeConfigurationError("The isolated helper returned an unknown stage")
    return payload


async def _run_helper(
    *,
    helper: Path,
    runtime: Path | None,
    libraries: Path,
    adb_serial: str | None,
    sdk_key: str,
    uid: str,
    auth_key: str,
    av_password: str,
) -> tuple[int, dict[str, Any]]:
    """Pass secrets once over stdin to a constrained helper container."""
    command: tuple[str, ...]
    if adb_serial is None:
        if runtime is None:
            raise ProbeConfigurationError("The Docker probe requires a runtime")
        command = (
            "docker",
            "run",
            "--rm",
            "-i",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory=256m",
            "--tmpfs=/tmp:size=8m,noexec,nosuid,nodev",
            f"--mount=type=bind,source={runtime},target=/runtime,readonly",
            f"--mount=type=bind,source={helper},target=/helper/frame_probe,readonly",
            f"--mount=type=bind,source={libraries},target=/libs,readonly",
            "--env=LD_LIBRARY_PATH=/runtime/lib64:/libs",
            PINNED_BUILD_IMAGE,
            "/helper/frame_probe",
        )
    else:
        try:
            await _prepare_adb_probe(
                serial=adb_serial, helper=helper, libraries=libraries
            )
        except Exception:
            await _cleanup_adb_probe(adb_serial)
            raise
        command = (
            str(ADB),
            "-s",
            adb_serial,
            "shell",
            f"LD_LIBRARY_PATH={ADB_PROBE_DIR} "
            f"/system/bin/linker64 {ADB_PROBE_DIR}/frame_probe",
        )
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    request = json.dumps(
        {
            "sdk_key": sdk_key,
            "uid": uid,
            "auth_key": auth_key,
            "av_password": av_password,
        },
        separators=(",", ":"),
    ).encode()
    try:
        stdout, _stderr = await asyncio.wait_for(
            process.communicate(request + b"\n"), timeout=75
        )
    except TimeoutError:
        process.terminate()
        await process.wait()
        raise ProbeConfigurationError("The isolated frame probe timed out") from None
    finally:
        request = b""
        sdk_key = uid = auth_key = av_password = ""
        if adb_serial is not None:
            await _cleanup_adb_probe(adb_serial)
    return process.returncode or 0, _validated_helper_result(stdout)


async def _run_adb(*arguments: str) -> None:
    """Run one non-interactive ADB file-management command quietly."""
    process = await asyncio.create_subprocess_exec(
        str(ADB),
        *arguments,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    if await process.wait() != 0:
        raise ProbeConfigurationError("The Android probe could not be prepared")


async def _prepare_adb_probe(*, serial: str, helper: Path, libraries: Path) -> None:
    """Copy only the helper and user-supplied libraries to a private temp path."""
    await _cleanup_adb_probe(serial)
    await _run_adb("-s", serial, "shell", "mkdir", "-p", ADB_PROBE_DIR)
    await _run_adb("-s", serial, "push", str(helper), f"{ADB_PROBE_DIR}/frame_probe")
    remote_libraries: list[str] = []
    for library_name in sorted(REQUIRED_LIBRARIES):
        library = libraries / library_name
        destination = f"{ADB_PROBE_DIR}/{library.name}"
        await _run_adb("-s", serial, "push", str(library), destination)
        remote_libraries.append(destination)
    await _run_adb(
        "-s",
        serial,
        "shell",
        "chmod",
        "700",
        f"{ADB_PROBE_DIR}/frame_probe",
    )
    await _run_adb("-s", serial, "shell", "chmod", "500", *remote_libraries)


async def _cleanup_adb_probe(serial: str) -> None:
    """Remove only the fixed temporary directory created by this probe."""
    process = await asyncio.create_subprocess_exec(
        str(ADB),
        "-s",
        serial,
        "shell",
        "rm",
        "-rf",
        ADB_PROBE_DIR,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.wait()


async def async_run(
    *,
    archive: Path,
    helper: Path,
    runtime: Path | None,
    adb_serial: str | None,
) -> int:
    """Fetch credentials in memory, extract user files, and run the helper."""
    values = load_probe_env(ENV_FILE)
    region = normalize_probe_region(values.get("OWLET_REGION", "europe"))
    report: dict[str, Any]
    try:
        with tempfile.TemporaryDirectory(
            prefix="owlet-frame-probe-", dir="/private/tmp"
        ) as temporary:
            extracted = extract_owlet_application(archive, Path(temporary))
            if extracted.sdk_key is None:
                raise ProbeConfigurationError(
                    "The user application did not contain an SDK key"
                )
            sdk_key = extracted.sdk_key.decode("ascii")
            libraries = Path(temporary) / extracted.abi
            async with aiohttp.ClientSession() as session:
                client = OwletCloudClient(
                    session,
                    email=values.get("OWLET_EMAIL", ""),
                    password=values.get("OWLET_PASSWORD", ""),
                    region=region,
                )
                token = await client._async_ensure_token()
                internal_dsn = await _discover_internal_dsn(
                    session, client, region=region, token=token
                )
                await client.async_validate_camera(internal_dsn)
                credentials = client._camera_credentials[internal_dsn]
                exit_code, report = await _run_helper(
                    helper=helper,
                    runtime=runtime,
                    libraries=libraries,
                    adb_serial=adb_serial,
                    sdk_key=sdk_key,
                    uid=credentials.uid,
                    auth_key=credentials.auth_key,
                    av_password=credentials.av_password,
                )
                del credentials
                sdk_key = token = internal_dsn = ""
    except OwletCamError as error:
        report = safe_error_report(error)
        exit_code = 1
    except (OwletArchiveError, UnicodeError) as error:
        report = {
            "ok": False,
            "error_code": type(error).__name__,
            "message": "The user application could not be prepared safely",
        }
        exit_code = 1
    finally:
        values.clear()
    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_code


def main() -> int:
    """Parse non-secret local paths and run the isolated probe."""
    parser = argparse.ArgumentParser(description="Run a redacted local frame probe")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--adb-serial")
    args = parser.parse_args()
    try:
        archive = _select_archive(args.archive)
        helper = args.helper.resolve(strict=True)
        runtime = args.runtime.resolve(strict=True) if args.runtime else None
        if args.adb_serial is None and runtime is None:
            raise ProbeConfigurationError(
                "Choose an Android emulator or provide the Docker runtime"
            )
        if args.adb_serial is not None and not ADB.is_file():
            raise ProbeConfigurationError("Android platform tools were not found")
        return asyncio.run(
            async_run(
                archive=archive,
                helper=helper,
                runtime=runtime,
                adb_serial=args.adb_serial,
            )
        )
    except ProbeConfigurationError as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": type(error).__name__,
                    "message": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    except OSError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": "LocalFileError",
                    "message": "A required local probe file could not be accessed",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
