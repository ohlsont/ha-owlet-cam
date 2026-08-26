#!/usr/bin/env python3
"""Create a compact user-owned Owlet runtime package outside Home Assistant."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.owlet_cam.runtime.apk import (  # noqa: E402
    OWLET_ANDROID_PACKAGES,
    RUNTIME_PACK_FORMAT,
    RUNTIME_PACK_MANIFEST,
    RUNTIME_PACK_SCHEMA_VERSION,
    RUNTIME_PACK_SDK_KEY,
    RUNTIME_PACK_SUFFIX,
    SUPPORTED_ARCHIVE_SUFFIXES,
    TARGET_ABI,
    ExtractedOwletApplication,
    OwletArchiveError,
    extract_owlet_application,
)

DEFAULT_PACKAGE: Final = "com.owletcare.sleep"
COMMAND_TIMEOUT: Final = 180.0
_ZIP_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)


class PreparationError(ValueError):
    """Raised with a secret-free message when desktop preparation fails."""


def prepare_runtime_package(source: Path, output: Path) -> dict[str, object]:
    """Extract an application and write the minimum deterministic runtime pack."""
    if output.suffix.lower() != RUNTIME_PACK_SUFFIX:
        raise PreparationError(f"Output must end with {RUNTIME_PACK_SUFFIX}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="owlet-cam-prepare-") as raw_temporary:
        temporary = Path(raw_temporary)
        try:
            application = extract_owlet_application(source, temporary / "extracted")
        except OwletArchiveError as err:
            raise PreparationError(str(err)) from err
        if application.package_name not in OWLET_ANDROID_PACKAGES:
            raise PreparationError(
                "The supplied application is not an Owlet Android app"
            )
        if application.sdk_key is None:
            raise PreparationError("The supplied application has no Owlet SDK key")
        manifest = _runtime_manifest(application)
        _write_runtime_pack(output, application, manifest)
        try:
            verified = extract_owlet_application(output, temporary / "verified")
        except OwletArchiveError as err:
            output.unlink(missing_ok=True)
            raise PreparationError(
                "The generated runtime package failed validation"
            ) from err
        if (
            verified.package_name != application.package_name
            or verified.app_version != application.app_version
            or verified.sdk_key != application.sdk_key
            or {name: library.sha256 for name, library in verified.libraries.items()}
            != {name: library.sha256 for name, library in application.libraries.items()}
        ):
            output.unlink(missing_ok=True)
            raise PreparationError("The generated runtime package failed validation")
    return {
        "output": str(output),
        "package_name": application.package_name,
        "app_version": application.app_version,
        "abi": application.abi,
        "libraries": sorted(application.libraries),
        "sdk_key_found": True,
    }


def acquire_with_adb(
    destination: Path,
    *,
    adb: str,
    package: str,
    serial: str | None,
) -> Path:
    """Pull every installed split APK without reading application private data."""
    _validate_package(package)
    selected_serial = serial or _select_adb_device(adb)
    result = _run_command(
        [adb, "-s", selected_serial, "shell", "pm", "path", package],
        failure="Could not locate the installed Owlet application with adb",
    )
    remote_paths: list[str] = []
    try:
        lines = result.stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as err:
        raise PreparationError("adb returned malformed application paths") from err
    for raw_line in lines:
        if not raw_line.startswith("package:"):
            continue
        remote = raw_line.removeprefix("package:").strip()
        path = PurePosixPath(remote)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or not remote.endswith(".apk")
            or len(remote) > 4096
        ):
            raise PreparationError("adb returned an unsafe application path")
        remote_paths.append(remote)
    if not remote_paths:
        raise PreparationError("The installed Owlet application has no readable APKs")

    pulled = destination / "adb-apks"
    pulled.mkdir(mode=0o700)
    local_apks: list[Path] = []
    for index, remote in enumerate(sorted(set(remote_paths))):
        local = pulled / f"split-{index:03d}.apk"
        _run_command(
            [adb, "-s", selected_serial, "pull", remote, str(local)],
            failure="Could not copy an installed Owlet application split with adb",
        )
        _validate_private_regular_file(local, require_private=False)
        local.chmod(0o600)
        local_apks.append(local)
    return _bundle_apks(local_apks, destination / "owlet-adb.apkm")


def acquire_with_apkeep(
    destination: Path,
    *,
    apkeep: str,
    config: Path,
    package: str,
) -> Path:
    """Use apkeep's Google Play backend without placing its token on argv."""
    _validate_package(package)
    _validate_private_regular_file(config, require_private=True)
    downloaded = destination / "apkeep-download"
    downloaded.mkdir(mode=0o700)
    _run_command(
        [
            apkeep,
            "-a",
            package,
            "-d",
            "google-play",
            "-o",
            "split_apk=true",
            "-i",
            str(config),
            str(downloaded),
        ],
        failure="apkeep could not download the Owlet application from Google Play",
    )
    candidates = sorted(
        path
        for path in downloaded.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in SUPPORTED_ARCHIVE_SUFFIXES - {RUNTIME_PACK_SUFFIX}
    )
    if not candidates:
        raise PreparationError("apkeep did not produce an application archive")
    if len(candidates) == 1:
        candidates[0].chmod(0o600)
        return candidates[0]
    if any(path.suffix.lower() != ".apk" for path in candidates):
        raise PreparationError("apkeep produced an ambiguous set of application files")
    return _bundle_apks(candidates, destination / "owlet-apkeep.apkm")


