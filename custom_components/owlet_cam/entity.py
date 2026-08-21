"""Shared Owlet Cam entity foundations."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OwletCamCoordinator


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
