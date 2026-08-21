"""Diagnostics support for Owlet Cam."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import REDACT_KEYS
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
        "config_entry": async_redact_data(dict(entry.data), REDACT_KEYS),
        "options": async_redact_data(dict(entry.options), REDACT_KEYS),
        "runtime": {
            "mode": entry.data.get("mode", "unknown"),
            "coordinator_last_update_success": runtime.coordinator.last_update_success,
            "camera_count": len(runtime.cameras),
            "native_helper_running": runtime.runtime_manager is not None,
            "cloud_reachable": coordinator_data.get("cloud_reachable"),
            "camera_credentials_available": coordinator_data.get(
                "credentials_available"
            ),
            "authentication_expiry": (
                expiry.isoformat() if hasattr(expiry, "isoformat") else None
            ),
        },
    }
