"""Safe user-supplied application archive extraction tests."""

from __future__ import annotations

import io
import json
import stat
import struct
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.owlet_cam.runtime.apk import (
    REQUIRED_LIBRARIES,
    ArchiveLimits,
    OwletArchiveError,
    _parse_binary_android_manifest,
    extract_owlet_application,
)

_FIXTURE_KEY = b"AQ" + b"fixture-only-not-a-real-key-0123456789"


def _application_zip(
    *, abi: str = "arm64-v8a", include_key: bool = True, include_manifest: bool = False
) -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        for name in REQUIRED_LIBRARIES:
            archive.writestr(f"lib/{abi}/{name}", f"fixture:{name}".encode())
        dex = b"fixture"
        if include_key:
            dex += b"\0" + _FIXTURE_KEY + b"\0"
        archive.writestr("classes.dex", dex)
        if include_manifest:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "package_name": "com.example.fixture",
                        "version_name": "9.8.7",
                    }
                ),
            )
    return result.getvalue()


def _write_archive(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def test_extracts_only_required_arm64_libraries(tmp_path: Path) -> None:
    source = _write_archive(tmp_path / "owlet.apk", _application_zip())

    result = extract_owlet_application(source, tmp_path / "out")

    assert set(result.libraries) == REQUIRED_LIBRARIES
    assert result.sdk_key_found is True
    assert result.sdk_key == _FIXTURE_KEY
    assert "fixture-only" not in repr(result)
    for library in result.libraries.values():
        assert library.path.parent.name == "arm64-v8a"
        assert stat.S_IMODE(library.path.stat().st_mode) == 0o500


def test_extracts_nested_apkm_split(tmp_path: Path) -> None:
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("splits/base.apk", _application_zip())
        archive.writestr("metadata.json", "{}")
    source = _write_archive(tmp_path / "owlet.apkm", outer.getvalue())

    result = extract_owlet_application(source, tmp_path / "out")

    assert set(result.libraries) == REQUIRED_LIBRARIES
    assert result.sdk_key_found is True


def test_reads_non_secret_application_metadata(tmp_path: Path) -> None:
    source = _write_archive(
        tmp_path / "owlet.xapk", _application_zip(include_manifest=True)
    )

    result = extract_owlet_application(source, tmp_path / "out")

    assert result.package_name == "com.example.fixture"
    assert result.app_version == "9.8.7"


def test_reads_binary_android_manifest_string_pool() -> None:
    values = ["android.permission.CAMERA", "com.owletcare.fixture", "4.5.6"]
    encoded = [
        bytes((len(value), len(value))) + value.encode() + b"\0" for value in values
    ]
    header_size = 28 + len(values) * 4
    offsets: list[int] = []
    strings = b""
    for value in encoded:
        offsets.append(len(strings))
        strings += value
    chunk_size = header_size + len(strings)
    pool = (
        struct.pack("<HHI", 0x0001, header_size, chunk_size)
        + struct.pack("<IIIII", len(values), 0, 0x100, header_size, 0)
        + b"".join(struct.pack("<I", offset) for offset in offsets)
        + strings
    )
    manifest = struct.pack("<HHI", 0x0003, 8, 8 + len(pool)) + pool

    package, version = _parse_binary_android_manifest(manifest)

    assert package == "com.owletcare.fixture"
    assert version == "4.5.6"


@pytest.mark.parametrize("payload", [b"", b"\x03\x00\x08\x00\xff\xff\xff\xff"])
def test_rejects_malformed_binary_android_manifest(payload: bytes) -> None:
    with pytest.raises(ValueError, match="manifest"):
        _parse_binary_android_manifest(payload)


def test_spools_nested_apk_to_private_disk_file(tmp_path: Path) -> None:
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("splits/base.apk", _application_zip())
    source = _write_archive(tmp_path / "owlet.apkm", outer.getvalue())
    destination = tmp_path / "out"

    with patch(
        "custom_components.owlet_cam.runtime.apk.tempfile.TemporaryFile",
        wraps=tempfile.TemporaryFile,
    ) as temporary_file:
        result = extract_owlet_application(source, destination)

    assert result.sdk_key_found
    temporary_file.assert_called_once_with(mode="w+b", dir=destination)
    assert not any(path.name.startswith("tmp") for path in destination.iterdir())


def test_rejects_archive_without_arm64_split(tmp_path: Path) -> None:
    source = _write_archive(tmp_path / "owlet.apk", _application_zip(abi="x86_64"))

    with pytest.raises(OwletArchiveError, match="missing required ARM64"):
        extract_owlet_application(source, tmp_path / "out")


def test_rejects_corrupt_zip(tmp_path: Path) -> None:
    source = _write_archive(tmp_path / "owlet.apk", b"not-a-zip")

    with pytest.raises(OwletArchiveError, match="not a valid ZIP"):
        extract_owlet_application(source, tmp_path / "out")


def test_rejects_zip_slip(tmp_path: Path) -> None:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("../escape.so", b"escape")
    source = _write_archive(tmp_path / "owlet.apk", content.getvalue())

    with pytest.raises(OwletArchiveError, match="path traversal"):
        extract_owlet_application(source, tmp_path / "out")
    assert not (tmp_path / "escape.so").exists()


def test_rejects_symlink_member(tmp_path: Path) -> None:
    content = io.BytesIO()
    link = zipfile.ZipInfo("lib/arm64-v8a/libIOTCAPIs.so")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(link, "target")
    source = _write_archive(tmp_path / "owlet.apk", content.getvalue())

    with pytest.raises(OwletArchiveError, match="link or special file"):
        extract_owlet_application(source, tmp_path / "out")


def test_rejects_oversized_uncompressed_archive(tmp_path: Path) -> None:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("classes.dex", b"x" * 33)
    source = _write_archive(tmp_path / "owlet.apk", content.getvalue())
    limits = ArchiveLimits(maximum_uncompressed_size=32)

    with pytest.raises(OwletArchiveError, match="expands beyond"):
        extract_owlet_application(source, tmp_path / "out", limits=limits)


def test_rejects_nonempty_destination(tmp_path: Path) -> None:
    source = _write_archive(tmp_path / "owlet.apk", _application_zip())
    destination = tmp_path / "out"
    destination.mkdir()
    (destination / "existing").write_text("owned by user")

    with pytest.raises(OwletArchiveError, match="must be empty"):
        extract_owlet_application(source, destination)
    assert (destination / "existing").read_text() == "owned by user"


def test_rejects_ambiguous_sdk_keys(tmp_path: Path) -> None:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        for name in REQUIRED_LIBRARIES:
            archive.writestr(f"lib/arm64-v8a/{name}", f"fixture:{name}".encode())
        archive.writestr(
            "classes.dex",
            b"\0" + _FIXTURE_KEY + b"\0AQ" + b"another-fixture-key-9876543210" + b"\0",
        )
    source = _write_archive(tmp_path / "owlet.apk", content.getvalue())

    with pytest.raises(OwletArchiveError, match="ambiguous SDK keys"):
        extract_owlet_application(source, tmp_path / "out")
