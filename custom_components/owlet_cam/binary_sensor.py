"""Binary sensor entities for Owlet Cam."""

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CAMERA_DSN, CONF_CAMERA_NAME, CONF_MODE, MODE_EMBEDDED
from .data import OwletCamConfigEntry
from .entity import OwletCamCloudEntity

_DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="cloud_reachable",
        translation_key="cloud_reachable",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="credentials_available",
        translation_key="camera_credentials_available",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    _hass: object,
    entry: OwletCamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up embedded cloud diagnostic binary sensors."""
    if entry.data.get(CONF_MODE) != MODE_EMBEDDED:
        return
    async_add_entities(
        [
            OwletCamCloudBinarySensor(
                entry,
                description=description,
                camera_dsn=entry.data[CONF_CAMERA_DSN],
                camera_name=entry.data[CONF_CAMERA_NAME],
            )
            for description in _DESCRIPTIONS
        ]
    )


class OwletCamCloudBinarySensor(OwletCamCloudEntity, BinarySensorEntity):
    """Represent one coordinator-cached cloud status boolean."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        entry: OwletCamConfigEntry,
        *,
        description: BinarySensorEntityDescription,
        camera_dsn: str,
        camera_name: str,
    ) -> None:
        """Initialize a cloud diagnostic binary sensor."""
        self.entity_description = description
        super().__init__(
            entry.runtime_data.coordinator,
            camera_dsn=camera_dsn,
            camera_name=camera_name,
            key=description.key,
        )

    @property
    def is_on(self) -> bool | None:
        """Return cached status without performing I/O."""
        value = self.coordinator.data.get(self.entity_description.key)
        return value if isinstance(value, bool) else None
