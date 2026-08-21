"""Pytest configuration for Owlet Cam."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable loading this repository's custom integration."""
    return
