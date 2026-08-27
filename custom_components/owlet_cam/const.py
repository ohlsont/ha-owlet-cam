"""Constants for Owlet Cam."""

from datetime import timedelta
from typing import Final

from homeassistant.const import CONF_PASSWORD as HA_CONF_PASSWORD
from homeassistant.const import Platform

DOMAIN: Final = "owlet_cam"
INTEGRATION_VERSION: Final = "0.9.0"
EXPECTED_HELPER_VERSION: Final = INTEGRATION_VERSION
PLATFORMS: Final = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
]

CONF_MODE: Final = "mode"
CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = HA_CONF_PASSWORD
CONF_REGION: Final = "region"
CONF_CAMERA_DSN: Final = "camera_dsn"
CONF_CAMERA_NAME: Final = "camera_name"
CONF_BRIDGE_URL: Final = "bridge_url"
CONF_BRIDGE_USERNAME: Final = "bridge_username"
CONF_BRIDGE_PASSWORD: Final = "bridge_password"  # noqa: S105
CONF_BRIDGE_CAMERA_ID: Final = "bridge_camera_id"
CONF_RTSP_OVERRIDE: Final = "explicit_rtsp_source"
CONF_VERIFY_TLS: Final = "verify_tls"
CONF_BRIDGE_TIMEOUT: Final = "bridge_request_timeout"

MODE_EXTERNAL: Final = "external_bridge"
MODE_EMBEDDED: Final = "embedded"
MODE_DEVELOPMENT: Final = "development"
DEV_MODE_ENV: Final = "OWLET_CAM_DEV_MODE"

REGION_EUROPE: Final = "europe"
REGION_WORLD: Final = "world"
REGIONS: Final = (REGION_EUROPE, REGION_WORLD)

CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_KEEP_WARM: Final = "keep_camera_session_warm"
CONF_IDLE_TIMEOUT: Final = "idle_disconnect_timeout"
CONF_STREAM_QUALITY: Final = "stream_quality"
CONF_ENABLE_AUDIO: Final = "enable_audio"
CONF_DEBUG_LOGGING: Final = "debug_logging"
CONF_DELETE_PROPRIETARY_FILES: Final = "delete_proprietary_files"
CONF_CONFIRM_DELETE: Final = "confirm_delete_proprietary_files"
CONF_RUNTIME_CHANNEL: Final = "runtime_channel"
CONF_RECONNECT_BACKOFF: Final = "reconnect_backoff"
CONF_NO_FRAME_TIMEOUT: Final = "no_frame_timeout"
CONF_PREFER_DIRECT_P2P: Final = "prefer_direct_p2p"
CONF_EXPERIMENTAL_LOCAL_SENSORS: Final = "experimental_local_sensors"
CONF_RETAIN_APPLICATION: Final = "retain_uploaded_application"
CONF_RUNTIME_PACKAGE: Final = "runtime_package"

DEFAULT_UPDATE_INTERVAL: Final = 300
DEFAULT_KEEP_WARM: Final = False
DEFAULT_IDLE_TIMEOUT: Final = 60
DEFAULT_STREAM_QUALITY: Final = "high"
DEFAULT_ENABLE_AUDIO: Final = True
DEFAULT_DEBUG_LOGGING: Final = False
DEFAULT_RUNTIME_CHANNEL: Final = "stable"
DEFAULT_RECONNECT_BACKOFF: Final = 30
DEFAULT_NO_FRAME_TIMEOUT: Final = 15
DEFAULT_PREFER_DIRECT_P2P: Final = False
DEFAULT_EXPERIMENTAL_LOCAL_SENSORS: Final = False
DEFAULT_RETAIN_APPLICATION: Final = False
DEFAULT_COORDINATOR_INTERVAL: Final = timedelta(seconds=DEFAULT_UPDATE_INTERVAL)
DEFAULT_VERIFY_TLS: Final = True
DEFAULT_BRIDGE_TIMEOUT: Final = 10

STATUS_READY: Final = "ready"

REDACT_KEYS: Final = {
    "account_password",
    "auth_key",
    "av_password",
    "bridge_password",
    "bridge_token",
    "camera_dsn",
    "email",
    "firebase_token",
    "password",
    "refresh_token",
    "sdk_key",
    "explicit_rtsp_source",
    "stream_path_token",
    "token",
    "uid",
    "username",
}
