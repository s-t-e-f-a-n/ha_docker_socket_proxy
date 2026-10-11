"""TLS helpers for Docker Socket Proxy.

Builds an ``ssl.SSLContext`` from PEM material stored in a config entry so the
integration can talk to a proxy that is protected by TLS, optionally with a
private CA and/or mutual TLS (client certificate).

Behaviour is deliberately conservative and not tied to any particular
deployment:

* Server certificates are always verified (there is no "skip verification"
  switch). Trust a private or self-signed server by supplying its CA (or the
  server certificate itself) as the CA certificate.
* Without a CA certificate the system/Home Assistant trust store is used.
* A client certificate and key are optional but must be supplied together.
* TLS 1.2 is the minimum protocol version.
"""

from __future__ import annotations

import os
import ssl
import tempfile
from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_CA_CERT,
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    CONF_CLIENT_KEY_PASSWORD,
)

_PEM_MARKER = "-----BEGIN "

# Error keys; these match the entries under "config.error" in strings.json.
ERR_INVALID_CA_CERT = "invalid_ca_cert"
ERR_INVALID_CLIENT_CERT = "invalid_client_cert"
ERR_INVALID_CLIENT_KEY = "invalid_client_key"
ERR_CLIENT_CERT_KEY_REQUIRED = "client_cert_key_required"
ERR_KEY_PASSWORD_REQUIRED = "client_key_password_required"
ERR_KEY_PASSWORD_INCORRECT = "client_key_password_incorrect"
ERR_CERT_KEY_MISMATCH = "client_cert_key_mismatch"


class DockerProxyTLSError(Exception):
    """Raised when the supplied TLS material is unusable.

    ``reason`` is a translation key suitable for a config flow error.
    """

    def __init__(self, reason: str, message: str | None = None) -> None:
        """Initialize the error."""
        super().__init__(message or reason)
        self.reason = reason


def _clean(value: Any) -> str | None:
    """Return stripped text, or None when the value is empty or not text."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def has_custom_tls(data: Mapping[str, Any]) -> bool:
    """Return True if the entry carries any custom TLS material."""
    return any(_clean(data.get(key)) for key in (CONF_CA_CERT, CONF_CLIENT_CERT))


def validate_tls_input(data: Mapping[str, Any]) -> None:
    """Cheap, non-blocking checks on the supplied values.

    Raises DockerProxyTLSError when the combination is invalid. Does not touch
    the filesystem or OpenSSL, so it is safe to call on the event loop.
    """
    ca = _clean(data.get(CONF_CA_CERT))
    cert = _clean(data.get(CONF_CLIENT_CERT))
    key = _clean(data.get(CONF_CLIENT_KEY))

    if ca and _PEM_MARKER not in ca:
        raise DockerProxyTLSError(ERR_INVALID_CA_CERT)
    if (cert is None) != (key is None):
        raise DockerProxyTLSError(ERR_CLIENT_CERT_KEY_REQUIRED)
    if cert and _PEM_MARKER not in cert:
        raise DockerProxyTLSError(ERR_INVALID_CLIENT_CERT)
    if key and _PEM_MARKER not in key:
        raise DockerProxyTLSError(ERR_INVALID_CLIENT_KEY)


def build_ssl_context(data: Mapping[str, Any]) -> ssl.SSLContext | None:
    """Build an SSL context from config entry data.

    Returns None when no custom TLS material is configured, in which case the
    caller should keep using Home Assistant's default session behaviour (plain
    http, or https verified against the default trust store).

    This function does blocking work (OpenSSL parsing, temporary files). Run it
    in an executor: ``await hass.async_add_executor_job(build_ssl_context, data)``.
    """
    validate_tls_input(data)

    ca = _clean(data.get(CONF_CA_CERT))
    cert = _clean(data.get(CONF_CLIENT_CERT))
    key = _clean(data.get(CONF_CLIENT_KEY))
    password = data.get(CONF_CLIENT_KEY_PASSWORD) or None

    if not ca and not cert:
        return None

    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # create_default_context already enables CERT_REQUIRED and hostname checks.
    # Python 3.13+ also sets VERIFY_X509_STRICT, which rejects private-CA
    # certificates lacking optional extensions (e.g. Authority Key Identifier),
    # as produced by many simple `openssl` recipes. Relax only that conformance
    # check: chain validation, expiry and host name matching stay enforced.
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT

    if ca:
        try:
            context.load_verify_locations(cadata=ca)
        except (ssl.SSLError, ValueError) as err:
            raise DockerProxyTLSError(ERR_INVALID_CA_CERT, str(err)) from err

    if cert and key:
        _load_client_chain(context, cert, key, password)

    return context


def _load_client_chain(
    context: ssl.SSLContext, cert: str, key: str, password: str | None
) -> None:
    """Load a client certificate chain from PEM text.

    ``ssl`` can only load a chain from files, so the PEM is written to a private
    temporary directory (mode 0700, files 0600) that is removed immediately.
    """
    with tempfile.TemporaryDirectory(prefix="dsp_tls_") as tmp:
        cert_path = os.path.join(tmp, "client.crt")
        key_path = os.path.join(tmp, "client.key")
        for path, text in ((cert_path, cert), (key_path, key)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text if text.endswith("\n") else text + "\n")

        # A callable password prevents OpenSSL from prompting on a terminal
        # when the key is encrypted and no passphrase was supplied.
        try:
            context.load_cert_chain(
                cert_path, key_path, password=lambda: password or ""
            )
        except ssl.SSLError as err:
            raise DockerProxyTLSError(_classify_chain_error(err, cert, key, password), str(err)) from err
        except (OSError, ValueError) as err:
            raise DockerProxyTLSError(ERR_INVALID_CLIENT_CERT, str(err)) from err


def _classify_chain_error(
    err: ssl.SSLError, cert: str, key: str, password: str | None
) -> str:
    """Map a failed load_cert_chain to a translation key.

    OpenSSL reports most PEM problems as an opaque "PEM lib" error whose text
    differs between versions, so the inputs are re-inspected with
    ``cryptography`` (bundled with Home Assistant) to give a precise reason.
    """
    if "key values mismatch" in str(err).lower():
        return ERR_CERT_KEY_MISMATCH

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import (
            load_pem_private_key,
        )
    except ImportError:  # pragma: no cover - cryptography ships with HA core
        return ERR_INVALID_CLIENT_CERT

    try:
        x509.load_pem_x509_certificate(cert.encode())
    except ValueError:
        return ERR_INVALID_CLIENT_CERT

    try:
        load_pem_private_key(key.encode(), password=password.encode() if password else None)
    except TypeError:
        # Key is encrypted but no passphrase was supplied (or vice versa).
        return ERR_KEY_PASSWORD_INCORRECT if password else ERR_KEY_PASSWORD_REQUIRED
    except ValueError as key_err:
        text = str(key_err).lower()
        if password and ("decrypt" in text or "password" in text):
            return ERR_KEY_PASSWORD_INCORRECT
        return ERR_INVALID_CLIENT_KEY
    except Exception:  # noqa: BLE001 - unsupported key types etc.
        return ERR_INVALID_CLIENT_KEY

    return ERR_INVALID_CLIENT_CERT
