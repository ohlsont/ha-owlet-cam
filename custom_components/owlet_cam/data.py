"""Typed runtime data for Owlet Cam config entries."""

from collections.abc import Callable
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry

from .api.bridge import OwletBridgeClient
from .api.cloud import OwletCloudClient
from .api.models import OwletCameraData
from .coordinator import OwletCamCoordinator
from .runtime.manager import OwletRuntimeManager


@dataclass(slots=True)
class OwletCamRuntimeData:
    """Runtime objects owned by one config entry."""

    client: OwletCloudClient | OwletBridgeClient | None
    coordinator: OwletCamCoordinator
    runtime_manager: OwletRuntimeManager | None
    cameras: dict[str, OwletCameraData] = field(default_factory=dict)
    remove_runtime_issue_listener: Callable[[], None] | None = None


type OwletCamConfigEntry = ConfigEntry[OwletCamRuntimeData]
