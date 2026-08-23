"""Runtime repair issue lifecycle tests."""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.owlet_cam.api.cloud import OwletCloudClient
from custom_components.owlet_cam.repairs import (
    async_remove_runtime_issues,
    async_sync_runtime_issues,
)
from custom_components.owlet_cam.runtime.manager import OwletRuntimeManager


async def test_repair_appears_and_disappears_with_safe_error(
    hass: HomeAssistant, tmp_path
) -> None:
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )
    with patch(
        "custom_components.owlet_cam.runtime.manager._normalized_machine",
        return_value="aarch64",
    ):
        manager.snapshot.last_error_code = "missing_apk"
        async_sync_runtime_issues(hass, "entry", manager)
        assert ir.async_get(hass).async_get_issue("owlet_cam", "entry_missing_apk")

        manager.snapshot.last_error_code = None
        async_sync_runtime_issues(hass, "entry", manager)
        assert (
            ir.async_get(hass).async_get_issue("owlet_cam", "entry_missing_apk") is None
        )


async def test_unload_removes_owned_repairs(hass: HomeAssistant, tmp_path) -> None:
    manager = OwletRuntimeManager(
        hass,
        root=tmp_path,
        client=AsyncMock(spec=OwletCloudClient),
        camera_identifier="OCD123456789",
    )
    with patch(
        "custom_components.owlet_cam.runtime.manager._normalized_machine",
        return_value="aarch64",
    ):
        manager.snapshot.last_error_code = "missing_sdk_key"
        async_sync_runtime_issues(hass, "entry", manager)
    async_remove_runtime_issues(hass, "entry")
    assert not ir.async_get(hass).issues
