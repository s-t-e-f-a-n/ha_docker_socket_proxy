"""End-to-end tests: real Home Assistant setup against a real local TLS server."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
import ssl
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import unused_port
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.docker_socket_proxy.const import (
    CONF_CA_CERT,
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    DOMAIN,
)

from .pki import Authority

CONTAINERS = [
    {
        "Id": "abc123",
        "Names": ["/web"],
        "Image": "nginx:latest",
        "State": "running",
        "Status": "Up 2 hours (healthy)",
        "Created": 1700000000,
        "Labels": {},
        "Ports": [],
        "NetworkSettings": {"Networks": {}},
    }
]


@pytest.fixture(autouse=True)
def no_blueprint_copy():
    with patch("custom_components.docker_socket_proxy.async_install_blueprint"):
        yield


@pytest.fixture
async def real_session(socket_enabled):
    """Give the coordinator a real aiohttp session.

    The test harness replaces Home Assistant's resolver, so its shared session
    cannot reach even localhost. Everything else (SSL context, request path,
    error handling) is the production code.
    """
    session = aiohttp.ClientSession()
    with patch(
        "custom_components.docker_socket_proxy.coordinator.async_get_clientsession",
        return_value=session,
    ):
        yield session
    await session.close()


async def _version(_request: web.Request) -> web.Response:
    return web.json_response({"Version": "27.0", "ApiVersion": "1.46", "Os": "linux"})


async def _containers(_request: web.Request) -> web.Response:
    return web.json_response(CONTAINERS)


async def _forbidden(_request: web.Request) -> web.Response:
    return web.Response(status=403)


@pytest.fixture
async def tls_proxy(
    socket_enabled, ca: Authority, server_pair
) -> AsyncIterator[Callable[..., Awaitable[str]]]:
    """Start an mTLS proxy on localhost; returns its base URL."""
    runners: list[web.AppRunner] = []
    tmp: list[str] = []

    async def start(*, require_client: bool = True, containers_status: int = 200) -> str:
        import tempfile, os

        d = tempfile.mkdtemp()
        tmp.append(d)
        cert, key = server_pair
        for name, text in (("s.pem", cert), ("s.key", key), ("ca.pem", ca.pem)):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(text)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(os.path.join(d, "s.pem"), os.path.join(d, "s.key"))
        if require_client:
            ctx.load_verify_locations(os.path.join(d, "ca.pem"))
            ctx.verify_mode = ssl.CERT_REQUIRED
        app = web.Application()
        app.router.add_get("/version", _version)
        app.router.add_get(
            "/containers/json", _containers if containers_status == 200 else _forbidden
        )
        runner = web.AppRunner(app)
        await runner.setup()
        port = unused_port()
        await web.TCPSite(runner, "127.0.0.1", port, ssl_context=ctx).start()
        runners.append(runner)
        return f"https://localhost:{port}"

    yield start
    for runner in runners:
        await runner.cleanup()


def _entry(url: str, **tls) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title="Proxy", unique_id=url,
        data={"name": "Proxy", "url": url, **tls}, options={"scan_interval": 30},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry):
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data.get(DOMAIN, {}).get(entry.entry_id)


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_mtls_end_to_end(hass, real_session, tls_proxy, ca, client_pair) -> None:
    url = await tls_proxy()
    cert, key = client_pair
    entry = _entry(url, **{CONF_CA_CERT: ca.pem, CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: key})
    coordinator = await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert coordinator.host_status == "1/1 running"
    assert coordinator.last_error is None
    assert coordinator.ssl_context is not None
    await _unload(hass, entry)


async def test_server_only_tls_with_private_ca(hass, real_session, tls_proxy, ca) -> None:
    url = await tls_proxy(require_client=False)
    coordinator = await _setup(hass, _entry(url, **{CONF_CA_CERT: ca.pem}))
    assert coordinator.host_status == "1/1 running"
    await _unload(hass, hass.config_entries.async_entries(DOMAIN)[0])


async def test_missing_client_cert_is_reported_clearly(hass, real_session, tls_proxy, ca) -> None:
    url = await tls_proxy()
    entry = _entry(url, **{CONF_CA_CERT: ca.pem})  # proxy wants a client cert
    coordinator = await _setup(hass, entry)
    assert coordinator.host_status == "unavailable version"
    assert "client certificate" in coordinator.last_error
    await _unload(hass, entry)


async def test_untrusted_server_is_reported_clearly(hass, real_session, tls_proxy, other_ca, client_pair) -> None:
    url = await tls_proxy()
    cert, key = client_pair
    entry = _entry(
        url, **{CONF_CA_CERT: other_ca.pem, CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: key}
    )
    coordinator = await _setup(hass, entry)
    assert coordinator.host_status == "unavailable version"
    assert "certificate verification failed" in coordinator.last_error
    await _unload(hass, entry)


async def test_https_without_custom_ca_uses_default_trust(hass, real_session, tls_proxy) -> None:
    """No custom CA: the private test CA is not in the default store, so it fails closed."""
    url = await tls_proxy(require_client=False)
    entry = _entry(url)
    coordinator = await _setup(hass, entry)
    assert coordinator.ssl_context is None
    assert coordinator.host_status == "unavailable version"
    await _unload(hass, entry)


async def test_403_from_proxy_is_distinguished(hass, real_session, tls_proxy, ca) -> None:
    url = await tls_proxy(require_client=False, containers_status=403)
    entry = _entry(url, **{CONF_CA_CERT: ca.pem})
    coordinator = await _setup(hass, entry)
    assert coordinator.host_status == "unavailable containers"
    assert "HTTP 403" in coordinator.last_error
    await _unload(hass, entry)


async def test_corrupt_stored_tls_is_a_setup_error(hass) -> None:
    entry = _entry(
        "https://proxy.lan:2376",
        **{CONF_CLIENT_CERT: "-----BEGIN CERTIFICATE-----\nzz\n-----END CERTIFICATE-----",
           CONF_CLIENT_KEY: "-----BEGIN PRIVATE KEY-----\nzz\n-----END PRIVATE KEY-----"},
    )
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_legacy_plain_http_entry_still_works(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An entry saved by the original version (no TLS keys) must keep working."""
    aioclient_mock.get("http://10.0.0.5:2375/version", json={"Version": "27.0"})
    aioclient_mock.get("http://10.0.0.5:2375/containers/json?all=1", json=CONTAINERS)
    entry = MockConfigEntry(
        domain=DOMAIN, title="NAS", unique_id="http://10.0.0.5:2375",
        data={"name": "NAS", "url": "http://10.0.0.5:2375"},
    )
    coordinator = await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert coordinator.ssl_context is None
    assert coordinator.host_status == "1/1 running"
    await _unload(hass, entry)
