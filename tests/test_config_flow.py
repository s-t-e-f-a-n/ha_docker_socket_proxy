"""Tests for the config flow: setup, TLS validation and in-place reconfigure."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
import uuid
from unittest.mock import MagicMock, patch

import aiohttp
from aiohttp.client_reqrep import ConnectionKey
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.docker_socket_proxy.const import (
    CONF_CA_CERT,
    CONF_CLEAR_TLS,
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    CONF_CLIENT_KEY_PASSWORD,
    DOMAIN,
)

from .pki import Authority

FLOW = "custom_components.docker_socket_proxy.config_flow"


class FakeUploads:
    """Stand-in for HA's file_upload store: file_id -> text."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.files: dict[str, str] = {}

    def add(self, _label: str, text: str) -> str:
        """Store text and return a UUID, which is what FileSelector accepts."""
        file_id = str(uuid.uuid4())
        self.files[file_id] = text
        return file_id

    @contextmanager
    def process(self, hass, file_id):
        path = self.tmp_path / file_id
        path.write_text(self.files[file_id], encoding="utf-8")
        yield path


@pytest.fixture
def uploads(tmp_path: Path):
    fake = FakeUploads(tmp_path)
    with patch(f"{FLOW}.process_uploaded_file", fake.process):
        yield fake


class FakeSession:
    """Records get() calls; behaves like aiohttp's session for the flow."""

    def __init__(self, status: int = 200, exc: Exception | None = None) -> None:
        self.status, self.exc, self.calls = status, exc, []

    @asynccontextmanager
    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.exc:
            raise self.exc
        yield MagicMock(status=self.status)


@pytest.fixture
def session():
    fake = FakeSession()
    with patch(f"{FLOW}.async_get_clientsession", return_value=fake):
        yield fake


@pytest.fixture(autouse=True)
def no_setup():
    """Config flow tests don't need the integration to actually start."""
    with patch(
        "custom_components.docker_socket_proxy.async_setup_entry", return_value=True
    ) as mock:
        yield mock


async def _start_user(hass: HomeAssistant, **overrides) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "NAS", "url": "http://10.0.0.5:2375", **overrides}
    )


async def test_plain_http_setup_unchanged(hass: HomeAssistant, session) -> None:
    result = await _start_user(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"name": "NAS", "url": "http://10.0.0.5:2375"}
    assert "ssl" not in session.calls[0][1]  # HA's default session behaviour


async def test_trailing_slash_normalised(hass: HomeAssistant, session) -> None:
    result = await _start_user(hass, url="http://10.0.0.5:2375/")
    assert result["data"]["url"] == "http://10.0.0.5:2375"


async def test_mtls_setup_stores_pem_and_uses_context(
    hass: HomeAssistant, session, uploads: FakeUploads, ca: Authority, client_pair
) -> None:
    cert, key = client_pair
    result = await _start_user(
        hass,
        url="https://proxy.lan:2376",
        **{
            CONF_CA_CERT: uploads.add("ca", ca.pem),
            CONF_CLIENT_CERT: uploads.add("cert", cert),
            CONF_CLIENT_KEY: uploads.add("key", key),
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CA_CERT] == ca.pem
    assert result["data"][CONF_CLIENT_CERT] == cert
    assert result["data"][CONF_CLIENT_KEY] == key
    assert session.calls[0][1]["ssl"] is not None


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"cert_only": True}, "client_cert_key_required"),
        ({"bad_ca": True}, "invalid_ca_cert"),
    ],
)
async def test_tls_input_errors(
    hass: HomeAssistant, session, uploads, client_pair, fields, error
) -> None:
    extra = {}
    if fields.get("cert_only"):
        extra[CONF_CLIENT_CERT] = uploads.add("cert", client_pair[0])
    if fields.get("bad_ca"):
        extra[CONF_CA_CERT] = uploads.add("ca", "garbage")
    result = await _start_user(hass, url="https://proxy.lan:2376", **extra)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert session.calls == []  # never contacted the proxy with bad material


async def test_passphrase_without_key_is_rejected(hass: HomeAssistant, session) -> None:
    result = await _start_user(
        hass, url="https://proxy.lan:2376", **{CONF_CLIENT_KEY_PASSWORD: "x"}
    )
    assert result["errors"] == {"base": "client_cert_key_required"}


def _client_conn_error(cls, **kw):
    key = ConnectionKey("h", 1, True, True, None, None, None)
    return cls(key, OSError("boom"), **kw)


@pytest.mark.parametrize(
    ("url", "exc", "error"),
    [
        ("http://h:2375", aiohttp.ClientConnectionError("x"), "cannot_connect"),
        ("http://h:2375", TimeoutError(), "cannot_connect"),
        ("https://h:2376", aiohttp.ClientSSLError(
            ConnectionKey("h", 1, True, True, None, None, None), OSError("x")), "ssl_error"),
        ("https://h:2376", aiohttp.ServerDisconnectedError(), "ssl_error"),
        ("http://h:2375", aiohttp.ServerDisconnectedError(), "cannot_connect"),
        ("http://h:2375", RuntimeError("bug"), "unknown"),
    ],
)
async def test_connection_error_mapping(hass: HomeAssistant, url, exc, error) -> None:
    with patch(f"{FLOW}.async_get_clientsession", return_value=FakeSession(exc=exc)):
        result = await _start_user(hass, url=url)
    assert result["errors"] == {"base": error}


