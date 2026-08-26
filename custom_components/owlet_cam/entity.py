"""Shared Owlet Cam entity foundations."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OwletCamCoordinator
from .runtime.manager import OwletRuntimeManager


class OwletCamCloudEntity(CoordinatorEntity[OwletCamCoordinator]):
    """Base for cached embedded cloud diagnostic entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OwletCamCoordinator,
        *,
        camera_dsn: str,
        camera_name: str,
        key: str,
    ) -> None:
        """Initialize a non-I/O entity from coordinator state."""
        super().__init__(coordinator)
        self._camera_dsn = camera_dsn
        self._attr_unique_id = f"{camera_dsn}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, camera_dsn)},
            name=camera_name,
            manufacturer="Owlet",
            model="Owlet Cam",
        )


class OwletCamBridgeEntity(CoordinatorEntity[OwletCamCoordinator]):
    """Base for external bridge entities backed only by coordinator data."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OwletCamCoordinator,
        *,
        camera_id: str,
        camera_name: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._camera_id = camera_id
        self._attr_unique_id = f"bridge_{camera_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"bridge_{camera_id}")},
            name=camera_name,
            manufacturer="Owlet",
            model="Owlet Cam via external bridge",
        )


class OwletCamRuntimeEntity(Entity):
    """Base for entities backed only by cached runtime-manager state."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        manager: OwletRuntimeManager,
        *,
        camera_identifier: str,
        camera_name: str,
        key: str,
    ) -> None:
        self.runtime_manager = manager
        self._attr_unique_id = f"{camera_identifier}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, camera_identifier)},
            name=camera_name,
            manufacturer="Owlet",
            model="Owlet Cam",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to in-memory runtime state changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.runtime_manager.async_add_listener(self.async_write_ha_state)
        )
