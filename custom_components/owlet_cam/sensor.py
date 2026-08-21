"""Sensor entities for Owlet Cam."""

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import STATUS_READY
from .data import OwletCamConfigEntry

STATUS_DESCRIPTION = SensorEntityDescription(
    key="integration_status",
    translation_key="integration_status",
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    _hass: object,
    entry: OwletCamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the milestone-zero diagnostic sensor."""
    async_add_entities([OwletCamIntegrationStatusSensor(entry)])


class OwletCamIntegrationStatusSensor(SensorEntity):
    """Report integration lifecycle readiness."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    entity_description = STATUS_DESCRIPTION

    def __init__(self, entry: OwletCamConfigEntry) -> None:
        """Initialize the sensor from already-loaded runtime data."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_integration_status"
        self._attr_name = "Owlet Cam Integration Status"

    @property
    def native_value(self) -> str:
        """Return coordinator-cached state without I/O."""
        return str(
            self._entry.runtime_data.coordinator.data.get("status", STATUS_READY)
        )

    @property
    def available(self) -> bool:
        """Return coordinator availability without I/O."""
        return bool(self._entry.runtime_data.coordinator.last_update_success)
