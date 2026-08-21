"""Tests for clean-room Owlet cloud authentication and KMS validation."""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.owlet_cam.api import cloud
from custom_components.owlet_cam.api.cloud import (
    OwletCloudClient,
    normalize_camera_dsn,
)
from custom_components.owlet_cam.api.exceptions import (
    OwletAuthenticationError,
    OwletCameraNotFoundError,
    OwletConnectionError,
    OwletInvalidDSNError,
    OwletRateLimitError,
    OwletUnsupportedRegionError,
)
from custom_components.owlet_cam.const import REGION_EUROPE, REGION_WORLD
from scripts.probe_cloud import (
    ProbeConfigurationError,
    async_probe,
    load_probe_env,
    normalize_probe_region,
    safe_error_report,
)

EMAIL = "parent@example.invalid"
PASSWORD = "fixture-account-password"  # noqa: S105 - sanitized fixture
DSN = "OCD123456789"
ID_TOKEN = "fixture-firebase-token"  # noqa: S105 - sanitized fixture
REFRESH_TOKEN = "fixture-refresh-token"  # noqa: S105 - sanitized fixture
UID = "fixture-camera-uid"
AUTH_KEY = "fixture-auth-key"
AV_PASSWORD = "fixture-av-password"  # noqa: S105 - sanitized fixture

AUTH_RESPONSE = {
    "localId": "fixture-account-id",
    "email": EMAIL,
    "idToken": ID_TOKEN,
    "refreshToken": REFRESH_TOKEN,
    "expiresIn": "3600",
}
KMS_RESPONSE = {
    "tutkid": UID,
    "authKey": AUTH_KEY,
    "password": AV_PASSWORD,
}


def _client(hass: HomeAssistant, region: str = REGION_EUROPE) -> OwletCloudClient:
    return OwletCloudClient(
        async_get_clientsession(hass),
        email=EMAIL,
        password=PASSWORD,
        region=region,
        request_timeout=0.01,
    )


def _mock_auth(
    aioclient_mock: AiohttpClientMocker,
    client: OwletCloudClient,
    *,
    status: int = 200,
    response: object = AUTH_RESPONSE,
) -> None:
    aioclient_mock.post(
        cloud._FIREBASE_SIGN_IN_URL,
        params={"key": client._region_config.firebase_api_key},
        status=status,
        json=response,
    )


def _mock_kms(
    aioclient_mock: AiohttpClientMocker,
    *,
    status: int = 200,
    response: object = KMS_RESPONSE,
) -> None:
    aioclient_mock.get(
        cloud._KMS_URL.format(dsn=DSN),
        status=status,
        json=response,
    )


@pytest.mark.parametrize("region", [REGION_EUROPE, REGION_WORLD])
async def test_successful_region_login_and_kms(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    region: str,
) -> None:
    """European and world projects return only non-secret metadata."""
    client = _client(hass, region)
    _mock_auth(aioclient_mock, client)
    _mock_kms(aioclient_mock)

    metadata = await client.async_validate_camera(f"  {DSN.lower()}  ")

    assert metadata.account_id == "fixture-account-id"
    assert metadata.camera_dsn == DSN
    assert metadata.credentials_available
    assert metadata.camera_uid_available
    assert metadata.auth_key_available
    assert metadata.av_password_available
    assert metadata.token_expiry > datetime.now(UTC)
    auth_request = aioclient_mock.mock_calls[0]
    assert auth_request[3]["X-Android-Package"] == "com.owletcare.sleep"
    assert auth_request[3]["X-Android-Cert"]
    kms_request = aioclient_mock.mock_calls[1]
    assert kms_request[3]["Authorization"] == ID_TOKEN


@pytest.mark.parametrize(
    ("error_code", "exception_type"),
    [
        ("INVALID_PASSWORD", OwletAuthenticationError),
        ("EMAIL_NOT_FOUND", OwletAuthenticationError),
        ("INVALID_EMAIL", OwletAuthenticationError),
    ],
)
async def test_authentication_errors_are_typed_and_safe(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    error_code: str,
    exception_type: type[Exception],
) -> None:
    client = _client(hass)
    _mock_auth(
        aioclient_mock,
        client,
        status=400,
        response={"error": {"message": f"{error_code}: {PASSWORD}"}},
    )

    with pytest.raises(exception_type) as caught:
        await client.async_validate_camera(DSN)

    assert PASSWORD not in str(caught.value)


