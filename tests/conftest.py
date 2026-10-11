"""Shared fixtures for the Docker Socket Proxy tests."""

from __future__ import annotations

import pytest

from .pki import Authority

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load the integration from custom_components/."""


@pytest.fixture(scope="session")
def ca() -> Authority:
    """The private CA that the test proxy's certificates chain to."""
    return Authority.create("test-ca")


@pytest.fixture(scope="session")
def other_ca() -> Authority:
    """An unrelated CA, used to provoke verification failures."""
    return Authority.create("other-ca")


@pytest.fixture(scope="session")
def server_pair(ca: Authority) -> tuple[str, str]:
    """Server certificate valid for localhost and 127.0.0.1."""
    return ca.issue("proxy", hosts=("localhost", "127.0.0.1"))


@pytest.fixture(scope="session")
def client_pair(ca: Authority) -> tuple[str, str]:
    """Client certificate (cert_pem, key_pem) signed by the test CA."""
    return ca.issue("ha-client")
