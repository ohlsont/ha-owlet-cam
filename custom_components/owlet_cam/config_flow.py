"""UI configuration flows for Owlet Cam."""

from __future__ import annotations

import os
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.cloud import OwletCloudClient, normalize_camera_dsn
from .api.exceptions import (
    OwletAuthenticationError,
    OwletCameraNotFoundError,
    OwletConnectionError,
    OwletInvalidDSNError,
    OwletRateLimitError,
    OwletUnsupportedRegionError,
)
from .const import (
    CONF_CAMERA_DSN,
    CONF_CAMERA_NAME,
    CONF_DEBUG_LOGGING,
    CONF_EMAIL,
    CONF_ENABLE_AUDIO,
    CONF_EXPERIMENTAL_LOCAL_SENSORS,
    CONF_IDLE_TIMEOUT,
    CONF_KEEP_WARM,
    CONF_MODE,
    CONF_NO_FRAME_TIMEOUT,
    CONF_PASSWORD,
    CONF_PREFER_DIRECT_P2P,
    CONF_RECONNECT_BACKOFF,
    CONF_REGION,
    CONF_RUNTIME_CHANNEL,
    CONF_STREAM_QUALITY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_DEBUG_LOGGING,
    DEFAULT_ENABLE_AUDIO,
    DEFAULT_EXPERIMENTAL_LOCAL_SENSORS,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_KEEP_WARM,
    DEFAULT_NO_FRAME_TIMEOUT,
    DEFAULT_PREFER_DIRECT_P2P,
    DEFAULT_RECONNECT_BACKOFF,
    DEFAULT_RUNTIME_CHANNEL,
    DEFAULT_STREAM_QUALITY,
    DEFAULT_UPDATE_INTERVAL,
    DEV_MODE_ENV,
    DOMAIN,
    MODE_DEVELOPMENT,
    MODE_EMBEDDED,
    MODE_EXTERNAL,
    REGION_EUROPE,
    REGIONS,
)

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OwletCamConfigFlow(  # type: ignore[call-arg]
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle an Owlet Cam config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OwletCamOptionsFlow:
        """Return the options flow for an entry."""
        return OwletCamOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Start with a connection-mode selector."""
        if user_input is not None:
            mode = user_input[CONF_MODE]
            if mode == MODE_DEVELOPMENT:
                if os.environ.get(DEV_MODE_ENV) != "1":
                    return self.async_abort(reason="development_disabled")
                await self.async_set_unique_id(MODE_DEVELOPMENT)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Owlet Cam Development",
                    data={CONF_MODE: MODE_DEVELOPMENT},
                )
            if mode == MODE_EXTERNAL:
                return self.async_abort(reason="external_not_available")
            return await self.async_step_embedded()

        modes = [MODE_EXTERNAL, MODE_EMBEDDED]
        if os.environ.get(DEV_MODE_ENV) == "1":
            modes.append(MODE_DEVELOPMENT)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_MODE, default=MODE_EXTERNAL): _select(modes, "mode")}
            ),
        )

    async def async_step_embedded(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Validate Owlet cloud authentication and camera KMS metadata."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, error = await self._async_validate_embedded(user_input)
            if error is None:
                dsn = data[CONF_CAMERA_DSN]
                await self.async_set_unique_id(dsn)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=data[CONF_CAMERA_NAME],
                    data={CONF_MODE: MODE_EMBEDDED, **data},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="embedded",
            data_schema=_embedded_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self,
        _entry_data: dict[str, Any],
    ) -> FlowResult:
        """Start reauthentication for an invalidated Owlet account."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Validate replacement account credentials and reload once."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {
                **entry.data,
                CONF_EMAIL: user_input[CONF_EMAIL],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_REGION: user_input[CONF_REGION],
            }
            data, error = await self._async_validate_embedded(candidate)
            if error is None:
                await self.async_set_unique_id(data[CONF_CAMERA_DSN])
                self._abort_if_unique_id_mismatch(reason="wrong_camera")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_EMAIL: data[CONF_EMAIL],
                        CONF_PASSWORD: data[CONF_PASSWORD],
                        CONF_REGION: data[CONF_REGION],
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=entry.data[CONF_EMAIL]): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_REGION, default=entry.data[CONF_REGION]): _select(
                        REGIONS, "region"
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Revalidate required camera configuration and reload once."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, error = await self._async_validate_embedded(user_input)
            if error is None:
                await self.async_set_unique_id(data[CONF_CAMERA_DSN])
                self._abort_if_unique_id_mismatch(reason="wrong_camera")
                return self.async_update_reload_and_abort(
                    entry,
                    title=data[CONF_CAMERA_NAME],
                    data_updates=data,
                )
            errors["base"] = error

        defaults = dict(entry.data)
        defaults.pop(CONF_PASSWORD, None)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_embedded_schema(user_input or defaults),
            errors=errors,
        )

    async def _async_validate_embedded(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Return normalized entry data and a translation error key."""
        try:
            email = _validate_email(str(user_input[CONF_EMAIL]))
            password = str(user_input[CONF_PASSWORD])
            if not password:
                return {}, "invalid_auth"
            dsn = normalize_camera_dsn(str(user_input[CONF_CAMERA_DSN]))
            name = str(user_input[CONF_CAMERA_NAME]).strip()
            if not name:
                return {}, "invalid_name"
            region = str(user_input[CONF_REGION])
            client = OwletCloudClient(
                async_get_clientsession(self.hass),
                email=email,
                password=password,
                region=region,
            )
            await client.async_validate_configured_camera(dsn)
        except vol.Invalid:
            return {}, "invalid_email"
        except OwletInvalidDSNError as err:
            return {}, "invalid_dsn_zero" if err.confused_zero else "invalid_dsn"
        except OwletAuthenticationError:
            return {}, "invalid_auth"
        except OwletCameraNotFoundError:
            return {}, "camera_not_found"
        except OwletRateLimitError:
            return {}, "rate_limited"
        except OwletUnsupportedRegionError:
            return {}, "unsupported_region"
        except OwletConnectionError:
            return {}, "cannot_connect"

        return {
            CONF_EMAIL: email,
            CONF_PASSWORD: password,
            CONF_REGION: region,
            CONF_CAMERA_DSN: dsn,
            CONF_CAMERA_NAME: name,
        }, None


class OwletCamOptionsFlow(config_entries.OptionsFlow):
    """Edit optional behavior in explicit general and embedded groups."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry
        self._pending: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start with general options."""
        return await self.async_step_general(user_input)

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure general camera behavior."""
        if user_input is not None:
            self._pending.update(user_input)
            if self._config_entry.data.get(CONF_MODE) == MODE_EMBEDDED:
                return await self.async_step_embedded()
            return self._finish()

        options = self._config_entry.options
        return self.async_show_form(
            step_id="general",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                    vol.Required(
                        CONF_KEEP_WARM,
                        default=options.get(CONF_KEEP_WARM, DEFAULT_KEEP_WARM),
                    ): bool,
                    vol.Required(
                        CONF_IDLE_TIMEOUT,
                        default=options.get(CONF_IDLE_TIMEOUT, DEFAULT_IDLE_TIMEOUT),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                    vol.Required(
                        CONF_STREAM_QUALITY,
                        default=options.get(
                            CONF_STREAM_QUALITY, DEFAULT_STREAM_QUALITY
                        ),
                    ): _select(("low", "medium", "high"), "stream_quality"),
                    vol.Required(
                        CONF_ENABLE_AUDIO,
                        default=options.get(CONF_ENABLE_AUDIO, DEFAULT_ENABLE_AUDIO),
                    ): bool,
                    vol.Required(
                        CONF_DEBUG_LOGGING,
                        default=options.get(CONF_DEBUG_LOGGING, DEFAULT_DEBUG_LOGGING),
                    ): bool,
                }
            ),
        )

    async def async_step_embedded(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure embedded experimental behavior."""
        if user_input is not None:
            self._pending.update(user_input)
            return self._finish()

        options = self._config_entry.options
        return self.async_show_form(
            step_id="embedded",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RUNTIME_CHANNEL,
                        default=options.get(
                            CONF_RUNTIME_CHANNEL, DEFAULT_RUNTIME_CHANNEL
                        ),
                    ): _select(("stable", "beta"), "runtime_channel"),
                    vol.Required(
                        CONF_RECONNECT_BACKOFF,
                        default=options.get(
                            CONF_RECONNECT_BACKOFF, DEFAULT_RECONNECT_BACKOFF
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
                    vol.Required(
                        CONF_NO_FRAME_TIMEOUT,
                        default=options.get(
                            CONF_NO_FRAME_TIMEOUT, DEFAULT_NO_FRAME_TIMEOUT
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
                    vol.Required(
                        CONF_PREFER_DIRECT_P2P,
                        default=options.get(
                            CONF_PREFER_DIRECT_P2P, DEFAULT_PREFER_DIRECT_P2P
                        ),
                    ): bool,
                    vol.Required(
                        CONF_EXPERIMENTAL_LOCAL_SENSORS,
                        default=options.get(
                            CONF_EXPERIMENTAL_LOCAL_SENSORS,
                            DEFAULT_EXPERIMENTAL_LOCAL_SENSORS,
                        ),
                    ): bool,
                }
            ),
        )

    def _finish(self) -> FlowResult:
        """Persist options and schedule exactly one entry reload."""
        self.hass.config_entries.async_schedule_reload(self._config_entry.entry_id)
        return self.async_create_entry(
            data={**self._config_entry.options, **self._pending}
        )


def _validate_email(value: str) -> str:
    normalized = value.strip()
    if not _EMAIL_PATTERN.fullmatch(normalized):
        raise vol.Invalid("invalid email")
    return normalized


def _embedded_schema(defaults: dict[str, Any] | None) -> vol.Schema:
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_EMAIL, default=values.get(CONF_EMAIL, "")): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(
                CONF_REGION, default=values.get(CONF_REGION, REGION_EUROPE)
            ): _select(REGIONS, "region"),
            vol.Required(CONF_CAMERA_DSN, default=values.get(CONF_CAMERA_DSN, "")): str,
            vol.Required(
                CONF_CAMERA_NAME, default=values.get(CONF_CAMERA_NAME, "Owlet Cam")
            ): str,
        }
    )


def _select(options: tuple[str, ...] | list[str], translation_key: str) -> Any:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(options),
            translation_key=translation_key,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )
