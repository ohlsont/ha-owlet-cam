"""Sensor entities for Owlet Cam."""

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfDataRate,
    UnitOfSoundPressure,
    UnitOfTemperature,
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
    STATUS_READY,
)
from .data import OwletCamConfigEntry
from .entity import OwletCamBridgeEntity, OwletCamCloudEntity, OwletCamRuntimeEntity

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
        key="last_stream_probe",
        translation_key="last_stream_probe",
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
    SensorEntityDescription(
        key="stream_codec",
        translation_key="stream_codec",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="stream_profile",
        translation_key="stream_profile",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="stream_bitrate",
        translation_key="stream_bitrate",
        native_unit_of_measurement=UnitOfDataRate.KILOBITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="audio_status",
        translation_key="audio_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="audio_codec",
        translation_key="audio_codec",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

_BRIDGE_DESCRIPTIONS = (
    SensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="sound_level",
        translation_key="sound_level",
        device_class=SensorDeviceClass.SOUND_PRESSURE,
        native_unit_of_measurement=UnitOfSoundPressure.DECIBEL,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="illuminance",
        translation_key="illuminance",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="stream_fps",
        translation_key="stream_fps",
        native_unit_of_measurement="fps",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="reconnect_count",
        translation_key="reconnect_count",
        state_class=SensorStateClass.MEASUREMENT,
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
    if entry.data.get(CONF_MODE) == MODE_EXTERNAL:
        async_add_entities(
            OwletCamBridgeSensor(entry, description=description)
            for description in _BRIDGE_DESCRIPTIONS
        )
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


class OwletCamBridgeSensor(OwletCamBridgeEntity, SensorEntity):
    """Expose one value from the coordinated external bridge cycle."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        entry: OwletCamConfigEntry,
        *,
        description: SensorEntityDescription,
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
    def native_value(self) -> float | int | None:
        """Return only the coordinator-cached bridge value."""
        value = self.coordinator.data.get(self.entity_description.key)
        return (
            value
            if isinstance(value, int | float) and not isinstance(value, bool)
            else None
        )


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
        frame_probe = snapshot.last_frame_probe
        stream_probe = snapshot.last_stream_probe
        match self.entity_description.key:
            case "runtime_status":
                return snapshot.status
            case "helper_version":
                return snapshot.helper_version
            case "detected_apk_version":
                return snapshot.detected_apk_version
            case "last_frame_probe":
                return snapshot.last_frame_probe_at
            case "last_stream_probe":
                return snapshot.last_stream_probe_at
            case "detected_resolution":
                probe = stream_probe or frame_probe
                return f"{probe.width}x{probe.height}" if probe is not None else None
            case "detected_fps":
                if stream_probe is not None:
                    return stream_probe.fps
                return frame_probe.estimated_fps if frame_probe is not None else None
            case "stream_codec":
                return stream_probe.codec if stream_probe is not None else None
            case "stream_profile":
                return stream_probe.profile if stream_probe is not None else None
            case "stream_bitrate":
                return stream_probe.bitrate_kbps if stream_probe is not None else None
            case "audio_status":
                return snapshot.audio_status
            case "audio_codec":
                codec_id = snapshot.audio_codec_id
                if codec_id is None:
                    return None
                return {
                    0x86: "AAC-LC (raw)",
                    0x87: "AAC-LC (ADTS)",
                    0x88: "AAC-LATM",
                    0x89: "G.711 μ-law",
                    0x8A: "G.711 A-law",
                    0x8B: "ADPCM",
                    0x8C: "PCM",
                    0x8D: "Speex",
                    0x8E: "MP3",
                    0x8F: "G.726",
                }.get(codec_id)
        return None
