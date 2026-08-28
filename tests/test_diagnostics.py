"""Diagnostics redaction tests."""

import json
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.owlet_cam.const import CONF_MODE, DOMAIN, MODE_EMBEDDED
from custom_components.owlet_cam.data import OwletCamRuntimeData
from custom_components.owlet_cam.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redact_every_secret_fixture(hass: HomeAssistant) -> None:
    """Configured secrets must not survive serialized diagnostics."""
    secrets = {
        "email": "parent@example.invalid",
        "password": "fixture-" + "account-password",
        "firebase_token": "fixture-" + "firebase-token",
        "uid": "fixture-" + "camera-uid",
        "auth_key": "fixture-" + "auth-key",
        "av_password": "fixture-" + "av-password",
        "sdk_key": "fixture-" + "sdk-key",
        "bridge_password": "fixture-" + "bridge-password",
        "bridge_token": "fixture-" + "bridge-token",
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Diagnostics",
        data={CONF_MODE: MODE_EMBEDDED, **secrets},
        options={
            "stream_path_token": "fixture-" + "stream-path",
            "explicit_rtsp_source": (
                "rtsp://fixture-user:fixture-stream-secret@bridge.invalid/camera"
            ),
        },
        unique_id="diagnostics",
    )
    entry.add_to_hass(hass)
    entry.runtime_data = OwletCamRuntimeData(
        client=None,
        coordinator=SimpleNamespace(
            data={"status": "ready"},
            last_update_success=True,
            last_exception=None,
        ),
        runtime_manager=None,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(diagnostics, sort_keys=True)

    for secret in (
        *secrets.values(),
        "fixture-stream-path",
        "fixture-stream-secret",
    ):
        assert secret not in serialized
    assert "**REDACTED**" in serialized
