"""Diagnostic sensor tests."""

from unittest.mock import Mock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.owlet_cam.const import CONF_MODE, DOMAIN, MODE_DEVELOPMENT


async def test_sensor_properties_use_cached_coordinator_data(
    hass: HomeAssistant,
) -> None:
    """Reading entity state must never touch a network or filesystem client."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Owlet Cam Development",
        data={CONF_MODE: MODE_DEVELOPMENT},
        unique_id=MODE_DEVELOPMENT,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.client = Mock(side_effect=AssertionError("I/O attempted"))

    state = hass.states.get("sensor.owlet_cam_integration_status")
    assert state is not None
    assert state.state == "ready"
    entry.runtime_data.client.assert_not_called()
