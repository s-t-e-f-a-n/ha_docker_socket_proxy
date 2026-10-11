"""Custom integration to integrate Docker Socket Proxy with Home Assistant.

For more details about this integration, please refer to
https://github.com/s-t-e-f-a-n/ha_docker_socket_proxy

Config flow for Docker Socket Proxy integration.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from aiohttp import ClientTimeout
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME, CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    FileSelector,
    FileSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_CA_CERT,
    CONF_CLEAR_TLS,
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    CONF_CLIENT_KEY_PASSWORD,
    CONF_GRACE_PERIOD_ENABLED,
    CONF_GRACE_PERIOD_SECONDS,
    CONF_SCAN_INTERVAL,
    DEFAULT_GRACE_PERIOD_ENABLED,
    DEFAULT_GRACE_PERIOD_SECONDS,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_URL,
    DOMAIN,
)
from .tls import (
    ERR_CLIENT_CERT_KEY_REQUIRED,
    ERR_INVALID_CA_CERT,
    ERR_INVALID_CLIENT_CERT,
    ERR_INVALID_CLIENT_KEY,
    DockerProxyTLSError,
    build_ssl_context,
)

_LOGGER = logging.getLogger(__name__)

# The three uploadable PEM fields; the passphrase is a plain text field.
_UPLOAD_FIELDS = (CONF_CA_CERT, CONF_CLIENT_CERT, CONF_CLIENT_KEY)
_PEM_SELECTOR = FileSelector(FileSelectorConfig(accept=".pem,.crt,.cer,.cert,.key"))
_INVALID_UPLOAD_REASON = {
    CONF_CA_CERT: ERR_INVALID_CA_CERT,
    CONF_CLIENT_CERT: ERR_INVALID_CLIENT_CERT,
    CONF_CLIENT_KEY: ERR_INVALID_CLIENT_KEY,
}


def _tls_fields() -> dict[Any, Any]:
    """Optional TLS fields shared by the setup and reconfigure forms."""
    return {
        vol.Optional(CONF_CA_CERT): _PEM_SELECTOR,
        vol.Optional(CONF_CLIENT_CERT): _PEM_SELECTOR,
        vol.Optional(CONF_CLIENT_KEY): _PEM_SELECTOR,
        vol.Optional(CONF_CLIENT_KEY_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }


def _user_schema(name: str, url: str) -> vol.Schema:
    """Schema for the initial setup dialog (Name, URL and optional TLS)."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=name): str,
            vol.Required(CONF_URL, default=url): str,
            **_tls_fields(),
        }
    )


def _reconfigure_schema(url: str) -> vol.Schema:
    """Schema for reconfiguring an existing entry."""
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=url): str,
            **_tls_fields(),
            vol.Optional(CONF_CLEAR_TLS, default=False): bool,
        }
    )


def _read_uploaded_pem(hass: HomeAssistant, file_id: str) -> str:
    """Read (and consume) an uploaded file. Blocking; run in the executor."""
    with process_uploaded_file(hass, file_id) as path:
        return path.read_text(encoding="utf-8")


