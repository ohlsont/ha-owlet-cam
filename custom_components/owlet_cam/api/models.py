"""Typed API models."""

from dataclasses import dataclass, field
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


@dataclass(frozen=True, slots=True, repr=False)
class OwletCameraCredentials:
    """Secret camera material passed only to the isolated native helper.

    This object must never be serialized, logged, included in diagnostics, or
    retained by an entity. ``repr=False`` prevents accidental dataclass output.
    """

    uid: str = field(repr=False)
    auth_key: str = field(repr=False)
    av_password: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class OwletCameraData:
    """Non-secret camera data shared with Home Assistant entities."""

    camera_id: str
    name: str
