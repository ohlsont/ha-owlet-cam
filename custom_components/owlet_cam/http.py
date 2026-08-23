"""Authenticated Home Assistant HTTP API for embedded runtime administration."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, cast

from aiohttp import web
from homeassistant.components.http import KEY_HASS, KEY_HASS_USER, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import CONF_MODE, DOMAIN, MODE_EMBEDDED
from .runtime.manager import OwletRuntimeError, OwletRuntimeManager
from .runtime.upload import MAXIMUM_UPLOAD_SIZE, OwletUploadError

_CHUNK_SIZE = 1024 * 1024
_CONFIRM_DELETE = "delete-proprietary-files"


class OwletRuntimeStatusView(HomeAssistantView):
    """Return cached, redacted status for loaded embedded entries."""

    url = "/api/owlet_cam/runtime"
    name = "api:owlet_cam:runtime"

    async def get(self, request: web.Request) -> web.Response:
        """Return only admin-safe runtime facts."""
        _require_admin(request)
        hass: HomeAssistant = request.app[KEY_HASS]
        entries: list[dict[str, Any]] = []
        for entry in hass.config_entries.async_entries(DOMAIN):
            if (
                entry.data.get(CONF_MODE) != MODE_EMBEDDED
                or entry.state is not ConfigEntryState.LOADED
            ):
                continue
            manager = entry.runtime_data.runtime_manager
            if manager is None:
                continue
            entries.append(
                {
                    "entry_id": entry.entry_id,
                    "title": entry.title,
                    "runtime": manager.diagnostics(),
                }
            )
        return cast(
            web.Response,
            self.json(
                {
                    "entries": entries,
                    "maximum_upload_size": MAXIMUM_UPLOAD_SIZE,
                    "supported_extensions": [".apk", ".apkm", ".xapk", ".zip"],
                },
            ),
        )


class OwletRuntimeApplicationView(HomeAssistantView):
    """Stream uploads and confirmation-gated proprietary deletion."""

    url = "/api/owlet_cam/runtime/{entry_id}/application"
    name = "api:owlet_cam:runtime:application"

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        """Store one bounded upload under a generated private filename."""
        _require_admin(request)
        manager = _manager(request, entry_id)
        suffix = request.headers.get("X-Owlet-Archive-Extension", "")
        try:
            stored = await manager.async_store_application_upload(
                request.content.iter_chunked(_CHUNK_SIZE),
                suffix=suffix,
                content_length=request.content_length,
            )
        except OwletUploadError as err:
            return cast(
                web.Response,
                self.json_message(
                    str(err), HTTPStatus.BAD_REQUEST, message_code=err.code
                ),
            )
        except OSError:
            return cast(
                web.Response,
                self.json_message(
                    "Application upload could not be stored",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    message_code="upload_storage_failed",
                ),
            )
        return cast(
            web.Response,
            self.json(
                {
                    "ok": True,
                    "size": stored.size,
                    "sha256": stored.sha256,
                    "runtime": manager.diagnostics(),
                },
                HTTPStatus.CREATED,
            ),
        )

    async def delete(self, request: web.Request, entry_id: str) -> web.Response:
        """Delete all user-supplied files only after explicit confirmation."""
        _require_admin(request)
        if request.headers.get("X-Owlet-Confirm-Delete") != _CONFIRM_DELETE:
            return cast(
                web.Response,
                self.json_message(
                    "Explicit deletion confirmation is required",
                    HTTPStatus.PRECONDITION_REQUIRED,
                    message_code="confirmation_required",
                ),
            )
        manager = _manager(request, entry_id)
        await manager.async_delete_proprietary_files()
        return cast(
            web.Response, self.json({"ok": True, "runtime": manager.diagnostics()})
        )


class OwletRuntimeActionView(HomeAssistantView):
    """Run bounded runtime actions selected in the authenticated panel."""

    url = "/api/owlet_cam/runtime/{entry_id}/action/{action}"
    name = "api:owlet_cam:runtime:action"

    async def post(
        self, request: web.Request, entry_id: str, action: str
    ) -> web.Response:
        """Run one allowlisted action and return redacted cached status."""
        _require_admin(request)
        manager = _manager(request, entry_id)
        try:
            if action == "authentication-test":
                await manager.async_run_authentication_test()
            elif action == "runtime-probe":
                await manager.async_prepare_and_probe_libraries()
            elif action == "frame-probe":
                await manager.async_run_frame_probe()
            elif action == "stream-probe":
                await manager.async_run_stream_probe()
            elif action == "restart-stream":
                await manager.async_restart_stream()
            else:
                return cast(
                    web.Response,
                    self.json_message(
                        "Unknown runtime action",
                        HTTPStatus.NOT_FOUND,
                        message_code="unknown_action",
                    ),
                )
        except OwletRuntimeError as err:
            return cast(
                web.Response,
                self.json_message(str(err), HTTPStatus.CONFLICT, message_code=err.code),
            )
        return cast(
            web.Response, self.json({"ok": True, "runtime": manager.diagnostics()})
        )


def _require_admin(request: web.Request) -> None:
    user = request.get(KEY_HASS_USER)
    if user is None or not user.is_admin:
        raise web.HTTPForbidden(text="Administrator access is required")


def _manager(request: web.Request, entry_id: str) -> OwletRuntimeManager:
    hass: HomeAssistant = request.app[KEY_HASS]
    entry = hass.config_entries.async_get_entry(entry_id)
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.data.get(CONF_MODE) != MODE_EMBEDDED
        or entry.state is not ConfigEntryState.LOADED
    ):
        raise web.HTTPNotFound(text="Embedded Owlet Cam entry is unavailable")
    manager = cast(OwletRuntimeManager | None, entry.runtime_data.runtime_manager)
    if manager is None:
        raise web.HTTPNotFound(text="Embedded Owlet Cam runtime is unavailable")
    return manager
