"""Tests for the development-only config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.owlet_cam.const import (
    CONF_MODE,
    DEV_MODE_ENV,
    DOMAIN,
    MODE_DEVELOPMENT,
)


async def test_flow_hidden_without_environment_switch(hass: HomeAssistant) -> None:
    """Ordinary config flows must not expose the temporary mode."""
    with patch.dict("os.environ", {}, clear=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "development_disabled"


async def test_flow_create_and_reject_duplicate(hass: HomeAssistant) -> None:
    """The development switch creates exactly one config entry."""
    with patch.dict("os.environ", {DEV_MODE_ENV: "1"}, clear=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_MODE: MODE_DEVELOPMENT},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_MODE: MODE_DEVELOPMENT},
        )

    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
