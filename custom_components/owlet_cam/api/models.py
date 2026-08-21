"""Typed API models."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OwletCameraData:
    """Non-secret camera data shared with Home Assistant entities."""

    camera_id: str
    name: str
