"""Update coordinator for Owlet Cam."""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.cloud import OwletCloudClient
from .api.exceptions import (
    OwletAuthenticationError,
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
        update_interval: timedelta = DEFAULT_COORDINATOR_INTERVAL,
    ) -> None:
        """Initialize a development or cloud coordinator."""
        self._client = client
        self._camera_dsn = camera_dsn
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=update_interval if client is not None else None,
            always_update=False,
        )
        if client is None:
            self.async_set_updated_data({"status": STATUS_READY})

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh safe cloud and KMS status data."""
        if self._client is None or self._camera_dsn is None:
            return {"status": STATUS_READY}
        try:
            metadata = await self._client.async_validate_configured_camera(
                self._camera_dsn
            )
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
