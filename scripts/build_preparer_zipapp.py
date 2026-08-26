#!/usr/bin/env python3
"""Build the dependency-free desktop preparer as a deterministic zipapp."""

from __future__ import annotations

import argparse
import os
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
_ZIP_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)
_SOURCES: Final = {
    "__main__.py": ROOT / "scripts/prepare_runtime_package.py",
    "custom_components/__init__.py": None,
    "custom_components/owlet_cam/__init__.py": None,
    "custom_components/owlet_cam/runtime/__init__.py": None,
    "custom_components/owlet_cam/runtime/apk.py": (
        ROOT / "custom_components/owlet_cam/runtime/apk.py"
    ),
}


def build_zipapp(output: Path) -> None:
    """Write a standalone source zipapp with stable bytes and private mode."""
    output.parent.mkdir(parents=True, exist_ok=True)
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
                for name, source in sorted(_SOURCES.items()):
                    content = b"" if source is None else source.read_bytes()
                    info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o400) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, content, compresslevel=9)
            stream.flush()
            os.fsync(stream.fileno())
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, output)
        output.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Build one preparer zipapp."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_zipapp(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