async def test_non_200_is_cannot_connect(hass: HomeAssistant) -> None:
    with patch(f"{FLOW}.async_get_clientsession", return_value=FakeSession(status=403)):
        result = await _start_user(hass)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_url_aborts(hass: HomeAssistant, session) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id="http://10.0.0.5:2375",
        data={"name": "A", "url": "http://10.0.0.5:2375"},
    ).add_to_hass(hass)
    result = await _start_user(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------- reconfigure


def _legacy_entry(hass: HomeAssistant, url="http://10.0.0.5:2375", **extra):
    """An entry as created by the original (pre-TLS) version of the integration."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="NAS", unique_id=url,
        data={"name": "NAS", "url": url, **extra},
        options={"scan_interval": 30},
    )
    entry.add_to_hass(hass)
    return entry


async def test_reconfigure_legacy_entry_to_mtls_in_place(
    hass: HomeAssistant, session, uploads, ca, client_pair
) -> None:
    entry = _legacy_entry(hass)
    original_id = entry.entry_id
    cert, key = client_pair

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["description_placeholders"] == {"stored": "none"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "url": "https://proxy.lan:2376/",
            CONF_CA_CERT: uploads.add("ca", ca.pem),
            CONF_CLIENT_CERT: uploads.add("cert", cert),
            CONF_CLIENT_KEY: uploads.add("key", key),
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    updated = hass.config_entries.async_get_entry(original_id)
    assert updated is entry  # same entry => same entity unique IDs and history
    assert entry.unique_id == "https://proxy.lan:2376"
    assert entry.data["url"] == "https://proxy.lan:2376"
    assert entry.data["name"] == "NAS"
    assert entry.data[CONF_CLIENT_KEY] == key
    assert entry.options == {"scan_interval": 30}  # options untouched


async def test_reconfigure_empty_fields_keep_stored_files(
    hass: HomeAssistant, session, ca, client_pair
) -> None:
    cert, key = client_pair
    entry = _legacy_entry(
        hass, url="https://proxy.lan:2376",
        **{CONF_CA_CERT: ca.pem, CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: key},
    )
    result = await entry.start_reconfigure_flow(hass)
    assert result["description_placeholders"] == {
        "stored": "CA certificate, client certificate, client key"
    }
    # Change only the port; leave every file field empty.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "https://proxy.lan:2377"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_CA_CERT] == ca.pem
    assert entry.data[CONF_CLIENT_KEY] == key
    assert entry.unique_id == "https://proxy.lan:2377"
    assert session.calls[-1][1]["ssl"] is not None


async def test_reconfigure_same_url_does_not_trip_duplicate_check(
    hass: HomeAssistant, session
) -> None:
    entry = _legacy_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "http://10.0.0.5:2375"}
    )
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_to_url_used_by_other_entry_aborts(
    hass: HomeAssistant, session
) -> None:
    _legacy_entry(hass, url="http://10.0.0.6:2375")
    entry = _legacy_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "http://10.0.0.6:2375"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.unique_id == "http://10.0.0.5:2375"


async def test_reconfigure_clear_tls_removes_material(
    hass: HomeAssistant, session, ca, client_pair
) -> None:
    cert, key = client_pair
    entry = _legacy_entry(
        hass, url="http://10.0.0.5:2375",
        **{CONF_CA_CERT: ca.pem, CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: key,
           CONF_CLIENT_KEY_PASSWORD: "pw"},
    )
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "http://10.0.0.5:2375", CONF_CLEAR_TLS: True}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {"name": "NAS", "url": "http://10.0.0.5:2375"}


async def test_reconfigure_failure_keeps_entry_untouched(
    hass: HomeAssistant, uploads
) -> None:
    entry = _legacy_entry(hass)
    before = dict(entry.data)
    with patch(f"{FLOW}.async_get_clientsession", return_value=FakeSession(status=500)):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"url": "https://nope:2376"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert dict(entry.data) == before
    assert entry.unique_id == "http://10.0.0.5:2375"


async def test_reconfigure_new_key_drops_old_passphrase(
    hass: HomeAssistant, session, uploads, ca
) -> None:
    cert, key = ca.issue("new-client")
    entry = _legacy_entry(
        hass, **{CONF_CLIENT_CERT: "old", CONF_CLIENT_KEY: "old", CONF_CLIENT_KEY_PASSWORD: "oldpw"}
    )
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "url": "http://10.0.0.5:2375",
            CONF_CLIENT_CERT: uploads.add("cert", cert),
            CONF_CLIENT_KEY: uploads.add("key", key),
        },
    )
    assert result["reason"] == "reconfigure_successful"
    assert CONF_CLIENT_KEY_PASSWORD not in entry.data
