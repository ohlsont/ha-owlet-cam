"""Release metadata and archive inspection tests."""

import json
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from scripts.create_release_metadata import create_metadata
from scripts.extract_release_notes import extract_release_notes
from scripts.inspect_release_assets import inspect_archive


def test_release_metadata_is_complete_and_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "ha-owlet-cam.zip"
    second = tmp_path / "owlet-cam-helper-aarch64.tar.gz"
    preparer = tmp_path / "owlet-cam-prepare.pyz"
    first.write_bytes(b"integration archive")
    second.write_bytes(b"helper archive")
    preparer.write_bytes(b"preparer archive")
    output = tmp_path / "metadata"

    create_metadata(
        assets=[second, preparer, first],
        output_directory=output,
        version="0.7.0",
        created="2026-08-26T12:00:00Z",
    )
    initial = {path.name: path.read_bytes() for path in output.iterdir()}
    create_metadata(
        assets=[first, second, preparer],
        output_directory=output,
        version="0.7.0",
        created="2026-08-26T12:00:00Z",
    )

    assert initial == {path.name: path.read_bytes() for path in output.iterdir()}
    assert set(initial) == {
        "checksums.txt",
        "license-manifest.json",
        "sbom.spdx.json",
    }
    sbom = json.loads(initial["sbom.spdx.json"])
    assert sbom["spdxVersion"] == "SPDX-2.3"
    assert len(sbom["packages"]) == 3
    licences = json.loads(initial["license-manifest.json"])
    assert licences["helper_runtime"]["contains_proprietary_components"] is False
    assert licences["desktop_preparer"]["contains_credentials"] is False


def test_release_notes_are_extracted_from_matching_section() -> None:
    changelog = (
        "# Changelog\n\n## [0.7.0] - 2026-08-26\n\n- Ready.\n\n"
        "## [0.6.0]\n\n- Earlier.\n"
    )

    notes = extract_release_notes(changelog, "0.7.0")

    assert notes == "## Owlet Cam 0.7.0\n\n- Ready.\n"


def test_release_notes_require_matching_non_empty_section() -> None:
    with pytest.raises(ValueError, match="no non-empty section"):
        extract_release_notes("# Changelog\n", "0.7.0")


def test_release_inspector_accepts_expected_archives(tmp_path: Path) -> None:
    integration = tmp_path / "ha-owlet-cam.zip"
    with zipfile.ZipFile(integration, "w") as archive:
        archive.writestr("custom_components/owlet_cam/manifest.json", b"{}")
    helper = tmp_path / "owlet-cam-helper-aarch64.tar.gz"
    with tarfile.open(helper, "w:gz") as archive:
        for name in ("bin/frame_probe", "runtime/lib64/libc.so"):
            content = b"open-source-runtime"
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, BytesIO(content))

    inspect_archive(integration)
    inspect_archive(helper)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("lib/libIOTCAPIs.so", b"proprietary"),
        ("uploads/application.xapk", b"proprietary"),
        ("runtime/config.json", b"AIza" + b"A" * 35),
    ],
)
def test_release_inspector_rejects_prohibited_material(
    tmp_path: Path, name: str, content: bytes
) -> None:
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(name, content)

    with pytest.raises(ValueError, match="contains"):
        inspect_archive(archive_path)


def test_release_inspector_rejects_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape", b"bad")

    with pytest.raises(ValueError, match="unsafe path"):
        inspect_archive(archive_path)