def _runtime_manifest(application: ExtractedOwletApplication) -> dict[str, object]:
    return {
        "format": RUNTIME_PACK_FORMAT,
        "schema_version": RUNTIME_PACK_SCHEMA_VERSION,
        "application_source_sha256": application.source_sha256,
        "package_name": application.package_name,
        "app_version": application.app_version,
        "abi": application.abi,
        "libraries": [
            {
                "name": library.name,
                "path": f"lib/{TARGET_ABI}/{library.name}",
                "sha256": library.sha256,
                "size": library.size,
            }
            for library in application.libraries.values()
        ],
    }


def _write_runtime_pack(
    output: Path,
    application: ExtractedOwletApplication,
    manifest: dict[str, object],
) -> None:
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".partial", dir=output.parent
    )
    temporary = Path(raw_temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w+b", closefd=False) as stream:
            with zipfile.ZipFile(
                stream, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
            ) as archive:
                _write_zip_member(
                    archive,
                    RUNTIME_PACK_MANIFEST,
                    json.dumps(
                        manifest, sort_keys=True, separators=(",", ":")
                    ).encode(),
                    0o600,
                )
                if application.sdk_key is None:
                    raise PreparationError(
                        "The supplied application has no Owlet SDK key"
                    )
                _write_zip_member(
                    archive, RUNTIME_PACK_SDK_KEY, application.sdk_key, 0o600
                )
                for library in application.libraries.values():
                    _write_zip_file(
                        archive,
                        f"lib/{TARGET_ABI}/{library.name}",
                        library.path,
                        0o500,
                        zipfile.ZIP_DEFLATED,
                    )
            stream.flush()
            os.fsync(stream.fileno())
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, output)
        output.chmod(0o600)
    except OSError as err:
        raise PreparationError(
            "The Owlet runtime package could not be written"
        ) from err
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _write_zip_member(
    archive: zipfile.ZipFile, name: str, content: bytes, mode: int
) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content, compresslevel=9)


def _write_zip_file(
    archive: zipfile.ZipFile,
    name: str,
    source: Path,
    mode: int,
    compression: int,
) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = compression
    with (
        source.open("rb") as input_file,
        archive.open(info, mode="w", force_zip64=True) as output_file,
    ):
        shutil.copyfileobj(input_file, output_file, length=1024 * 1024)


