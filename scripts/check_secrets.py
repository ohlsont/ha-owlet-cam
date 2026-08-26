#!/usr/bin/env python3
"""Fail on prohibited binary material or common serialized token forms."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROHIBITED_SUFFIXES = {".apk", ".apkm", ".xapk", ".so"}
TOKEN_PATTERNS = {
    "JWT": re.compile(rb"eyJ[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{20,}"),
    "Google API key": re.compile(rb"AIza[0-9A-Za-z_-]{30,}"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def tracked_files() -> list[Path]:
    """Return tracked and untracked repository files, excluding ignored files."""
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    )
    return [ROOT / item.decode() for item in output.split(b"\0") if item]


def main() -> int:
    """Scan repository material without printing detected secret bytes."""
    failures: list[str] = []
    for path in tracked_files():
        if not path.is_file():
            continue
        if path.suffix.lower() in PROHIBITED_SUFFIXES:
            failures.append(f"prohibited file type: {path.relative_to(ROOT)}")
            continue
        if path == Path(__file__):
            continue
        content = path.read_bytes()
        for label, pattern in TOKEN_PATTERNS.items():
            if pattern.search(content):
                failures.append(f"{label} pattern: {path.relative_to(ROOT)}")
    if failures:
        raise SystemExit("secret scan failed\n" + "\n".join(failures))
    print(f"secret scan passed ({len(tracked_files())} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
