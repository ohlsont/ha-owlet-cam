"""Clean-room adapter for the observed Owlet-To-Rtsp HTTP API."""

from __future__ import annotations

import asyncio
import json
from base64 import b64encode
from collections.abc import Mapping
from typing import Any, Final, Protocol, TypeGuard, cast
from urllib.parse import quote, urlsplit, urlunsplit

from aiohttp import ClientError, ClientSession

from .exceptions import (
    OwletBridgeAuthenticationError,
    OwletBridgeCompatibilityError,
    OwletBridgeConnectionError,
)
from .models import BridgeCamera, BridgeInfo, CameraSensors, CameraStatus

MAX_BRIDGE_RESPONSE_SIZE: Final = 2 * 1024 * 1024
DEFAULT_BRIDGE_TIMEOUT: Final = 10.0


class OwletBridgeClient(Protocol):
    """External bridge behavior consumed by Home Assistant."""

    async def async_validate(self) -> BridgeInfo: ...

    async def async_get_cameras(self) -> list[BridgeCamera]: ...

    async def async_get_status(self, camera_id: str) -> CameraStatus: ...

    async def async_get_sensors(self, camera_id: str) -> CameraSensors: ...

    async def async_get_snapshot(self, camera_id: str) -> bytes | None: ...

    async def async_get_stream_source(self, camera_id: str) -> str | None: ...


