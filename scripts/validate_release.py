#!/usr/bin/env python3
"""Validate release metadata and proprietary-file exclusions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "owlet_cam"
PROHIBITED_SUFFIXES = {".apk", ".apkm", ".xapk", ".so"}


def release_source_files() -> list[Path]:
    """Return tracked and untracked release sources, excluding ignored runtime data."""
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    )
    return [ROOT / item.decode() for item in output.split(b"\0") if item]


def main() -> int:
    """Run deterministic release checks."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())
    pyproject = (ROOT / "pyproject.toml").read_text()

    required = {
        "domain",
        "name",
        "version",
        "codeowners",
        "config_flow",
        "documentation",
        "issue_tracker",
        "integration_type",
        "iot_class",
        "requirements",
    }
    missing = required - manifest.keys()
    if missing:
        raise SystemExit(f"manifest missing keys: {sorted(missing)}")
    if manifest["domain"] != "owlet_cam":
        raise SystemExit("manifest domain must be owlet_cam")
    if f'version = "{manifest["version"]}"' not in pyproject:
        raise SystemExit("manifest and pyproject versions differ")
    if hacs != {
        "name": "Owlet Cam",
        "homeassistant": "2024.11.0",
        "persistent_directory": "userfiles",
    }:
        raise SystemExit("hacs.json persistence or compatibility policy changed")

    prohibited = [
        path.relative_to(ROOT)
        for path in release_source_files()
        if path.is_file() and path.suffix.lower() in PROHIBITED_SUFFIXES
    ]
    if prohibited:
        raise SystemExit(f"prohibited release files: {prohibited}")
    print(f"release metadata valid for {manifest['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
