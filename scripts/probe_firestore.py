#!/usr/bin/env python3
"""Probe Owlet Firestore camera discovery without printing private values."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path
from typing import Any, Final

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.owlet_cam.api.cloud import (  # noqa: E402
    OwletCloudClient,
)
from custom_components.owlet_cam.api.exceptions import (  # noqa: E402
    OwletCamError,
    OwletConnectionError,
)
from custom_components.owlet_cam.const import REGION_EUROPE  # noqa: E402
from scripts.probe_cloud import (  # noqa: E402
    ENV_FILE,
    ProbeConfigurationError,
    load_probe_env,
    normalize_probe_region,
    safe_error_report,
)

_FIRESTORE_PROJECTS: Final = {
    "europe": "owletcare-prod-eu",
    "world": "owletcare-prod",
}
_STANDARD_TOKEN_CLAIMS: Final = frozenset(
    {
        "aud",
        "auth_time",
        "email",
        "email_verified",
        "exp",
        "firebase",
        "iat",
        "iss",
        "sub",
        "user_id",
    }
)


def _token_claim_shapes(token: str) -> dict[str, str]:
    """Describe custom token claim types without returning any claim value."""
    try:
        encoded_payload = token.split(".", maxsplit=2)[1]
        encoded_payload += "=" * (-len(encoded_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload))
    except (IndexError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: type(value).__name__
        for key, value in payload.items()
        if isinstance(key, str) and key not in _STANDARD_TOKEN_CLAIMS
    }


def _string_field(fields: object, name: str) -> str | None:
    """Extract one Firestore string without retaining the surrounding document."""
    if not isinstance(fields, dict):
        return None
    value = fields.get(name)
    if not isinstance(value, dict):
        return None
    string_value = value.get("stringValue")
    return string_value if isinstance(string_value, str) and string_value else None


def _map_keys_field(fields: object, name: str) -> list[str]:
    """Extract Firestore map keys without retaining their values."""
    if not isinstance(fields, dict):
        return []
    value = fields.get(name)
    if not isinstance(value, dict):
        return []
    map_value = value.get("mapValue")
    if not isinstance(map_value, dict):
        return []
    map_fields = map_value.get("fields")
    if not isinstance(map_fields, dict):
        return []
    return [key for key in map_fields if isinstance(key, str) and key]


async def _get_document(
    session: aiohttp.ClientSession,
    *,
    project: str,
    collection: str,
    document_id: str,
    token: str,
) -> tuple[int, dict[str, Any]]:
    """Fetch one already-known document ID without exposing its contents."""
    url = (
        "https://firestore.googleapis.com/v1/projects/"
        f"{project}/databases/(default)/documents/{collection}/{document_id}"
    )
    try:
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            status = response.status
            try:
                payload: object = await response.json(content_type=None)
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {}
    except TimeoutError as error:
        raise OwletConnectionError(
            "Owlet camera discovery timed out", reason="timeout"
        ) from error
    except aiohttp.ClientError as error:
        raise OwletConnectionError(
            "Owlet camera discovery connection failed", reason="connection_error"
        ) from error
    return status, payload if status == 200 and isinstance(payload, dict) else {}


async def async_run() -> int:
    """Run a real-account probe and emit only redacted facts."""
    values = load_probe_env(ENV_FILE)
    region = normalize_probe_region(values.get("OWLET_REGION", REGION_EUROPE))
    configured_identifier = values.get("OWLET_IDENTIFIER", "").strip().upper()
    report: dict[str, object] = {
        "ok": False,
        "region": region,
        "authentication": False,
    }
    try:
        async with aiohttp.ClientSession() as session:
            client = OwletCloudClient(
                session,
                email=values.get("OWLET_EMAIL", ""),
                password=values.get("OWLET_PASSWORD", ""),
                region=region,
            )
            # This diagnostic script intentionally consumes the client's in-memory
            # token. It is never serialized, logged, exported, or returned.
            token = await client._async_ensure_token()
            report["authentication"] = True
            report["custom_token_claim_shapes"] = _token_claim_shapes(token)

            account_id = client._account_id
            if account_id is None:
                raise RuntimeError("Authenticated client has no account identifier")
            user_status, user_document = await _get_document(
                session,
                project=_FIRESTORE_PROJECTS[region],
                collection="accountUsers",
                document_id=account_id,
                token=token,
            )
            user_fields = user_document.get("fields", {})
            report["signed_in_user_document"] = {
                "http_status": user_status,
                "field_names": (
                    sorted(user_fields) if isinstance(user_fields, dict) else []
                ),
            }

            account_status, account_document = await _get_document(
                session,
                project=_FIRESTORE_PROJECTS[region],
                collection="accounts",
                document_id=account_id,
                token=token,
            )
            account_fields = account_document.get("fields", {})
            service_keys = _map_keys_field(account_fields, "serviceKeys")
            report["account_document"] = {
                "http_status": account_status,
                "service_count": len(service_keys),
            }

            device_keys: list[str] = []
            service_statuses: list[int] = []
            for service_key in service_keys:
                status, service_document = await _get_document(
                    session,
                    project=_FIRESTORE_PROJECTS[region],
                    collection="services",
                    document_id=service_key,
                    token=token,
                )
                service_statuses.append(status)
                device_key = _string_field(service_document.get("fields"), "deviceKey")
                if device_key is not None:
                    device_keys.append(device_key)
            report["service_documents"] = {
                "requested_count": len(service_keys),
                "successful_count": service_statuses.count(200),
            }

            discovered_dsns: list[str] = []
            device_statuses: list[int] = []
            for device_key in device_keys:
                status, device_document = await _get_document(
                    session,
                    project=_FIRESTORE_PROJECTS[region],
                    collection="devices",
                    document_id=device_key,
                    token=token,
                )
                device_statuses.append(status)
                dsn = _string_field(device_document.get("fields"), "dsn")
                if dsn is not None:
                    discovered_dsns.append(dsn.strip().upper())
            report["device_documents"] = {
                "requested_count": len(device_keys),
                "successful_count": device_statuses.count(200),
            }
            report["camera_dsn_count"] = len(discovered_dsns)
            report["configured_identifier_matches_internal_dsn"] = (
                configured_identifier in discovered_dsns
            )

            if len(discovered_dsns) == 1:
                metadata = await client.async_validate_camera(discovered_dsns[0])
                report.update(
                    {
                        "ok": True,
                        "kms_lookup": True,
                        "camera_uid_available": metadata.camera_uid_available,
                        "auth_key_available": metadata.auth_key_available,
                        "av_password_available": metadata.av_password_available,
                    }
                )
            else:
                report["kms_lookup"] = False
    except OwletCamError as error:
        report["cloud_error"] = safe_error_report(error)
    finally:
        values.clear()
        configured_identifier = ""

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] is True else 1


def main() -> int:
    """Run the asynchronous probe with safe configuration failures."""
    try:
        return asyncio.run(async_run())
    except ProbeConfigurationError as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": type(error).__name__,
                    "message": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