class OwletHttpBridgeClient:
    """Parse only the current documented/observed bridge response fields."""

    def __init__(
        self,
        session: ClientSession,
        *,
        base_url: str,
        username: str | None = None,
        password_or_token: str | None = None,
        verify_tls: bool = True,
        request_timeout: float = DEFAULT_BRIDGE_TIMEOUT,
        rtsp_override: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = normalize_bridge_url(base_url)
        self._username = username or None
        self._password_or_token = password_or_token or None
        self._verify_tls = verify_tls
        self._request_timeout = max(1.0, request_timeout)
        self._rtsp_override = (
            normalize_rtsp_url(rtsp_override) if rtsp_override else None
        )
        self._cameras: dict[str, BridgeCamera] = {}

    async def async_validate(self) -> BridgeInfo:
        """Validate connectivity and the observed status contract."""
        payload = await self._async_json("/api/status")
        required = {
            "cameras",
            "cameras_with_key",
            "streams_live",
            "rtsp_port",
        }
        if not required.issubset(payload) or not all(
            _is_number(payload[key]) for key in required
        ):
            raise OwletBridgeCompatibilityError(
                "The service does not expose the supported Owlet bridge API"
            )
        return BridgeInfo(
            api_family="btoth525/owlet-to-rtsp",
            api_version=None,
            supports_snapshots=True,
            supports_sensors=True,
        )

    async def async_get_cameras(self) -> list[BridgeCamera]:
        """Enumerate cameras while deliberately ignoring credential fields."""
        payload = await self._async_json("/api/cameras")
        raw_cameras = payload.get("cameras")
        rtsp_port = payload.get("rtsp_port")
        if not isinstance(raw_cameras, list) or not _is_port(rtsp_port):
            raise OwletBridgeCompatibilityError(
                "The bridge camera response is incompatible"
            )
        rtsp_port_value = cast(int, rtsp_port)
        cameras: list[BridgeCamera] = []
        for raw in raw_cameras:
            if not isinstance(raw, Mapping):
                raise OwletBridgeCompatibilityError(
                    "The bridge camera response is incompatible"
                )
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                raise OwletBridgeCompatibilityError(
                    "The bridge camera response is incompatible"
                )
            camera_id = name.strip()
            codec = raw.get("codec")
            camera = BridgeCamera(
                camera_id=camera_id,
                name=camera_id,
                online=raw.get("have_key") is True,
                stream_healthy=raw.get("stream_up") is True,
                stream_codec=(codec if isinstance(codec, str) and codec else None),
                received_bytes=_optional_int(raw.get("recv")),
                rtsp_url=self._stream_url(camera_id, rtsp_port_value),
            )
            cameras.append(camera)
        self._cameras = {camera.camera_id: camera for camera in cameras}
        return cameras

    async def async_get_status(self, camera_id: str) -> CameraStatus:
        """Refresh camera status through the camera-list endpoint."""
        camera = await self._camera(camera_id, refresh=True)
        return CameraStatus(
            online=camera.online,
            stream_healthy=camera.stream_healthy,
        )

    async def async_get_sensors(self, camera_id: str) -> CameraSensors:
        """Read current metric room sensors when the optional endpoint exists."""
        content = await self._async_bytes(
            "/api/vitals?units=metric", allow_not_found=True
        )
        if content is None:
            return CameraSensors()
        try:
            payload: object = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return CameraSensors()
        if not isinstance(payload, dict):
            return CameraSensors()
        devices = payload.get("devices")
        if not isinstance(devices, list):
            return CameraSensors()
        for device in devices:
            if not isinstance(device, Mapping) or device.get("kind") != "cam":
                continue
            identifier = device.get("dsn") or device.get("name")
            sensor_values = device.get("sensors")
            if identifier != camera_id or not isinstance(sensor_values, Mapping):
                continue
            return CameraSensors(
                temperature=_optional_float(sensor_values.get("temperature")),
                humidity=_optional_float(sensor_values.get("humidity")),
                sound_level=_optional_float(
                    sensor_values.get("noise", sensor_values.get("sound"))
                ),
                illuminance=_optional_float(sensor_values.get("brightness")),
                wifi_signal=_optional_float(sensor_values.get("wifi_rssi")),
            )
        return CameraSensors()

    async def async_get_snapshot(self, camera_id: str) -> bytes | None:
        """Return a bounded JPEG snapshot from the observed camera route."""
        await self._camera(camera_id)
        path = f"/snapshot/{quote(camera_id, safe='')}.jpg"
        try:
            content = await self._async_bytes(path, allow_not_found=True)
        except OwletBridgeConnectionError:
            return None
        if (
            content is None
            or len(content) < 4
            or not content.startswith(b"\xff\xd8")
            or not content.endswith(b"\xff\xd9")
        ):
            return None
        return content

    async def async_get_stream_source(self, camera_id: str) -> str | None:
        """Return the cached or freshly enumerated RTSP source."""
        return (await self._camera(camera_id)).rtsp_url

    async def _camera(self, camera_id: str, *, refresh: bool = False) -> BridgeCamera:
        if refresh or camera_id not in self._cameras:
            await self.async_get_cameras()
        try:
            return self._cameras[camera_id]
        except KeyError as err:
            raise OwletBridgeCompatibilityError(
                "The selected bridge camera is no longer available"
            ) from err

    def _stream_url(self, camera_id: str, rtsp_port: int) -> str:
        if self._rtsp_override is not None:
            return self._rtsp_override
        parsed = urlsplit(self._base_url)
        hostname = parsed.hostname or ""
        if ":" in hostname:
            hostname = f"[{hostname}]"
        return f"rtsp://{hostname}:{rtsp_port}/{quote(camera_id, safe='')}"

    async def _async_json(self, path: str) -> dict[str, Any]:
        content = await self._async_bytes(path)
        if content is None:
            raise OwletBridgeCompatibilityError("The bridge response is missing")
        try:
            payload: object = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as err:
            raise OwletBridgeCompatibilityError(
                "The bridge returned malformed JSON"
            ) from err
        if not isinstance(payload, dict):
            raise OwletBridgeCompatibilityError(
                "The bridge returned an incompatible response"
            )
        return payload

    async def _async_bytes(
        self, path: str, *, allow_not_found: bool = False
    ) -> bytes | None:
        try:
            async with asyncio.timeout(self._request_timeout):
                async with self._session.get(
                    f"{self._base_url}{path}",
                    headers=self._headers(),
                    ssl=self._verify_tls,
                ) as response:
                    if response.status in {401, 403}:
                        raise OwletBridgeAuthenticationError(
                            "The bridge rejected API authentication"
                        )
                    if allow_not_found and response.status == 404:
                        return None
                    if response.status != 200:
                        raise OwletBridgeConnectionError("The bridge request failed")
                    content = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        content.extend(chunk)
                        if len(content) > MAX_BRIDGE_RESPONSE_SIZE:
                            raise OwletBridgeConnectionError(
                                "The bridge response exceeded the size limit"
                            )
                    return bytes(content)
        except (TimeoutError, ClientError) as err:
            raise OwletBridgeConnectionError("The bridge could not be reached") from err

    def _headers(self) -> dict[str, str]:
        if self._username is not None and self._password_or_token is not None:
            credential = b64encode(
                f"{self._username}:{self._password_or_token}".encode()
            ).decode("ascii")
            return {"Authorization": f"Basic {credential}"}
        if self._password_or_token is not None:
            return {"Authorization": f"Bearer {self._password_or_token}"}
        return {}


def normalize_bridge_url(value: str) -> str:
    """Normalize an HTTP(S) base URL without credentials, query, or fragments."""
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("The bridge base URL is invalid")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def normalize_rtsp_url(value: str) -> str:
    """Normalize an explicit RTSP source without changing its opaque path."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname or parsed.fragment:
        raise ValueError("The explicit RTSP source is invalid")
    return value.strip()


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_port(value: object) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535
    )


def _optional_int(value: object) -> int | None:
    return int(value) if _is_number(value) else None


def _optional_float(value: object) -> float | None:
    return float(value) if _is_number(value) else None
