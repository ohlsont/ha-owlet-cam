#!/usr/bin/env python3
"""Extract one version section from CHANGELOG.md."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def extract_release_notes(changelog: str, version: str) -> str:
    """Return one non-empty bracketed changelog section."""
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\](?:[^\n]*)\n(?P<body>.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(changelog)
    if match is None or not (body := match.group("body").strip()):
        raise ValueError("CHANGELOG.md has no non-empty section for the release")
    return f"## Owlet Cam {version}\n\n{body}\n"


def main() -> int:
    """Extract release notes from command-line inputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    notes = extract_release_notes(
        args.changelog.read_text(encoding="utf-8"), args.version
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(notes, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
