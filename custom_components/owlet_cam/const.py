"""Constants for Owlet Cam."""

from typing import Final

DOMAIN: Final = "owlet_cam"
PLATFORMS: Final = ["sensor"]

CONF_MODE: Final = "mode"
MODE_DEVELOPMENT: Final = "development"
DEV_MODE_ENV: Final = "OWLET_CAM_DEV_MODE"

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
    "stream_path_token",
    "token",
    "uid",
    "username",
}
