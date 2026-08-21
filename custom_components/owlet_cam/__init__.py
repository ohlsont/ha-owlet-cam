"""Owlet Cam integration lifecycle."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import PLATFORMS
from .coordinator import OwletCamCoordinator
from .data import OwletCamConfigEntry, OwletCamRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OwletCamConfigEntry,
) -> bool:
    """Set up Owlet Cam from a config entry."""
    entry.runtime_data = OwletCamRuntimeData(
        client=None,
        coordinator=OwletCamCoordinator(hass),
        runtime_manager=None,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: OwletCamConfigEntry,
) -> bool:
    """Unload Owlet Cam and all forwarded platforms."""
    registry = er.async_get(hass)
    entity_ids = [
        registry_entry.entity_id
        for registry_entry in er.async_entries_for_config_entry(
            registry, entry.entry_id
        )
    ]
    unloaded = bool(await hass.config_entries.async_unload_platforms(entry, PLATFORMS))
    if unloaded:
        # Current Home Assistant may restore an unavailable state for a
        # registry entity after platform unload. The milestone contract is
        # stricter: an unloaded Owlet Cam entry owns no state-machine entities.
        for entity_id in entity_ids:
            hass.states.async_remove(entity_id)
    return unloaded
