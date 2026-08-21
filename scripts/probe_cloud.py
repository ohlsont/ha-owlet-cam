#!/usr/bin/env python3
"""Run a redacted real-account Owlet cloud/KMS capability probe."""

from __future__ import annotations

import asyncio
import getpass
import json
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.owlet_cam.api.cloud import OwletCloudClient  # noqa: E402
from custom_components.owlet_cam.api.exceptions import OwletCamError  # noqa: E402
from custom_components.owlet_cam.const import (  # noqa: E402
    REGION_EUROPE,
    REGIONS,
)


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
    return {
        "ok": False,
        "error_code": type(error).__name__,
        "message": str(error),
    }


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
    try:
        region_input = input("Region [europe/world] (default europe): ").strip().lower()
        region = region_input or REGION_EUROPE
        if region not in REGIONS:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error_code": "OwletUnsupportedRegionError",
                        "message": "Unsupported Owlet region",
                    },
                    indent=2,
                )
            )
            return 1

        email = getpass.getpass("Owlet email (hidden): ").strip()
        password = getpass.getpass("Owlet password (hidden): ")
        camera_dsn = getpass.getpass("Camera DSN/serial (hidden): ")
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
    except (EOFError, KeyboardInterrupt):
        print("\nProbe cancelled; no credentials were stored.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