def _select_adb_device(adb: str) -> str:
    result = _run_command(
        [adb, "devices"], failure="Could not list Android devices with adb"
    )
    devices = []
    try:
        lines = result.stdout.decode("utf-8", errors="strict").splitlines()[1:]
    except UnicodeDecodeError as err:
        raise PreparationError("adb returned malformed device information") from err
    for line in lines:
        fields = line.split()
        if len(fields) == 2 and fields[1] == "device":
            devices.append(fields[0])
    if len(devices) != 1:
        raise PreparationError(
            "Connect exactly one authorized Android device or pass --serial"
        )
    return devices[0]


def _bundle_apks(apks: Sequence[Path], output: Path) -> Path:
    if not apks:
        raise PreparationError("No Android application splits were collected")
    with output.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        with zipfile.ZipFile(
            stream, mode="w", compression=zipfile.ZIP_STORED
        ) as archive:
            for index, apk in enumerate(apks):
                _validate_private_regular_file(apk, require_private=False)
                _write_zip_file(
                    archive,
                    f"splits/split-{index:03d}.apk",
                    apk,
                    0o600,
                    zipfile.ZIP_STORED,
                )
    return output


def _validate_package(package: str) -> None:
    if package not in OWLET_ANDROID_PACKAGES:
        raise PreparationError("Only official Owlet Android package IDs are allowed")


def _validate_private_regular_file(path: Path, *, require_private: bool) -> None:
    try:
        metadata = path.lstat()
    except OSError as err:
        raise PreparationError("A required local file cannot be read") from err
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PreparationError("A required local path is not a regular file")
    if require_private and os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PreparationError("The apkeep configuration file must use mode 0600")


def _run_command(
    arguments: Sequence[str], *, failure: str
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(arguments),
            check=True,
            capture_output=True,
            timeout=COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as err:
        raise PreparationError(failure) from err


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a compact user-owned Owlet runtime package outside Home Assistant"
        )
    )
    subparsers = parser.add_subparsers(dest="source", required=True)
    archive = subparsers.add_parser("archive", help="Use an existing APK/APKM/XAPK")
    archive.add_argument("application", type=Path)
    archive.add_argument("output", type=Path)

    adb = subparsers.add_parser("adb", help="Export an app installed on Android")
    adb.add_argument("output", type=Path)
    adb.add_argument("--adb", default=_default_adb())
    adb.add_argument("--serial")
    adb.add_argument(
        "--package", choices=sorted(OWLET_ANDROID_PACKAGES), default=DEFAULT_PACKAGE
    )

    apkeep = subparsers.add_parser("apkeep", help="Download with apkeep Google Play")
    apkeep.add_argument("output", type=Path)
    apkeep.add_argument("--apkeep", default=shutil.which("apkeep") or "apkeep")
    apkeep.add_argument("--config", type=Path, required=True)
    apkeep.add_argument(
        "--package", choices=sorted(OWLET_ANDROID_PACKAGES), default=DEFAULT_PACKAGE
    )
    return parser


def _default_adb() -> str:
    if discovered := shutil.which("adb"):
        return discovered
    executable = "adb.exe" if os.name == "nt" else "adb"
    candidates = [
        Path.home() / "Library/Android/sdk/platform-tools" / executable,
        Path.home() / "Android/Sdk/platform-tools" / executable,
    ]
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        candidates.append(
            Path(local_app_data) / "Android/Sdk/platform-tools" / executable
        )
    return str(next((path for path in candidates if path.is_file()), Path(executable)))


def main() -> int:
    """Acquire, minimize, validate, and report only non-secret facts."""
    args = _parser().parse_args()
    try:
        if args.source == "archive":
            application = args.application
        else:
            with tempfile.TemporaryDirectory(prefix="owlet-cam-acquire-") as raw:
                temporary = Path(raw)
                if args.source == "adb":
                    application = acquire_with_adb(
                        temporary,
                        adb=args.adb,
                        package=args.package,
                        serial=args.serial,
                    )
                else:
                    application = acquire_with_apkeep(
                        temporary,
                        apkeep=args.apkeep,
                        config=args.config,
                        package=args.package,
                    )
                report = prepare_runtime_package(application, args.output)
                print(json.dumps(report, indent=2))
                return 0
        report = prepare_runtime_package(application, args.output)
    except PreparationError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
