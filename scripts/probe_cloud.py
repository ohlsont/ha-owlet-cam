#!/usr/bin/env python3
"""Run a redacted real-account Owlet cloud/KMS capability probe."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import stat
import sys
from pathlib import Path
from typing import Final

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.owlet_cam.api.cloud import OwletCloudClient  # noqa: E402
from custom_components.owlet_cam.api.exceptions import OwletCamError  # noqa: E402
from custom_components.owlet_cam.const import (  # noqa: E402
    REGION_EUROPE,
)

ENV_FILE: Final = ROOT / ".env"
_ENV_KEYS: Final = frozenset(
    {"OWLET_REGION", "OWLET_EMAIL", "OWLET_PASSWORD", "OWLET_IDENTIFIER"}
)
_REGION_ALIASES: Final = {
    "eu": "europe",
    "europe": "europe",
    "global": "world",
    "us": "world",
    "usa": "world",
    "world": "world",
}


class ProbeConfigurationError(ValueError):
    """A safe local probe configuration failure."""


def load_probe_env(path: Path) -> dict[str, str]:
    """Read selected probe values directly without exporting them to the OS env."""
    try:
        source_stat = path.lstat()
    except OSError as error:
        raise ProbeConfigurationError("The local .env file cannot be read") from error
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise ProbeConfigurationError("The local .env file must be a regular file")
    if stat.S_IMODE(source_stat.st_mode) & 0o077:
        raise ProbeConfigurationError("The local .env file must have mode 0600")
    if hasattr(os, "getuid") and source_stat.st_uid != os.getuid():
        raise ProbeConfigurationError("The local .env file must be owned by this user")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ProbeConfigurationError("The local .env file cannot be read") from error

    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        key = key.strip()
        if not separator or key not in _ENV_KEYS:
            continue
        if key in values:
            raise ProbeConfigurationError("The local .env file has a duplicate key")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def normalize_probe_region(value: str) -> str:
    """Map user-facing region aliases to the integration's cloud regions."""
    normalized = value.strip().lower()
    try:
        return _REGION_ALIASES[normalized]
    except KeyError as error:
        raise ProbeConfigurationError("Unsupported Owlet region") from error


async def async_probe(
    session: aiohttp.ClientSession,
    *,
    email: str,
    password: str,
    region: str,
    camera_dsn: str,
) -> dict[str, object]:
    """Authenticate and return only redacted camera-credential presence facts."""
    client = OwletCloudClient(
        session,
        email=email,
        password=password,
        region=region,
    )
    metadata = await client.async_validate_camera(camera_dsn)
    return {
        "ok": True,
        "region": region,
        "camera_dsn_valid": True,
        "camera_uid_available": metadata.camera_uid_available,
        "auth_key_available": metadata.auth_key_available,
        "av_password_available": metadata.av_password_available,
        "credentials_available": metadata.credentials_available,
        "authentication_expiry_utc": metadata.token_expiry.isoformat(),
    }


def safe_error_report(error: OwletCamError) -> dict[str, object]:
    """Return a redacted, machine-readable error from a safe typed exception."""
    report: dict[str, object] = {
        "ok": False,
        "error_code": type(error).__name__,
        "message": str(error),
    }
    reason = getattr(error, "reason", None)
    if isinstance(reason, str):
        report["reason"] = reason
    http_status = getattr(error, "http_status", None)
    if isinstance(http_status, int):
        report["http_status"] = http_status
    return report


async def async_run(*, email: str, password: str, region: str, camera_dsn: str) -> int:
    """Run the network portion of the interactive probe."""
    try:
        async with aiohttp.ClientSession() as session:
            report = await async_probe(
                session,
                email=email,
                password=password,
                region=region,
                camera_dsn=camera_dsn,
            )
    except OwletCamError as error:
        report = safe_error_report(error)
    finally:
        email = ""
        password = ""
        camera_dsn = ""

    print(json.dumps(report, indent=2))
    return 0 if report["ok"] is True else 1


def main() -> int:
    """Run the asynchronous interactive probe."""
    values: dict[str, str] = {}
    try:
        parser = argparse.ArgumentParser(
            description="Run a redacted Owlet cloud/KMS capability probe"
        )
        parser.add_argument(
            "--region",
            choices=tuple(sorted(_REGION_ALIASES)),
            help="Non-secret region override; US maps to world",
        )
        args = parser.parse_args()
        if ENV_FILE.exists():
            values = load_probe_env(ENV_FILE)
        region_input = args.region or values.get("OWLET_REGION", "")
        if not region_input:
            region_input = input("Region [europe/world] (default europe): ").strip()
        region = normalize_probe_region(region_input or REGION_EUROPE)

        email = (
            values.get("OWLET_EMAIL", "")
            or getpass.getpass("Owlet email (hidden): ").strip()
        )
        password = values.get("OWLET_PASSWORD", "") or getpass.getpass(
            "Owlet password (hidden): "
        )
        camera_dsn = values.get("OWLET_IDENTIFIER", "") or getpass.getpass(
            "Camera DSN/serial (hidden): "
        )
        try:
            return asyncio.run(
                async_run(
                    email=email,
                    password=password,
                    region=region,
                    camera_dsn=camera_dsn,
                )
            )
        finally:
            email = ""
            password = ""
            camera_dsn = ""
            values.clear()
    except ProbeConfigurationError as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": type(error).__name__,
                    "message": str(error),
                },
                indent=2,
            )
        )
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nProbe cancelled; no credentials were stored.", file=sys.stderr)
        return 130
    finally:
        values.clear()


if __name__ == "__main__":
    raise SystemExit(main())
