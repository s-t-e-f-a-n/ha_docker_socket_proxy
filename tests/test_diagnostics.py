"""Diagnostics must never leak key material, passphrases or the proxy host."""

from __future__ import annotations

import json
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.docker_socket_proxy.const import (
    CONF_CA_CERT,
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    CONF_CLIENT_KEY_PASSWORD,
    DOMAIN,
)


async def test_diagnostics_redacts_secrets(hass: HomeAssistant, hass_client, ca) -> None:
    cert, key = ca.issue_encrypted("diag-client", "hunter2")
    entry = MockConfigEntry(
        domain=DOMAIN, title="NAS", unique_id="https://192.168.9.9:2376",
        data={
            "name": "NAS", "url": "https://192.168.9.9:2376",
            CONF_CA_CERT: ca.pem, CONF_CLIENT_CERT: cert,
            CONF_CLIENT_KEY: key, CONF_CLIENT_KEY_PASSWORD: "hunter2",
        },
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "diagnostics", {})
    # Load the integration (so its diagnostics platform registers) without
    # starting a coordinator; this entry points at a host that does not exist.
    with patch("custom_components.docker_socket_proxy.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    text = json.dumps(result)

    for secret in ("BEGIN", "hunter2", "192.168.9.9", key.splitlines()[1]):
        assert secret not in text, secret

    assert result["connection"]["url"] == "https://<redacted>:2376"
    tls = result["connection"]["tls"]
    assert tls["custom_ca"] is True and tls["client_certificate"] is True
    assert tls["ca_summary"]["subject"] == "CN=test-ca"
    assert "not_valid_after" in tls["client_certificate_summary"]
    assert "coordinator" not in result  # entry was never set up


async def test_diagnostics_includes_live_coordinator_state(
    hass: HomeAssistant, hass_client, aioclient_mock
) -> None:
    aioclient_mock.get("http://h:2375/version", json={"Version": "27"})
    aioclient_mock.get("http://h:2375/containers/json?all=1", json=[])
    entry = MockConfigEntry(
        domain=DOMAIN, title="NAS", unique_id="http://h:2375",
        data={"name": "NAS", "url": "http://h:2375"},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "diagnostics", {})
    with patch("custom_components.docker_socket_proxy.async_install_blueprint"):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert result["connection"]["tls"]["custom_ca"] is False
    assert result["connection"]["tls"]["ca_summary"] is None
    assert result["connection"]["url"] == "http://<redacted>:2375"
    assert result["coordinator"]["ssl_context_in_use"] is False
    assert result["coordinator"]["last_update_success"] is True
    assert result["coordinator"]["last_error"] is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
