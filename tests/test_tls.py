"""Tests for the TLS helper (no Home Assistant instance needed)."""

from __future__ import annotations

import ssl

import pytest

from custom_components.docker_socket_proxy.const import (
    CONF_CA_CERT,
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    CONF_CLIENT_KEY_PASSWORD,
)
from custom_components.docker_socket_proxy.tls import (
    DockerProxyTLSError,
    build_ssl_context,
    has_custom_tls,
)

from .pki import Authority


def _reason(data: dict) -> str:
    with pytest.raises(DockerProxyTLSError) as err:
        build_ssl_context(data)
    return err.value.reason


def test_no_tls_data_returns_none() -> None:
    assert build_ssl_context({}) is None
    assert build_ssl_context({"name": "x", "url": "http://h:2375"}) is None
    assert not has_custom_tls({"url": "http://h:2375"})


def test_ca_only_builds_verifying_context(ca: Authority) -> None:
    ctx = build_ssl_context({CONF_CA_CERT: ca.pem})
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_strict_flag_relaxed_but_verification_kept(ca: Authority) -> None:
    ctx = build_ssl_context({CONF_CA_CERT: ca.pem})
    assert not ctx.verify_flags & ssl.VERIFY_X509_STRICT
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_mutual_tls_context(ca: Authority, client_pair: tuple[str, str]) -> None:
    cert, key = client_pair
    ctx = build_ssl_context(
        {CONF_CA_CERT: ca.pem, CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: key}
    )
    assert isinstance(ctx, ssl.SSLContext)


def test_client_cert_without_ca_is_allowed(client_pair: tuple[str, str]) -> None:
    cert, key = client_pair
    assert build_ssl_context({CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: key}) is not None


def test_cert_and_key_must_come_together(client_pair: tuple[str, str]) -> None:
    cert, key = client_pair
    assert _reason({CONF_CLIENT_CERT: cert}) == "client_cert_key_required"
    assert _reason({CONF_CLIENT_KEY: key}) == "client_cert_key_required"


def test_garbage_inputs_are_rejected(client_pair: tuple[str, str]) -> None:
    cert, key = client_pair
    assert _reason({CONF_CA_CERT: "not a pem"}) == "invalid_ca_cert"
    assert (
        _reason({CONF_CA_CERT: "-----BEGIN CERTIFICATE-----\nzzzz\n-----END CERTIFICATE-----"})
        == "invalid_ca_cert"
    )
    assert _reason({CONF_CLIENT_CERT: "nope", CONF_CLIENT_KEY: key}) == "invalid_client_cert"
    assert _reason({CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: "nope"}) == "invalid_client_key"
    broken = "-----BEGIN PRIVATE KEY-----\nzzzz\n-----END PRIVATE KEY-----"
    assert _reason({CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: broken}) == "invalid_client_key"


def test_mismatched_cert_and_key(ca: Authority, client_pair: tuple[str, str]) -> None:
    cert, _ = client_pair
    _, other_key = ca.issue("someone-else")
    data = {CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: other_key}
    assert _reason(data) == "client_cert_key_mismatch"


def test_encrypted_key_passphrase_handling(ca: Authority) -> None:
    cert, key = ca.issue_encrypted("enc-client", "s3cret")
    base = {CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: key}
    assert build_ssl_context({**base, CONF_CLIENT_KEY_PASSWORD: "s3cret"}) is not None
    assert _reason(base) == "client_key_password_required"
    assert _reason({**base, CONF_CLIENT_KEY_PASSWORD: "wrong"}) == "client_key_password_incorrect"


def test_no_temp_key_material_left_behind(
    ca: Authority, client_pair: tuple[str, str], tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    cert, key = client_pair
    build_ssl_context({CONF_CLIENT_CERT: cert, CONF_CLIENT_KEY: key})
    assert list(tmp_path.iterdir()) == []
