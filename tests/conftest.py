"""Fixtures for Lens tests."""

import sys

import pytest
import pytest_socket

pytest_plugins = "pytest_homeassistant_custom_component"

if sys.platform == "win32":
    # The Windows asyncio loop needs an AF_INET socketpair, which the HA plugin's
    # socket guard blocks. CI runs on Linux with the guard in place.
    pytest_socket.disable_socket = lambda *args, **kwargs: None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in every test."""
    return
