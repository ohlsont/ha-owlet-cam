"""Desktop Owlet runtime preparation and acquisition tests."""

from __future__ import annotations

import io
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.owlet_cam.runtime.apk import (
    REQUIRED_LIBRARIES,
    RUNTIME_PACK_MANIFEST,
    extract_owlet_application,
)
from scripts.build_preparer_zipapp import build_zipapp
from scripts.prepare_runtime_package import (
    PreparationError,
    acquire_with_adb,
    acquire_with_apkeep,
    prepare_runtime_package,
)

_FIXTURE_KEY = b"AQ" + b"desktop-preparer-fixture-key-0123456789"


def _source_application() -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "package_name": "com.owletcare.sleep",
                    "version_name": "3.40.0",
                }
            ),
        )
        for name in REQUIRED_LIBRARIES:
            archive.writestr(f"lib/arm64-v8a/{name}", f"fixture:{name}".encode())
        archive.writestr("classes.dex", b"prefix\0" + _FIXTURE_KEY + b"\0suffix")
    return result.getvalue()


def _write_source(path: Path) -> Path:
    path.write_bytes(_source_application())
    path.chmod(0o600)
    return path


def test_prepares_deterministic_minimum_runtime_package(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "dream.apk")
    first = tmp_path / "first.owletcam"
    second = tmp_path / "second.owletcam"

    report = prepare_runtime_package(source, first)
    prepare_runtime_package(source, second)

    assert first.read_bytes() == second.read_bytes()
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert report["sdk_key_found"] is True
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        assert names == {
            RUNTIME_PACK_MANIFEST,
            "private/sdk-key",
            *(f"lib/arm64-v8a/{name}" for name in REQUIRED_LIBRARIES),
        }
        serialized = b"".join(archive.read(name) for name in names)
        assert b"password" not in serialized
        assert b"firebase" not in serialized

    extracted = extract_owlet_application(first, tmp_path / "round-trip")
    assert extracted.package_name == "com.owletcare.sleep"
    assert extracted.app_version == "3.40.0"
    assert extracted.sdk_key == _FIXTURE_KEY


def test_standalone_zipapp_prepares_package_without_home_assistant(
    tmp_path: Path,
) -> None:
    source = _write_source(tmp_path / "dream.apk")
    first_tool = tmp_path / "prepare-first.pyz"
    second_tool = tmp_path / "prepare-second.pyz"
    output = tmp_path / "runtime.owletcam"
    build_zipapp(first_tool)
    build_zipapp(second_tool)

    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(first_tool), "archive", str(source), str(output)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert first_tool.read_bytes() == second_tool.read_bytes()
    assert output.is_file()
    assert "sdk_key_found" in completed.stdout
    assert _FIXTURE_KEY.decode() not in completed.stdout
    assert completed.stderr == ""


def test_adb_collects_all_installed_splits_with_fixed_names(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(
        arguments: list[str], *, failure: str
    ) -> subprocess.CompletedProcess[bytes]:
        del failure
        calls.append(arguments)
        if arguments[-1] == "devices":
            return subprocess.CompletedProcess(
                arguments, 0, b"List of devices\nemulator-1\tdevice\n", b""
            )
        if "path" in arguments:
            return subprocess.CompletedProcess(
                arguments,
                0,
                b"package:/data/app/pkg/base.apk\npackage:/data/app/pkg/split_arm64.apk\n",
                b"",
            )
        Path(arguments[-1]).write_bytes(b"fixture-apk")
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    with patch("scripts.prepare_runtime_package._run_command", side_effect=fake_run):
        archive = acquire_with_adb(
            tmp_path,
            adb="adb",
            package="com.owletcare.sleep",
            serial=None,
        )

    with zipfile.ZipFile(archive) as bundled:
        assert bundled.namelist() == [
            "splits/split-000.apk",
            "splits/split-001.apk",
        ]
    assert all("password" not in argument for call in calls for argument in call)


def test_apkeep_uses_private_config_without_token_on_command_line(
    tmp_path: Path,
) -> None:
    config = tmp_path / "apkeep.ini"
    config.write_text("[google]\naas_token=fixture-super-secret-token\n")
    config.chmod(0o600)
    captured: list[str] = []

    def fake_run(
        arguments: list[str], *, failure: str
    ) -> subprocess.CompletedProcess[bytes]:
        del failure
        captured.extend(arguments)
        output = Path(arguments[-1]) / "dream.apk"
        _write_source(output)
        return subprocess.CompletedProcess(arguments, 0, b"downloaded", b"")

    with patch("scripts.prepare_runtime_package._run_command", side_effect=fake_run):
        source = acquire_with_apkeep(
            tmp_path,
            apkeep="apkeep",
            config=config,
            package="com.owletcare.sleep",
        )

    assert source.name == "dream.apk"
    assert "split_apk=true" in captured
    assert "fixture-super-secret-token" not in " ".join(captured)


def test_apkeep_rejects_public_token_config(tmp_path: Path) -> None:
    config = tmp_path / "apkeep.ini"
    config.write_text("[google]\naas_token=fixture-super-secret-token\n")
    config.chmod(0o644)

    with pytest.raises(PreparationError, match="0600"):
        acquire_with_apkeep(
            tmp_path,
            apkeep="apkeep",
            config=config,
            package="com.owletcare.sleep",
        )
