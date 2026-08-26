#!/usr/bin/env python3
"""Create checksums, an SPDX SBOM, and a release licence manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def create_metadata(
    *, assets: list[Path], output_directory: Path, version: str, created: str
) -> None:
    """Write deterministic release metadata for the supplied assets."""
    if not assets or any(not path.is_file() for path in assets):
        raise ValueError("Release assets must be non-empty regular files")
    output_directory.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "name": path.name,
            "sha256": sha256(path),
            "size": path.stat().st_size,
        }
        for path in sorted(assets, key=lambda item: item.name)
    ]
    (output_directory / "checksums.txt").write_text(
        "".join(f"{record['sha256']}  {record['name']}\n" for record in records),
        encoding="utf-8",
    )
    namespace_digest = hashlib.sha256(
        json.dumps(records, sort_keys=True).encode()
    ).hexdigest()
    packages = [
        {
            "SPDXID": f"SPDXRef-Asset-{index}",
            "name": record["name"],
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "checksums": [{"algorithm": "SHA256", "checksumValue": record["sha256"]}],
            "comment": f"Release asset; size={record['size']} bytes",
        }
        for index, record in enumerate(records, start=1)
    ]
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"ha-owlet-cam-{version}",
        "documentNamespace": (
            f"https://github.com/ohlsont/ha-owlet-cam/spdx/{version}/{namespace_digest}"
        ),
        "creationInfo": {
            "created": created,
            "creators": ["Tool: ha-owlet-cam-create-release-metadata"],
        },
        "packages": packages,
    }
    (output_directory / "sbom.spdx.json").write_text(
        json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    licence_manifest = {
        "schema_version": 1,
        "release_version": version,
        "project": {
            "name": "ha-owlet-cam",
            "license": "MIT",
            "notice": "LICENSE",
        },
        "helper_runtime": {
            "license": "Apache-2.0 AND MIT",
            "notices_in_archive": [
                "LICENSES/AOSP-NOTICE.html.gz",
                "LICENSES/OWLET-CAM-MIT.txt",
            ],
            "contains_proprietary_components": False,
        },
        "assets": records,
    }
    (output_directory / "license-manifest.json").write_text(
        json.dumps(licence_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    """Create release metadata from CLI arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("assets", nargs="+", type=Path)
    args = parser.parse_args()
    created = (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    create_metadata(
        assets=args.assets,
        output_directory=args.output_directory,
        version=args.version,
        created=created,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