@pytest.mark.parametrize(
    ("status", "exception_type"),
    [
        (401, OwletAuthenticationError),
        (403, OwletCameraNotFoundError),
        (404, OwletCameraNotFoundError),
        (429, OwletRateLimitError),
        (500, OwletConnectionError),
    ],
)
async def test_kms_http_error_mapping(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    exception_type: type[Exception],
) -> None:
    client = _client(hass)
    _mock_auth(aioclient_mock, client)
    _mock_kms(aioclient_mock, status=status, response={"error": "safe"})

    with pytest.raises(exception_type):
        await client.async_validate_camera(DSN)


async def test_auth_rate_limit_and_server_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    rate_client = _client(hass)
    _mock_auth(aioclient_mock, rate_client, status=429, response={})
    with pytest.raises(OwletRateLimitError):
        await rate_client.async_validate_camera(DSN)

    aioclient_mock.clear_requests()
    server_client = _client(hass)
    _mock_auth(aioclient_mock, server_client, status=503, response={})
    with pytest.raises(OwletConnectionError):
        await server_client.async_validate_camera(DSN)


async def test_timeout_and_malformed_json(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    timeout_client = _client(hass)
    aioclient_mock.post(
        cloud._FIREBASE_SIGN_IN_URL,
        params={"key": timeout_client._region_config.firebase_api_key},
        exc=TimeoutError,
    )
    with pytest.raises(OwletConnectionError):
        await timeout_client.async_validate_camera(DSN)

    malformed_client = _client(hass)
    aioclient_mock.post(
        cloud._FIREBASE_SIGN_IN_URL,
        params={"key": malformed_client._region_config.firebase_api_key},
        text="not-json",
    )
    with pytest.raises(OwletConnectionError):
        await malformed_client.async_validate_camera(DSN)


async def test_client_connection_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    client = _client(hass)
    aioclient_mock.post(
        cloud._FIREBASE_SIGN_IN_URL,
        params={"key": client._region_config.firebase_api_key},
        exc=aiohttp.ClientConnectionError("safe"),
    )
    with pytest.raises(OwletConnectionError):
        await client.async_validate_camera(DSN)


async def test_incomplete_success_responses_are_rejected(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    auth_client = _client(hass)
    _mock_auth(aioclient_mock, auth_client, response={"idToken": ID_TOKEN})
    with pytest.raises(OwletConnectionError):
        await auth_client.async_validate_camera(DSN)

    kms_client = _client(hass)
    _mock_auth(aioclient_mock, kms_client)
    _mock_kms(aioclient_mock, response={"unexpected": True})
    with pytest.raises(OwletConnectionError):
        await kms_client.async_validate_camera(DSN)


async def test_partial_kms_metadata_is_presence_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    client = _client(hass)
    _mock_auth(aioclient_mock, client)
    _mock_kms(aioclient_mock, response={"tutkid": UID})

    metadata = await client.async_validate_camera(DSN)

    assert metadata.camera_uid_available
    assert not metadata.auth_key_available
    assert not metadata.av_password_available
    assert not metadata.credentials_available


async def test_expired_token_refreshes_without_password_login(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    client = _client(hass)
    _mock_auth(aioclient_mock, client)
    _mock_kms(aioclient_mock)
    await client.async_validate_camera(DSN)
    client._token_expiry = datetime.now(UTC) - timedelta(seconds=1)

    aioclient_mock.post(
        cloud._FIREBASE_REFRESH_URL,
        params={"key": client._region_config.firebase_api_key},
        json={
            "id_token": "fixture-refreshed-token",
            "refresh_token": "fixture-new-refresh-token",
            "expires_in": "3600",
            "user_id": "fixture-account-id",
        },
    )
    _mock_kms(aioclient_mock)

    metadata = await client.async_validate_camera(DSN)

    assert metadata.credentials_available
    assert (
        len(
            [
                call
                for call in aioclient_mock.mock_calls
                if call[1].path.endswith("accounts:signInWithPassword")
            ]
        )
        == 1
    )


@pytest.mark.parametrize(
    ("value", "confused_zero"),
    [
        ("0CD123456789", True),
        ("0CA1234567890123", True),
        ("not-a-dsn", False),
        ("OCD12", False),
        ("", False),
    ],
)
def test_invalid_dsn_is_rejected(value: str, confused_zero: bool) -> None:
    with pytest.raises(OwletInvalidDSNError) as caught:
        normalize_camera_dsn(value)
    assert caught.value.confused_zero is confused_zero


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("OCD123456789", "OCD123456789"),
        ("OCA1234567890123", "OCA1234567890123"),
        ("  oca1234567890123  ", "OCA1234567890123"),
    ],
)
def test_valid_camera_prefixes_are_normalized(value: str, expected: str) -> None:
    assert normalize_camera_dsn(value) == expected


async def test_local_cloud_probe_reports_presence_without_secrets(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    client = _client(hass)
    _mock_auth(aioclient_mock, client)
    _mock_kms(aioclient_mock)

    report = await async_probe(
        async_get_clientsession(hass),
        email=EMAIL,
        password=PASSWORD,
        region=REGION_EUROPE,
        camera_dsn=DSN,
    )

    serialized = json.dumps(report)
    assert report["ok"] is True
    assert report["credentials_available"] is True
    for secret in (
        EMAIL,
        PASSWORD,
        DSN,
        ID_TOKEN,
        REFRESH_TOKEN,
        UID,
        AUTH_KEY,
        AV_PASSWORD,
    ):
        assert secret not in serialized


def test_local_cloud_probe_error_report_is_safe() -> None:
    report = safe_error_report(
        OwletAuthenticationError("Authentication failed", reason="client_rejected")
    )

    assert report == {
        "ok": False,
        "error_code": "OwletAuthenticationError",
        "message": "Authentication failed",
        "reason": "client_rejected",
    }

    connection_report = safe_error_report(
        OwletConnectionError("Invalid response", reason="invalid_json", http_status=403)
    )
    assert connection_report == {
        "ok": False,
        "error_code": "OwletConnectionError",
        "message": "Invalid response",
        "reason": "invalid_json",
        "http_status": 403,
    }


def test_local_cloud_probe_reads_private_env_without_exporting(
    tmp_path: Path,
) -> None:
    source = tmp_path / ".env"
    source.write_text(
        "\n".join(
            (
                "OWLET_REGION=US",
                f"OWLET_EMAIL={EMAIL}",
                f"OWLET_PASSWORD='{PASSWORD}'",
                f'OWLET_IDENTIFIER="{DSN}"',
            )
        )
    )
    source.chmod(0o600)

    values = load_probe_env(source)

    assert values == {
        "OWLET_REGION": "US",
        "OWLET_EMAIL": EMAIL,
        "OWLET_PASSWORD": PASSWORD,
        "OWLET_IDENTIFIER": DSN,
    }
    assert normalize_probe_region(values["OWLET_REGION"]) == REGION_WORLD


def test_local_cloud_probe_rejects_permissive_env_mode(tmp_path: Path) -> None:
    source = tmp_path / ".env"
    source.write_text(f"OWLET_PASSWORD={PASSWORD}\n")
    source.chmod(0o644)

    with pytest.raises(ProbeConfigurationError, match="mode 0600") as caught:
        load_probe_env(source)

    assert PASSWORD not in str(caught.value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("US", REGION_WORLD), ("world", REGION_WORLD), ("EU", REGION_EUROPE)],
)
def test_local_cloud_probe_region_aliases(value: str, expected: str) -> None:
    assert normalize_probe_region(value) == expected


async def test_unsupported_region_is_typed(hass: HomeAssistant) -> None:
    with pytest.raises(OwletUnsupportedRegionError):
        _client(hass, "antarctica")


async def test_no_secret_appears_in_logs_or_exception(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _client(hass)
    _mock_auth(
        aioclient_mock,
        client,
        status=400,
        response={
            "error": {
                "message": f"INVALID_PASSWORD:{PASSWORD}:{ID_TOKEN}:{UID}:{AUTH_KEY}"
            }
        },
    )

    with pytest.raises(OwletAuthenticationError) as caught:
        await client.async_validate_camera(DSN)

    captured = caplog.text + str(caught.value)
    for secret in (PASSWORD, ID_TOKEN, UID, AUTH_KEY, AV_PASSWORD):
        assert secret not in captured
