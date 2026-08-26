"""Authenticated application upload storage tests."""

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from custom_components.owlet_cam.runtime.upload import (
    MAXIMUM_UPLOAD_SIZE,
    OwletUploadError,
    async_store_upload,
    store_uploaded_path,
)


async def _chunks(*values: bytes):
    for value in values:
        yield value


async def test_upload_streams_to_generated_private_path(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    uploads = tmp_path / "uploads"

    stored = await async_store_upload(
        hass,
        uploads,
        _chunks(b"first", b"-second"),
        suffix=".XAPK",
        content_length=12,
    )

    files = list(uploads.iterdir())
    assert len(files) == 1
    assert files[0].name == f"application-{stored.sha256[:16]}.xapk"
    assert files[0].read_bytes() == b"first-second"
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert stored.size == 12


async def test_upload_accepts_compact_runtime_package(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    stored = await async_store_upload(
        hass,
        tmp_path / "uploads",
        _chunks(b"compact-runtime"),
        suffix=".OWLETCAM",
        content_length=15,
    )

    files = list((tmp_path / "uploads").iterdir())
    assert files[0].name == f"application-{stored.sha256[:16]}.owletcam"


def test_file_selector_upload_is_stored_privately(tmp_path: Path) -> None:
    """A native file-selector source is atomically copied with no original name."""
    source = tmp_path / "my-personal-runtime.owletcam"
    source.write_bytes(b"compact-user-owned-runtime-package")

    stored = store_uploaded_path(source, tmp_path / "uploads")

    files = list((tmp_path / "uploads").iterdir())
    assert stored.size == source.stat().st_size
    assert files == [
        tmp_path / "uploads" / f"application-{stored.sha256[:16]}.owletcam"
    ]
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert "my-personal-runtime" not in files[0].name


def test_file_selector_upload_rejects_wrong_type(tmp_path: Path) -> None:
    """The backend enforces the suffix even if a frontend accept hint is bypassed."""
    source = tmp_path / "runtime.txt"
    source.write_bytes(b"not-a-runtime-package")

    with pytest.raises(OwletUploadError) as caught:
        store_uploaded_path(source, tmp_path / "uploads")

    assert caught.value.code == "unsupported_archive"
    assert not (tmp_path / "uploads").exists()


def test_file_selector_upload_rejects_missing_and_symlink_sources(
    tmp_path: Path,
) -> None:
    """The trusted file ID still cannot redirect storage through a source symlink."""
    with pytest.raises(OwletUploadError) as missing:
        store_uploaded_path(tmp_path / "missing.owletcam", tmp_path / "uploads")
    assert missing.value.code == "upload_unavailable"

    target = tmp_path / "target.owletcam"
    target.write_bytes(b"runtime")
    link = tmp_path / "link.owletcam"
    link.symlink_to(target)
    with pytest.raises(OwletUploadError) as symlink:
        store_uploaded_path(link, tmp_path / "uploads")
    assert symlink.value.code == "unsafe_upload"


def test_file_selector_upload_rejects_empty_and_oversized_sources(
    tmp_path: Path,
) -> None:
    """Declared file size gates run before private temporary storage is created."""
    empty = tmp_path / "empty.owletcam"
    empty.touch()
    with pytest.raises(OwletUploadError) as empty_error:
        store_uploaded_path(empty, tmp_path / "uploads")
    assert empty_error.value.code == "upload_too_large"

    oversized = tmp_path / "oversized.owletcam"
    with oversized.open("wb") as oversized_file:
        oversized_file.truncate(MAXIMUM_UPLOAD_SIZE + 1)
    with pytest.raises(OwletUploadError) as oversized_error:
        store_uploaded_path(oversized, tmp_path / "uploads")
    assert oversized_error.value.code == "upload_too_large"
    assert not (tmp_path / "uploads").exists()


async def test_upload_atomically_replaces_previous_archive(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    previous = uploads / "previous.apk"
    previous.write_bytes(b"old")

    await async_store_upload(
        hass,
        uploads,
        _chunks(b"new"),
        suffix=".apk",
        content_length=3,
    )

    files = list(uploads.iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b"new"
    assert not previous.exists()


@pytest.mark.parametrize("suffix", ["", ".exe", "../camera.apk", ".apk/evil"])
async def test_upload_rejects_unsupported_suffix(
    hass: HomeAssistant, tmp_path: Path, suffix: str
) -> None:
    with pytest.raises(OwletUploadError, match="Unsupported") as caught:
        await async_store_upload(
            hass,
            tmp_path / "uploads",
            _chunks(b"fixture"),
            suffix=suffix,
            content_length=7,
        )
    assert caught.value.code == "unsupported_archive"
    assert not (tmp_path / "uploads").exists()


async def test_upload_rejects_declared_oversize_before_disk_write(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    with pytest.raises(OwletUploadError) as caught:
        await async_store_upload(
            hass,
            tmp_path / "uploads",
            _chunks(b"fixture"),
            suffix=".apk",
            content_length=MAXIMUM_UPLOAD_SIZE + 1,
        )
    assert caught.value.code == "upload_too_large"
    assert not (tmp_path / "uploads").exists()


async def test_failed_upload_removes_partial_file(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    async def failing_content():
        yield b"partial"
        raise OSError("fixture failure")

    with pytest.raises(OSError, match="fixture failure"):
        await async_store_upload(
            hass,
            tmp_path / "uploads",
            failing_content(),
            suffix=".apk",
            content_length=None,
        )
    assert not list((tmp_path / "uploads").iterdir())


async def test_upload_rejects_symlinked_storage(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    uploads = tmp_path / "uploads"
    uploads.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OwletUploadError) as caught:
        await async_store_upload(
            hass,
            uploads,
            _chunks(b"fixture"),
            suffix=".apk",
            content_length=7,
        )

    assert caught.value.code == "unsafe_upload_storage"
    assert not list(outside.iterdir())
