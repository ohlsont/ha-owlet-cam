"""Disabled-by-default runtime control tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.owlet_cam.button import (
    _AUTHENTICATION_TEST,
    _FRAME_PROBE,
    _RESTART_STREAM,
    _RUNTIME_PROBE,
    _STREAM_PROBE,
    OwletCamRuntimeProbeButton,
)
from custom_components.owlet_cam.const import (
    CONF_CAMERA_DSN,
    CONF_CAMERA_NAME,
    DOMAIN,
)
from custom_components.owlet_cam.runtime.manager import (
    OwletRuntimeError,
    OwletRuntimeManager,
)


def _button(description):
    manager = MagicMock(spec=OwletRuntimeManager)
    manager.stream_available = True
    manager.frame_probe_available = True
    manager.supported_architecture = True
    manager.async_run_stream_probe = AsyncMock()
    manager.async_restart_stream = AsyncMock()
    manager.async_run_authentication_test = AsyncMock()
    manager.async_run_frame_probe = AsyncMock()
    manager.async_prepare_and_probe_libraries = AsyncMock()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Nursery",
        data={CONF_CAMERA_DSN: "OCD123456789", CONF_CAMERA_NAME: "Nursery"},
    )
    entry.runtime_data = SimpleNamespace(runtime_manager=manager)
    return OwletCamRuntimeProbeButton(entry, description=description), manager


@pytest.mark.parametrize(
    ("description", "method"),
    [
        (_STREAM_PROBE, "async_run_stream_probe"),
        (_RESTART_STREAM, "async_restart_stream"),
        (_AUTHENTICATION_TEST, "async_run_authentication_test"),
        (_FRAME_PROBE, "async_run_frame_probe"),
        (_RUNTIME_PROBE, "async_prepare_and_probe_libraries"),
    ],
)
async def test_runtime_buttons_use_cached_gate_and_bounded_action(
    description, method
) -> None:
    button, manager = _button(description)

    assert button.available
    await button.async_press()

    getattr(manager, method).assert_awaited_once_with()


async def test_runtime_button_translates_safe_runtime_error() -> None:
    button, manager = _button(_RUNTIME_PROBE)
    manager.async_prepare_and_probe_libraries.side_effect = OwletRuntimeError(
        "invalid_apk", "Safe runtime failure"
    )

    with pytest.raises(HomeAssistantError, match="Safe runtime failure"):
        await button.async_press()


def test_runtime_button_rejects_missing_manager() -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Nursery",
        data={CONF_CAMERA_DSN: "OCD123456789", CONF_CAMERA_NAME: "Nursery"},
    )
    entry.runtime_data = SimpleNamespace(runtime_manager=None)

    with pytest.raises(RuntimeError, match="unavailable"):
        OwletCamRuntimeProbeButton(entry, description=_RUNTIME_PROBE)
