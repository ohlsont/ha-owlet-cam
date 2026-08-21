"""UI configuration flow for Owlet Cam."""

import os
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_MODE, DEV_MODE_ENV, DOMAIN, MODE_DEVELOPMENT


class OwletCamConfigFlow(  # type: ignore[call-arg]
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle an Owlet Cam config flow."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Create the temporary development-only entry."""
        if os.environ.get(DEV_MODE_ENV) != "1":
            return self.async_abort(reason="development_disabled")

        if user_input is not None:
            await self.async_set_unique_id(MODE_DEVELOPMENT)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Owlet Cam Development",
                data={CONF_MODE: MODE_DEVELOPMENT},
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_MODE, default=MODE_DEVELOPMENT): vol.In(
                    [MODE_DEVELOPMENT]
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
