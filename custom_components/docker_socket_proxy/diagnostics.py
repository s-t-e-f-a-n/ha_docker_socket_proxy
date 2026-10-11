"""Diagnostics support for Docker Socket Proxy.

Secrets are never included: the client private key and its passphrase are
redacted, and certificates are summarised (subject / expiry) instead of dumped.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant

from .const import (
    ATTR_CONTAINERS,
    CONF_CA_CERT,
    CONF_CLIENT_CERT,
    DOMAIN,
    TLS_SECRET_KEYS,
)

# Redacted everywhere they appear in the entry data. The URL host identifies the
# user's network, and certificate PEMs are replaced by a summary below.
TO_REDACT = {CONF_URL, CONF_CA_CERT, CONF_CLIENT_CERT, *TLS_SECRET_KEYS}


def _describe_cert(pem: str | None) -> dict[str, Any] | None:
    """Summarise the first certificate in a PEM string (no key material)."""
    if not pem:
        return None
    try:
        from cryptography import x509  # bundled with Home Assistant core

        cert = x509.load_pem_x509_certificate(pem.encode())
        return {
            "subject": cert.subject.rfc4514_string(),
            "not_valid_after": cert.not_valid_after_utc.isoformat(),
        }
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return {"error": "unreadable"}


def _redacted_url(url: str) -> str:
    """Keep scheme and port (useful for debugging); drop the host."""
    parsed = urlparse(url)
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://<redacted>{port}"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = entry.data

    diagnostics: dict[str, Any] = {
        "entry": {
            "data": async_redact_data(dict(data), TO_REDACT),
            "options": dict(entry.options),
        },
        "connection": {
            "url": _redacted_url(data.get(CONF_URL, "")),
            "tls": {
                "custom_ca": bool(data.get(CONF_CA_CERT)),
                "client_certificate": bool(data.get(CONF_CLIENT_CERT)),
                "ca_summary": _describe_cert(data.get(CONF_CA_CERT)),
                "client_certificate_summary": _describe_cert(
                    data.get(CONF_CLIENT_CERT)
                ),
            },
        },
    }

    if coordinator is not None:
        containers = (coordinator.data or {}).get(ATTR_CONTAINERS, {})
        diagnostics["coordinator"] = {
            "host_status": coordinator.host_status,
            "last_error": coordinator.last_error,
            "last_update_success": coordinator.last_update_success,
            "container_count": len(containers),
            "ssl_context_in_use": coordinator.ssl_context is not None,
        }

    return diagnostics
