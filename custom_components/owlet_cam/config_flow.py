"""UI configuration flows for Owlet Cam."""

from __future__ import annotations

import os
import re
from hashlib import sha256
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.bridge import OwletHttpBridgeClient, normalize_bridge_url
from .api.cloud import OwletCloudClient, normalize_camera_dsn
from .api.exceptions import (
    OwletAuthenticationError,
    OwletBridgeAuthenticationError,
    OwletBridgeCompatibilityError,
    OwletBridgeConnectionError,
    OwletCameraNotFoundError,
    OwletConnectionError,
    OwletInvalidDSNError,
    OwletRateLimitError,
    OwletUnsupportedRegionError,
)
from .api.models import BridgeCamera
from .const import (
    CONF_BRIDGE_CAMERA_ID,
    CONF_BRIDGE_PASSWORD,
    CONF_BRIDGE_TIMEOUT,
    CONF_BRIDGE_URL,
    CONF_BRIDGE_USERNAME,
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
    CONF_RETAIN_APPLICATION,
    CONF_RTSP_OVERRIDE,
    CONF_RUNTIME_CHANNEL,
    CONF_STREAM_QUALITY,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_TLS,
    DEFAULT_BRIDGE_TIMEOUT,
    DEFAULT_DEBUG_LOGGING,
    DEFAULT_ENABLE_AUDIO,
    DEFAULT_EXPERIMENTAL_LOCAL_SENSORS,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_KEEP_WARM,
    DEFAULT_NO_FRAME_TIMEOUT,
    DEFAULT_PREFER_DIRECT_P2P,
    DEFAULT_RECONNECT_BACKOFF,
    DEFAULT_RETAIN_APPLICATION,
    DEFAULT_RUNTIME_CHANNEL,
    DEFAULT_STREAM_QUALITY,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VERIFY_TLS,
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
    _external_data: dict[str, Any] | None = None
    _external_cameras: list[BridgeCamera] | None = None

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
                return await self.async_step_external()
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

    async def async_step_external(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Validate a bridge and enumerate its cameras."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, cameras, error = await self._async_validate_external(user_input)
            if error is None:
                self._external_data = data
                self._external_cameras = cameras
                if len(cameras) == 1:
                    return await self._async_create_external_entry(cameras[0])
                return await self.async_step_external_camera()
            errors["base"] = error
        return self.async_show_form(
            step_id="external",
            data_schema=_external_schema(user_input),
            errors=errors,
        )

    async def async_step_external_camera(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Select exactly one camera when the bridge exposes several."""
        if self._external_data is None or not self._external_cameras:
            return self.async_abort(reason="cannot_connect")
        choices = {camera.camera_id: camera.name for camera in self._external_cameras}
        if user_input is not None:
            selected = str(user_input[CONF_BRIDGE_CAMERA_ID])
            camera = next(
                camera
                for camera in self._external_cameras
                if camera.camera_id == selected
            )
            return await self._async_create_external_entry(camera)
        return self.async_show_form(
            step_id="external_camera",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BRIDGE_CAMERA_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=value, label=label)
                                for value, label in choices.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def _async_create_external_entry(self, camera: BridgeCamera) -> FlowResult:
        """Create one stable per-camera bridge entry."""
        if self._external_data is None:
            return self.async_abort(reason="cannot_connect")
        identity = f"{self._external_data[CONF_BRIDGE_URL]}|{camera.camera_id}"
        await self.async_set_unique_id(
            f"bridge_{sha256(identity.encode()).hexdigest()}"
        )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=camera.name,
            data={
                CONF_MODE: MODE_EXTERNAL,
                **self._external_data,
                CONF_BRIDGE_CAMERA_ID: camera.camera_id,
                CONF_CAMERA_NAME: camera.name,
            },
        )

    async def _async_validate_external(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any], list[BridgeCamera], str | None]:
        """Return safe normalized bridge data, cameras, and any form error."""
        try:
            base_url = normalize_bridge_url(str(user_input[CONF_BRIDGE_URL]))
            username = str(user_input.get(CONF_BRIDGE_USERNAME, "")).strip()
            password = str(user_input.get(CONF_BRIDGE_PASSWORD, ""))
            verify_tls = bool(user_input.get(CONF_VERIFY_TLS, DEFAULT_VERIFY_TLS))
            rtsp_override = str(user_input.get(CONF_RTSP_OVERRIDE, "")).strip()
            client = OwletHttpBridgeClient(
                async_get_clientsession(self.hass),
                base_url=base_url,
                username=username or None,
                password_or_token=password or None,
                verify_tls=verify_tls,
                rtsp_override=rtsp_override or None,
            )
            await client.async_validate()
            cameras = await client.async_get_cameras()
            if not cameras:
                return {}, [], "no_cameras"
            if any(camera.rtsp_url is None for camera in cameras):
                return {}, [], "no_stream"
        except ValueError:
            return {}, [], "invalid_bridge_url"
        except OwletBridgeAuthenticationError:
            return {}, [], "invalid_bridge_auth"
        except OwletBridgeCompatibilityError:
            return {}, [], "unsupported_bridge"
        except OwletBridgeConnectionError:
            return {}, [], "cannot_connect_bridge"
        return (
            {
                CONF_BRIDGE_URL: base_url,
                CONF_BRIDGE_USERNAME: username,
                CONF_BRIDGE_PASSWORD: password,
                CONF_VERIFY_TLS: verify_tls,
                CONF_RTSP_OVERRIDE: rtsp_override,
            },
            cameras,
            None,
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
        if entry.data.get(CONF_MODE) == MODE_EXTERNAL:
            return await self.async_step_reauth_bridge(user_input)
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

    async def async_step_reauth_bridge(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Validate replacement external bridge credentials and reload once."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {
                **entry.data,
                CONF_BRIDGE_USERNAME: user_input.get(CONF_BRIDGE_USERNAME, ""),
                CONF_BRIDGE_PASSWORD: user_input.get(CONF_BRIDGE_PASSWORD, ""),
            }
            data, cameras, error = await self._async_validate_external(candidate)
            if error is None and any(
                camera.camera_id == entry.data[CONF_BRIDGE_CAMERA_ID]
                for camera in cameras
            ):
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_BRIDGE_USERNAME: data[CONF_BRIDGE_USERNAME],
                        CONF_BRIDGE_PASSWORD: data[CONF_BRIDGE_PASSWORD],
                    },
                )
            errors["base"] = error or "camera_not_found"
        return self.async_show_form(
            step_id="reauth_bridge",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_BRIDGE_USERNAME,
                        default=entry.data.get(CONF_BRIDGE_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_BRIDGE_PASSWORD): str,
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
        if entry.data.get(CONF_MODE) == MODE_EXTERNAL:
            return await self.async_step_reconfigure_bridge(user_input)
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

    async def async_step_reconfigure_bridge(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Revalidate the existing camera against updated bridge settings."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {
                **entry.data,
                **user_input,
                CONF_BRIDGE_PASSWORD: user_input.get(
                    CONF_BRIDGE_PASSWORD, entry.data.get(CONF_BRIDGE_PASSWORD, "")
                ),
            }
            data, cameras, error = await self._async_validate_external(candidate)
            selected = next(
                (
                    camera
                    for camera in cameras
                    if camera.camera_id == entry.data[CONF_BRIDGE_CAMERA_ID]
                ),
                None,
            )
            if error is None and selected is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    title=selected.name,
                    data_updates={
                        **data,
                        CONF_CAMERA_NAME: selected.name,
                    },
                )
            errors["base"] = error or "camera_not_found"
        defaults = dict(entry.data)
        defaults.pop(CONF_BRIDGE_PASSWORD, None)
        return self.async_show_form(
            step_id="reconfigure_bridge",
            data_schema=_external_schema(user_input or defaults),
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
            if self._config_entry.data.get(CONF_MODE) == MODE_EXTERNAL:
                return await self.async_step_external()
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
                    vol.Required(
                        CONF_RETAIN_APPLICATION,
                        default=options.get(
                            CONF_RETAIN_APPLICATION, DEFAULT_RETAIN_APPLICATION
                        ),
                    ): bool,
                }
            ),
        )

    async def async_step_external(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure external bridge request and stream overrides."""
        if user_input is not None:
            self._pending.update(user_input)
            return self._finish()
        options = self._config_entry.options
        return self.async_show_form(
            step_id="external",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BRIDGE_TIMEOUT,
                        default=options.get(
                            CONF_BRIDGE_TIMEOUT, DEFAULT_BRIDGE_TIMEOUT
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
                    vol.Optional(
                        CONF_RTSP_OVERRIDE,
                        default=options.get(
                            CONF_RTSP_OVERRIDE,
                            self._config_entry.data.get(CONF_RTSP_OVERRIDE, ""),
                        ),
                    ): str,
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


def _external_schema(defaults: dict[str, Any] | None) -> vol.Schema:
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_BRIDGE_URL, default=values.get(CONF_BRIDGE_URL, "")): str,
            vol.Optional(
                CONF_BRIDGE_USERNAME,
                default=values.get(CONF_BRIDGE_USERNAME, ""),
            ): str,
            vol.Optional(CONF_BRIDGE_PASSWORD): str,
            vol.Optional(
                CONF_RTSP_OVERRIDE,
                default=values.get(CONF_RTSP_OVERRIDE, ""),
            ): str,
            vol.Required(
                CONF_VERIFY_TLS,
                default=values.get(CONF_VERIFY_TLS, DEFAULT_VERIFY_TLS),
            ): bool,
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
