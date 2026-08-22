"""Pytest configuration for Owlet Cam."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable loading this repository's custom integration."""
    return


@pytest.fixture(autouse=True)
def mock_ffmpeg_version() -> Iterator[None]:
    """Avoid requiring a host FFmpeg binary for integration setup tests."""
    with patch(
        "haffmpeg.tools.FFVersion.get_version",
        new=AsyncMock(return_value="6.0"),
    ):
        yield
