"""Config-entry lifecycle tests."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.owlet_cam.const import (
    CONF_MODE,
    DOMAIN,
    MODE_DEVELOPMENT,
)

ENTITY_ID = "sensor.owlet_cam_integration_status"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Owlet Cam Development",
        data={CONF_MODE: MODE_DEVELOPMENT},
        unique_id=MODE_DEVELOPMENT,
    )


async def test_setup_unload_and_reload(hass: HomeAssistant) -> None:
    """Setup, unload, and reload leave exactly one entity."""
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_ID) is not None
    assert len(hass.states.async_entity_ids("sensor")) == 1

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_ID) is not None
    assert len(hass.states.async_entity_ids("sensor")) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(ENTITY_ID) is None


async def test_remove_entry_cleanly(hass: HomeAssistant) -> None:
    """Removing an entry unloads its entity and leaves no integration tasks."""
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert hass.states.get(ENTITY_ID) is None
    assert not hass.services.async_services().get(DOMAIN)
