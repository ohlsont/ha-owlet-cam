"""Binary sensor entities for Owlet Cam."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_BRIDGE_CAMERA_ID,
    CONF_CAMERA_DSN,
    CONF_CAMERA_NAME,
    CONF_MODE,
    MODE_EMBEDDED,
    MODE_EXTERNAL,
)
from .data import OwletCamConfigEntry
from .entity import OwletCamBridgeEntity, OwletCamCloudEntity, OwletCamRuntimeEntity

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

_RUNTIME_DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="native_libraries_compatible",
        translation_key="native_libraries_compatible",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="video_frames_received",
        translation_key="video_frames_received",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

_BRIDGE_DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="camera_online",
        translation_key="camera_online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    BinarySensorEntityDescription(
        key="stream_healthy",
        translation_key="stream_healthy",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="bridge_online",
        translation_key="bridge_online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
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
        if entry.data.get(CONF_MODE) == MODE_EXTERNAL:
            async_add_entities(
                OwletCamBridgeBinarySensor(entry, description=description)
                for description in _BRIDGE_DESCRIPTIONS
            )
        return
    entities: list[BinarySensorEntity] = [
        OwletCamCloudBinarySensor(
            entry,
            description=description,
            camera_dsn=entry.data[CONF_CAMERA_DSN],
            camera_name=entry.data[CONF_CAMERA_NAME],
        )
        for description in _DESCRIPTIONS
    ]
    if entry.runtime_data.runtime_manager is not None:
        entities.extend(
            OwletCamRuntimeBinarySensor(entry, description=description)
            for description in _RUNTIME_DESCRIPTIONS
        )
    async_add_entities(entities)


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


class OwletCamBridgeBinarySensor(OwletCamBridgeEntity, BinarySensorEntity):
    """Expose one coordinated bridge health boolean."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        entry: OwletCamConfigEntry,
        *,
        description: BinarySensorEntityDescription,
    ) -> None:
        self.entity_description = description
        camera_id = entry.data[CONF_BRIDGE_CAMERA_ID]
        camera = entry.runtime_data.cameras[camera_id]
        super().__init__(
            entry.runtime_data.coordinator,
            camera_id=camera_id,
            camera_name=camera.name,
            key=description.key,
        )

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get(self.entity_description.key)
        return value if isinstance(value, bool) else None


class OwletCamRuntimeBinarySensor(OwletCamRuntimeEntity, BinarySensorEntity):
    """Expose a cached native gate result without entity-property I/O."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        entry: OwletCamConfigEntry,
        *,
        description: BinarySensorEntityDescription,
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
    def is_on(self) -> bool | None:
        """Return only manager-cached compatibility or frame state."""
        snapshot = self.runtime_manager.snapshot
        if self.entity_description.key == "native_libraries_compatible":
            return snapshot.libraries_compatible
        probe = snapshot.last_frame_probe
        if probe is None:
            return None
        return probe.frames >= 100 and probe.sps > 0 and probe.pps > 0 and probe.idr > 0
