#!/usr/bin/env python3
"""Fail when release archives contain unsafe or prohibited material."""

from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Final

MAX_MEMBER_SIZE: Final = 128 * 1024 * 1024
MAX_TOTAL_SIZE: Final = 512 * 1024 * 1024
PROPRIETARY_NAMES: Final = {
    "libavapis.so",
    "libiotcapis.so",
    "libp2ptunnelapis.so",
    "librdtapis.so",
    "libtutkglobalapis.so",
}
ALLOWED_OPEN_SOURCE_LIBRARIES: Final = {
    "runtime/lib64/libc.so",
    "runtime/lib64/libdl.so",
    "runtime/lib64/libm.so",
}
SECRET_PATTERNS: Final = {
    "JWT": re.compile(rb"eyJ[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{20,}"),
    "Google API key": re.compile(rb"AIza[0-9A-Za-z_-]{30,}"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def _validate_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Archive contains an unsafe path")
    lowered = path.name.lower()
    if lowered in PROPRIETARY_NAMES or lowered.endswith((".apk", ".apkm", ".xapk")):
        raise ValueError("Archive contains prohibited proprietary material")
    if lowered.endswith(".so") and path.as_posix() not in ALLOWED_OPEN_SOURCE_LIBRARIES:
        raise ValueError("Archive contains an unapproved shared library")
    return path


def _zip_members(path: Path) -> Iterator[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            _validate_name(info.filename)
            if info.file_size > MAX_MEMBER_SIZE:
                raise ValueError("Archive member is too large")
            yield info.filename, archive.read(info)


def _tar_members(path: Path) -> Iterator[tuple[str, bytes]]:
    with tarfile.open(path, mode="r:*") as archive:
        for info in archive:
            if info.isdir():
                continue
            _validate_name(info.name)
            if not info.isfile() or info.issym() or info.islnk():
                raise ValueError("Archive contains a non-regular member")
            if info.size > MAX_MEMBER_SIZE:
                raise ValueError("Archive member is too large")
            source = archive.extractfile(info)
            if source is None:
                raise ValueError("Archive member cannot be read")
            yield info.name, source.read()


def inspect_archive(path: Path) -> None:
    """Validate archive paths, member allowlists, sizes, and secret patterns."""
    if zipfile.is_zipfile(path):
        members = _zip_members(path)
    elif tarfile.is_tarfile(path):
        members = _tar_members(path)
    else:
        raise ValueError("Release asset is not a supported archive")
    total = 0
    count = 0
    for _name, content in members:
        count += 1
        total += len(content)
        if total > MAX_TOTAL_SIZE:
            raise ValueError("Archive expands beyond the release limit")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                raise ValueError(f"Archive contains a {label} pattern")
    if count == 0:
        raise ValueError("Release archive is empty")


def main() -> int:
    """Inspect every supplied release archive."""
    parser = argparse.ArgumentParser()
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args()
    for archive in args.archives:
        inspect_archive(archive)
        print(f"release archive accepted: {archive.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
