"""Owlet Cam integration lifecycle."""

from datetime import timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.cloud import OwletCloudClient
from .api.models import OwletCameraData
from .const import (
    CONF_CAMERA_DSN,
    CONF_CAMERA_NAME,
    CONF_EMAIL,
    CONF_IDLE_TIMEOUT,
    CONF_KEEP_WARM,
    CONF_MODE,
    CONF_NO_FRAME_TIMEOUT,
    CONF_PASSWORD,
    CONF_RECONNECT_BACKOFF,
    CONF_REGION,
    CONF_UPDATE_INTERVAL,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_KEEP_WARM,
    DEFAULT_NO_FRAME_TIMEOUT,
    DEFAULT_RECONNECT_BACKOFF,
    DEFAULT_UPDATE_INTERVAL,
    MODE_EMBEDDED,
    PLATFORMS,
)
from .coordinator import OwletCamCoordinator
from .data import OwletCamConfigEntry, OwletCamRuntimeData
from .runtime.manager import OwletRuntimeManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OwletCamConfigEntry,
) -> bool:
    """Set up Owlet Cam from a config entry."""
    client = None
    cameras: dict[str, OwletCameraData] = {}
    runtime_manager = None
    if entry.data.get(CONF_MODE) == MODE_EMBEDDED:
        dsn = entry.data[CONF_CAMERA_DSN]
        client = OwletCloudClient(
            async_get_clientsession(hass),
            email=entry.data[CONF_EMAIL],
            password=entry.data[CONF_PASSWORD],
            region=entry.data[CONF_REGION],
        )
        coordinator = OwletCamCoordinator(
            hass,
            client=client,
            camera_dsn=dsn,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
        )
        await coordinator.async_config_entry_first_refresh()
        cameras[dsn] = OwletCameraData(
            camera_id=dsn,
            name=entry.data[CONF_CAMERA_NAME],
        )
        runtime_manager = OwletRuntimeManager(
            hass,
            root=Path(hass.config.path("custom_components", "owlet_cam", "userfiles")),
            client=client,
            camera_identifier=dsn,
            keep_warm=entry.options.get(CONF_KEEP_WARM, DEFAULT_KEEP_WARM),
            idle_disconnect_timeout=entry.options.get(
                CONF_IDLE_TIMEOUT, DEFAULT_IDLE_TIMEOUT
            ),
            no_frame_timeout=entry.options.get(
                CONF_NO_FRAME_TIMEOUT, DEFAULT_NO_FRAME_TIMEOUT
            ),
            reconnect_backoff=entry.options.get(
                CONF_RECONNECT_BACKOFF, DEFAULT_RECONNECT_BACKOFF
            ),
        )
    else:
        coordinator = OwletCamCoordinator(hass)

    entry.runtime_data = OwletCamRuntimeData(
        client=client,
        coordinator=coordinator,
        runtime_manager=runtime_manager,
        cameras=cameras,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if runtime_manager is not None:
        runtime_manager.async_schedule_previous_validation_restore()
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: OwletCamConfigEntry,
) -> bool:
    """Unload Owlet Cam and all forwarded platforms."""
    runtime_manager = entry.runtime_data.runtime_manager
    registry = er.async_get(hass)
    entity_ids = [
        registry_entry.entity_id
        for registry_entry in er.async_entries_for_config_entry(
            registry, entry.entry_id
        )
    ]
    unloaded = bool(await hass.config_entries.async_unload_platforms(entry, PLATFORMS))
    if unloaded:
        if runtime_manager is not None:
            await runtime_manager.async_shutdown()
        # Current Home Assistant may restore an unavailable state for a
        # registry entity after platform unload. The milestone contract is
        # stricter: an unloaded Owlet Cam entry owns no state-machine entities.
        for entity_id in entity_ids:
            hass.states.async_remove(entity_id)
    return unloaded
