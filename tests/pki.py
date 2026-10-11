"""Throwaway PKI for the TLS tests (generated in memory, never written to the repo)."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(
    cn: str,
    key: rsa.RSAPrivateKey,
    *,
    issuer: x509.Name | None = None,
    issuer_key: rsa.RSAPrivateKey | None = None,
    ca: bool = False,
    san: list[x509.GeneralName] | None = None,
    key_ids: bool = False,
    days: int = 2,
    expired: bool = False,
) -> x509.Certificate:
    now = dt.datetime.now(dt.UTC)
    start = now - dt.timedelta(days=10 if expired else 1)
    end = now - dt.timedelta(days=5) if expired else now + dt.timedelta(days=days)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(issuer or _name(cn))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(end)
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if san:
        builder = builder.add_extension(x509.SubjectAlternativeName(san), critical=False)
    if key_ids:
        builder = builder.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        signer = (issuer_key or key).public_key()
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(signer), critical=False
        )
    return builder.sign(issuer_key or key, hashes.SHA256())


def cert_pem(cert: x509.Certificate) -> str:
    """Return a certificate as PEM text."""
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def key_pem(key: rsa.RSAPrivateKey, password: str | None = None) -> str:
    """Return a private key as PKCS#8 PEM text, optionally encrypted."""
    enc = (
        serialization.BestAvailableEncryption(password.encode())
        if password
        else serialization.NoEncryption()
    )
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc
    ).decode()


@dataclass
class Authority:
    """A CA plus the ability to issue leaf certificates."""

    key: rsa.RSAPrivateKey
    cert: x509.Certificate

    @classmethod
    def create(cls, cn: str, *, key_ids: bool = True) -> Authority:
        key = _key()
        return cls(key, _cert(cn, key, ca=True, key_ids=key_ids))

    @property
    def pem(self) -> str:
        return cert_pem(self.cert)

    def issue(
        self,
        cn: str,
        *,
        hosts: tuple[str, ...] = (),
        key_ids: bool = True,
        expired: bool = False,
    ) -> tuple[str, str]:
        """Issue a leaf certificate. Returns (cert_pem, key_pem)."""
        key = _key()
        san: list[x509.GeneralName] = []
        for host in hosts:
            try:
                san.append(x509.IPAddress(ipaddress.ip_address(host)))
            except ValueError:
                san.append(x509.DNSName(host))
        cert = _cert(
            cn,
            key,
            issuer=self.cert.subject,
            issuer_key=self.key,
            san=san or None,
            key_ids=key_ids,
            expired=expired,
        )
        return cert_pem(cert), key_pem(key)

    def issue_encrypted(self, cn: str, password: str) -> tuple[str, str]:
        """Issue a leaf whose private key is passphrase-protected."""
        key = _key()
        cert = _cert(cn, key, issuer=self.cert.subject, issuer_key=self.key, key_ids=True)
        return cert_pem(cert), key_pem(key, password)
