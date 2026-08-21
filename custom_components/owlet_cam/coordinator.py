"""Update coordinator for Owlet Cam."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, STATUS_READY


class OwletCamCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate updates without doing I/O in entity properties."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the milestone-zero coordinator."""
        super().__init__(
            hass, logger=__import__("logging").getLogger(__name__), name=DOMAIN
        )
        self.async_set_updated_data({"status": STATUS_READY})
