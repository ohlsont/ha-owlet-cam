"""Diagnostics support for Owlet Cam."""

import platform
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import __version__ as home_assistant_version
from homeassistant.core import HomeAssistant

from .const import INTEGRATION_VERSION, REDACT_KEYS
from .data import OwletCamConfigEntry


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant,
    entry: OwletCamConfigEntry,
) -> dict[str, Any]:
    """Return secret-safe diagnostics for a config entry."""
    runtime = entry.runtime_data
    coordinator_data = runtime.coordinator.data
    expiry = coordinator_data.get("authentication_expiry")
    return {
        "integration_version": INTEGRATION_VERSION,
        "home_assistant_version": home_assistant_version,
        "architecture": platform.machine(),
        "config_entry": async_redact_data(dict(entry.data), REDACT_KEYS),
        "options": async_redact_data(dict(entry.options), REDACT_KEYS),
        "runtime": {
            "mode": entry.data.get("mode", "unknown"),
            "coordinator_last_update_success": runtime.coordinator.last_update_success,
            "camera_count": len(runtime.cameras),
            "camera": {
                "identifier": "**REDACTED**" if runtime.cameras else None,
                "model": "Owlet Cam" if runtime.cameras else None,
                "firmware": None,
            },
            "native_helper_configured": runtime.runtime_manager is not None,
            "cloud_reachable": coordinator_data.get("cloud_reachable"),
            "camera_credentials_available": coordinator_data.get(
                "credentials_available"
            ),
            "authentication_expiry": (
                expiry.isoformat() if hasattr(expiry, "isoformat") else None
            ),
            "coordinator": {
                "last_update_success": runtime.coordinator.last_update_success,
                "last_exception_type": (
                    type(runtime.coordinator.last_exception).__name__
                    if runtime.coordinator.last_exception is not None
                    else None
                ),
            },
            "embedded_runtime": (
                runtime.runtime_manager.diagnostics()
                if runtime.runtime_manager is not None
                else None
            ),
        },
    }