async def _async_collect_tls(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn form input into TLS entry data.

    An uploaded file replaces the stored value; an empty field keeps the
    existing one (reconfigure only). Raises DockerProxyTLSError if an upload
    cannot be read as text.
    """
    existing = existing or {}
    tls_data: dict[str, Any] = {}

    for key in _UPLOAD_FIELDS:
        if file_id := user_input.get(key):
            try:
                tls_data[key] = await hass.async_add_executor_job(
                    _read_uploaded_pem, hass, file_id
                )
            except (OSError, ValueError) as err:
                raise DockerProxyTLSError(_INVALID_UPLOAD_REASON[key], str(err)) from err
        elif existing.get(key):
            tls_data[key] = existing[key]

    if password := user_input.get(CONF_CLIENT_KEY_PASSWORD):
        tls_data[CONF_CLIENT_KEY_PASSWORD] = password
    elif existing.get(CONF_CLIENT_KEY_PASSWORD) and not user_input.get(CONF_CLIENT_KEY):
        # Keep the stored passphrase only while the stored key is kept too.
        tls_data[CONF_CLIENT_KEY_PASSWORD] = existing[CONF_CLIENT_KEY_PASSWORD]

    return tls_data


async def _async_validate(
    hass: HomeAssistant, url: str, tls_data: dict[str, Any]
) -> str | None:
    """Check the TLS material and reach /version. Returns an error key or None."""
    kwargs: dict[str, Any] = {}
    try:
        ssl_context = await hass.async_add_executor_job(build_ssl_context, tls_data)
    except DockerProxyTLSError as err:
        return err.reason
    if ssl_context is not None:
        kwargs["ssl"] = ssl_context
    elif tls_data:
        # Only a passphrase was supplied: there is no key to apply it to.
        return ERR_CLIENT_CERT_KEY_REQUIRED

    try:
        session = async_get_clientsession(hass)
        async with session.get(
            f"{url}/version", timeout=ClientTimeout(total=5), **kwargs
        ) as response:
            return None if response.status == 200 else "cannot_connect"
    except aiohttp.ClientSSLError:
        # Includes certificate verification and handshake failures.
        return "ssl_error"
    except aiohttp.ServerDisconnectedError:
        # A TLS server that requires a client certificate typically drops the
        # connection after the handshake when none (or a wrong one) was sent.
        return "ssl_error" if url.lower().startswith("https://") else "cannot_connect"
    except (aiohttp.ClientError, TimeoutError):
        return "cannot_connect"
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception("Unexpected exception during Docker Socket Proxy validation")
        return "unknown"


class DockerProxyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Docker Socket Proxy."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step when the user adds the integration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Normalize URL by removing trailing slashes
            url = user_input[CONF_URL].rstrip("/")

            # Ensure the URL is unique to prevent duplicate integrations for the same host
            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()

            try:
                tls_data = await _async_collect_tls(self.hass, user_input)
            except DockerProxyTLSError as err:
                errors["base"] = err.reason
            else:
                if error := await _async_validate(self.hass, url, tls_data):
                    errors["base"] = error
                else:
                    # Success: Create entry and initialize options with defaults
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data={
                            CONF_NAME: user_input[CONF_NAME],
                            CONF_URL: url,
                            **tls_data,
                        },
                        options={
                            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                            CONF_GRACE_PERIOD_ENABLED: DEFAULT_GRACE_PERIOD_ENABLED,
                            CONF_GRACE_PERIOD_SECONDS: DEFAULT_GRACE_PERIOD_SECONDS,
                        },
                    )

        user_input = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(
                user_input.get(CONF_NAME, DEFAULT_NAME),
                user_input.get(CONF_URL, DEFAULT_URL),
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the URL and/or TLS material of an existing entry in place.

        The config entry is kept, so every entity (unique IDs are based on the
        entry ID) and its history survive. Only the entry data and unique ID
        change.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")

            # The unique ID is the URL, so moving to a URL that another entry
            # already uses would create a duplicate host.
            if any(
                other.entry_id != entry.entry_id and other.unique_id == url
                for other in self._async_current_entries(include_ignore=False)
            ):
                return self.async_abort(reason="already_configured")

            existing = {} if user_input.get(CONF_CLEAR_TLS) else dict(entry.data)
            try:
                tls_data = await _async_collect_tls(self.hass, user_input, existing)
            except DockerProxyTLSError as err:
                errors["base"] = err.reason
            else:
                if error := await _async_validate(self.hass, url, tls_data):
                    errors["base"] = error
                else:
                    # Replace the data wholesale so cleared TLS keys really go
                    # away. The entry's update listener reloads the integration.
                    self.hass.config_entries.async_update_entry(
                        entry,
                        unique_id=url,
                        data={
                            CONF_NAME: entry.data.get(CONF_NAME, entry.title),
                            CONF_URL: url,
                            **tls_data,
                        },
                    )
                    return self.async_abort(reason="reconfigure_successful")

        stored = [
            label
            for key, label in (
                (CONF_CA_CERT, "CA certificate"),
                (CONF_CLIENT_CERT, "client certificate"),
                (CONF_CLIENT_KEY, "client key"),
            )
            if entry.data.get(key)
        ]
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_reconfigure_schema(
                (user_input or {}).get(CONF_URL, entry.data[CONF_URL])
            ),
            description_placeholders={"stored": ", ".join(stored) or "none"},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DockerOptionsFlowHandler:
        """Return the options flow handler for this integration."""
        return DockerOptionsFlowHandler()


class DockerOptionsFlowHandler(OptionsFlow):
    """Handle management of Docker Socket Proxy options (Grace Period & Intervals)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the configuration options."""
        if user_input is not None:
            # Options were updated, save the data
            return self.async_create_entry(title="", data=user_input)

        # Retrieve current options, falling back to defaults if not yet set
        options = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    # Frequency of data polling
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
                    # Tombstone management for inactive/missing containers
                    vol.Required(
                        CONF_GRACE_PERIOD_ENABLED,
                        default=options.get(
                            CONF_GRACE_PERIOD_ENABLED, DEFAULT_GRACE_PERIOD_ENABLED
                        ),
                    ): bool,
                    vol.Required(
                        CONF_GRACE_PERIOD_SECONDS,
                        default=options.get(
                            CONF_GRACE_PERIOD_SECONDS, DEFAULT_GRACE_PERIOD_SECONDS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0)),
                }
            ),
        )
