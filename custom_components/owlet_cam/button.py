"""Diagnostic controls for the isolated Owlet native runtime."""

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CAMERA_DSN, CONF_CAMERA_NAME, CONF_MODE, MODE_EMBEDDED
from .data import OwletCamConfigEntry
from .entity import OwletCamRuntimeEntity
from .runtime.manager import OwletRuntimeError

_RUNTIME_PROBE = ButtonEntityDescription(
    key="run_runtime_probe",
    translation_key="run_runtime_probe",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)
_FRAME_PROBE = ButtonEntityDescription(
    key="run_frame_probe",
    translation_key="run_frame_probe",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    _hass: object,
    entry: OwletCamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up disabled-by-default experimental probe buttons."""
    manager = entry.runtime_data.runtime_manager
    if entry.data.get(CONF_MODE) != MODE_EMBEDDED or manager is None:
        return
    async_add_entities(
        [
            OwletCamRuntimeProbeButton(entry, description=_RUNTIME_PROBE),
            OwletCamRuntimeProbeButton(entry, description=_FRAME_PROBE),
        ]
    )


class OwletCamRuntimeProbeButton(OwletCamRuntimeEntity, ButtonEntity):
    """Run one explicitly requested bounded native capability probe."""

    entity_description: ButtonEntityDescription

    def __init__(
        self,
        entry: OwletCamConfigEntry,
        *,
        description: ButtonEntityDescription,
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
    def available(self) -> bool:
        """Enforce architecture and previous-gate requirements."""
        if self.entity_description.key == _FRAME_PROBE.key:
            return self.runtime_manager.frame_probe_available
        return self.runtime_manager.supported_architecture

    async def async_press(self) -> None:
        """Run the selected probe without blocking Home Assistant's event loop."""
        try:
            if self.entity_description.key == _FRAME_PROBE.key:
                await self.runtime_manager.async_run_frame_probe()
            else:
                await self.runtime_manager.async_prepare_and_probe_libraries()
        except OwletRuntimeError as err:
            raise HomeAssistantError(str(err)) from err
