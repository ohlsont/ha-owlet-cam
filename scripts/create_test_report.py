#!/usr/bin/env python3
"""Print reproducible local metadata for a TEST_REPORT evidence update."""

from __future__ import annotations

import platform
import subprocess


def main() -> int:
    """Print only non-secret build metadata."""
    commit = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], text=True
    ).strip()
    print(f"Commit: {commit}")
    print(f"Python: {platform.python_version()}")
    print(f"Architecture: {platform.machine()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
