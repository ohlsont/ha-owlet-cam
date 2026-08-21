"""Typed API models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class OwletCloudMetadata:
    """Non-secret result of cloud authentication and camera KMS validation."""

    account_id: str
    camera_dsn: str
    camera_uid_available: bool
    auth_key_available: bool
    av_password_available: bool
    token_expiry: datetime

    @property
    def credentials_available(self) -> bool:
        """Return whether every camera credential was present."""
        return (
            self.camera_uid_available
            and self.auth_key_available
            and self.av_password_available
        )


@dataclass(frozen=True, slots=True)
class OwletCameraData:
    """Non-secret camera data shared with Home Assistant entities."""

    camera_id: str
    name: str
