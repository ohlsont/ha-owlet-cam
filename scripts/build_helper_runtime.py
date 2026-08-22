#!/usr/bin/env python3
"""Create a deterministic, proprietary-free ARM64 helper runtime archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
VERSION: Final = "0.6.0-dev"
ARCHITECTURE: Final = "aarch64"
AOSP_COMMIT: Final = "070571b455076f77a01c7b07154a15e545d2b428"
AOSP_APEX_SHA256: Final = (
    "83bf0dce249728dae48149b80d28b48115c54adad95a352120d58a6ac669d1fc"
)
BUILD_IMAGE: Final = (
    "debian@sha256:1710bde34461551a19a47c787885ec9ad7058d9a5bead2affb8d088fa2f8502b"
)
_RUNTIME_FILES: Final = {
    "runtime/bin/linker64": "bin/linker64",
    "runtime/lib64/libc.so": "lib64/libc.so",
    "runtime/lib64/libdl.so": "lib64/libdl.so",
    "runtime/lib64/libm.so": "lib64/libm.so",
}


def build_runtime_archive(
    *,
    frame_probe: Path,
    snapshot_capture: Path,
    stream_capture: Path,
    library_probe: Path,
    runtime_root: Path,
    aosp_notice: Path,
    output: Path,
) -> str:
    """Build one deterministic tar.gz and return its SHA-256."""
    inputs = {
        "bin/frame_probe": frame_probe,
        "bin/snapshot_capture": snapshot_capture,
        "bin/stream_capture": stream_capture,
        "bin/probe_libraries": library_probe,
        **{
            archive_path: runtime_root / source_path
            for archive_path, source_path in _RUNTIME_FILES.items()
        },
        "LICENSES/AOSP-NOTICE.html.gz": aosp_notice,
        "LICENSES/OWLET-CAM-MIT.txt": ROOT / "LICENSE",
    }
    for path in inputs.values():
        _require_regular_file(path)

    with tempfile.TemporaryDirectory(prefix="owlet-helper-package-") as temporary:
        staging = Path(temporary)
        hashes: dict[str, str] = {}
        for relative, source in sorted(inputs.items()):
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            if relative in {
                "bin/frame_probe",
                "bin/probe_libraries",
                "bin/snapshot_capture",
                "bin/stream_capture",
                "runtime/bin/linker64",
            }:
                mode = 0o700
            elif relative.startswith("runtime/lib64/"):
                mode = 0o500
            else:
                mode = 0o400
            destination.chmod(mode)
            hashes[relative] = _sha256(destination)

        manifest = {
            "schema_version": 1,
            "version": VERSION,
            "architecture": ARCHITECTURE,
            "files": hashes,
            "build": {
                "aosp_commit": AOSP_COMMIT,
                "aosp_apex_sha256": AOSP_APEX_SHA256,
                "container_image": BUILD_IMAGE,
                "contains_proprietary_files": False,
            },
        }
        manifest_path = staging / "runtime-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest_path.chmod(0o400)

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_output = output.with_name(f".{output.name}.partial")
        try:
            with temporary_output.open("wb") as raw:
                with gzip.GzipFile(
                    fileobj=raw, mode="wb", mtime=0, filename=""
                ) as zipped:
                    with tarfile.open(fileobj=zipped, mode="w|") as archive:
                        for path in sorted(staging.rglob("*")):
                            if path.is_dir():
                                continue
                            relative = path.relative_to(staging).as_posix()
                            info = tarfile.TarInfo(relative)
                            data = path.read_bytes()
                            info.size = len(data)
                            info.mode = stat_mode(path)
                            info.mtime = 0
                            info.uid = 0
                            info.gid = 0
                            info.uname = "root"
                            info.gname = "root"
                            archive.addfile(info, io.BytesIO(data))
                raw.flush()
                os.fsync(raw.fileno())
            os.replace(temporary_output, output)
        finally:
            temporary_output.unlink(missing_ok=True)
    return _sha256(output)


def stat_mode(path: Path) -> int:
    """Return only permission bits for the deterministic archive header."""
    return path.stat().st_mode & 0o777


def _require_regular_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as err:
        raise ValueError("A helper build input is missing") from err
    if path.is_symlink() or not path.is_file() or metadata.st_size == 0:
        raise ValueError("A helper build input is not a regular non-empty file")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    """Build from explicit non-secret paths."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame-probe", type=Path, required=True)
    parser.add_argument("--snapshot-capture", type=Path, required=True)
    parser.add_argument("--stream-capture", type=Path, required=True)
    parser.add_argument("--library-probe", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--aosp-notice", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checksum = build_runtime_archive(
        frame_probe=args.frame_probe,
        snapshot_capture=args.snapshot_capture,
        stream_capture=args.stream_capture,
        library_probe=args.library_probe,
        runtime_root=args.runtime_root,
        aosp_notice=args.aosp_notice,
        output=args.output,
    )
    print(f"{checksum}  {args.output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
