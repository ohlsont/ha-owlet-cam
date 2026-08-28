"""Update coordinator for Owlet Cam."""

import logging
from datetime import timedelta
from typing import Any, cast

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.bridge import OwletBridgeClient
from .api.cloud import OwletCloudClient
from .api.exceptions import (
    OwletAuthenticationError,
    OwletBridgeAuthenticationError,
    OwletBridgeCompatibilityError,
    OwletBridgeConnectionError,
    OwletCameraNotFoundError,
    OwletConnectionError,
    OwletRateLimitError,
)
from .const import DEFAULT_COORDINATOR_INTERVAL, DOMAIN, STATUS_READY

_LOGGER = logging.getLogger(__name__)


class OwletCamCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate updates without doing I/O in entity properties."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        client: OwletCloudClient | None = None,
        camera_dsn: str | None = None,
        bridge_client: OwletBridgeClient | None = None,
        bridge_camera_id: str | None = None,
        update_interval: timedelta = DEFAULT_COORDINATOR_INTERVAL,
    ) -> None:
        """Initialize a cloud or bridge coordinator."""
        cloud_configured = client is not None and camera_dsn is not None
        bridge_configured = bridge_client is not None and bridge_camera_id is not None
        if cloud_configured == bridge_configured:
            raise ValueError("Configure exactly one Owlet coordinator transport")
        self._client = client
        self._camera_dsn = camera_dsn
        self._bridge_client = bridge_client
        self._bridge_camera_id = bridge_camera_id
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            always_update=False,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh safe cloud and KMS status data."""
        if self._bridge_client is not None:
            bridge_camera_id = cast(str, self._bridge_camera_id)
            try:
                status = await self._bridge_client.async_get_status(bridge_camera_id)
                sensors = await self._bridge_client.async_get_sensors(bridge_camera_id)
            except OwletBridgeAuthenticationError as err:
                raise ConfigEntryAuthFailed(
                    "Owlet bridge authentication failed"
                ) from err
            except (
                OwletBridgeCompatibilityError,
                OwletBridgeConnectionError,
            ) as err:
                raise UpdateFailed("Owlet bridge is temporarily unavailable") from err
            return {
                "status": STATUS_READY,
                "bridge_online": True,
                "camera_online": status.online,
                "stream_healthy": status.stream_healthy,
                "stream_fps": status.stream_fps,
                "reconnect_count": status.reconnect_count,
                "temperature": sensors.temperature,
                "humidity": sensors.humidity,
                "sound_level": sensors.sound_level,
                "illuminance": sensors.illuminance,
                "wifi_signal": sensors.wifi_signal,
            }
        client = cast(OwletCloudClient, self._client)
        camera_dsn = cast(str, self._camera_dsn)
        try:
            metadata = await client.async_validate_configured_camera(camera_dsn)
        except OwletAuthenticationError as err:
            raise ConfigEntryAuthFailed("Owlet account authentication failed") from err
        except OwletRateLimitError as err:
            raise UpdateFailed("Owlet cloud rate limit reached") from err
        except OwletCameraNotFoundError as err:
            raise UpdateFailed("Owlet camera metadata is unavailable") from err
        except OwletConnectionError as err:
            raise UpdateFailed("Owlet cloud is temporarily unavailable") from err

        return {
            "status": STATUS_READY,
            "cloud_reachable": True,
            "credentials_available": metadata.credentials_available,
            "authentication_expiry": metadata.token_expiry,
        }
