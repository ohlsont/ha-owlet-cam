"""Sensor entities for Owlet Cam."""

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CAMERA_DSN,
    CONF_CAMERA_NAME,
    CONF_MODE,
    MODE_EMBEDDED,
    STATUS_READY,
)
from .data import OwletCamConfigEntry
from .entity import OwletCamCloudEntity, OwletCamRuntimeEntity

STATUS_DESCRIPTION = SensorEntityDescription(
    key="integration_status",
    translation_key="integration_status",
    entity_category=EntityCategory.DIAGNOSTIC,
)

AUTHENTICATION_EXPIRY_DESCRIPTION = SensorEntityDescription(
    key="authentication_expiry",
    translation_key="authentication_expiry",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
)

_RUNTIME_DESCRIPTIONS = (
    SensorEntityDescription(
        key="runtime_status",
        translation_key="runtime_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="helper_version",
        translation_key="helper_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="detected_apk_version",
        translation_key="detected_apk_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="last_frame_probe",
        translation_key="last_frame_probe",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="detected_resolution",
        translation_key="detected_resolution",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="detected_fps",
        translation_key="detected_fps",
        native_unit_of_measurement="fps",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    _hass: object,
    entry: OwletCamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up cached diagnostic sensors."""
    if entry.data.get(CONF_MODE) == MODE_EMBEDDED:
        entities: list[SensorEntity] = [
            OwletCamAuthenticationExpirySensor(
                entry,
                camera_dsn=entry.data[CONF_CAMERA_DSN],
                camera_name=entry.data[CONF_CAMERA_NAME],
            )
        ]
        if entry.runtime_data.runtime_manager is not None:
            entities.extend(
                OwletCamRuntimeSensor(entry, description=description)
                for description in _RUNTIME_DESCRIPTIONS
            )
        async_add_entities(entities)
        return
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


class OwletCamAuthenticationExpirySensor(OwletCamCloudEntity, SensorEntity):
    """Report the expiry of the in-memory Firebase authentication."""

    entity_description = AUTHENTICATION_EXPIRY_DESCRIPTION

    def __init__(
        self,
        entry: OwletCamConfigEntry,
        *,
        camera_dsn: str,
        camera_name: str,
    ) -> None:
        """Initialize the cached expiry sensor."""
        super().__init__(
            entry.runtime_data.coordinator,
            camera_dsn=camera_dsn,
            camera_name=camera_name,
            key=self.entity_description.key,
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the coordinator-cached token expiry."""
        value = self.coordinator.data.get("authentication_expiry")
        return value if isinstance(value, datetime) else None


class OwletCamRuntimeSensor(OwletCamRuntimeEntity, SensorEntity):
    """Expose one cached, non-secret runtime capability value."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        entry: OwletCamConfigEntry,
        *,
        description: SensorEntityDescription,
    ) -> None:
        self.entity_description = description
        manager = entry.runtime_data.runtime_manager
        if manager is None:
            raise RuntimeError("Embedded runtime manager is unavailable")
        super().__init__(
            manager,
            camera_identifier=entry.data[CONF_CAMERA_DSN],
            camera_name=entry.data[CONF_CAMERA_NAME],
            key=description.key,
        )

    @property
    def native_value(self) -> str | float | datetime | None:
        """Return only manager-cached state."""
        snapshot = self.runtime_manager.snapshot
        probe = snapshot.last_frame_probe
        match self.entity_description.key:
            case "runtime_status":
                return snapshot.status
            case "helper_version":
                return snapshot.helper_version
            case "detected_apk_version":
                return snapshot.detected_apk_version
            case "last_frame_probe":
                return snapshot.last_frame_probe_at
            case "detected_resolution":
                return f"{probe.width}x{probe.height}" if probe is not None else None
            case "detected_fps":
                return probe.estimated_fps if probe is not None else None
        return None
