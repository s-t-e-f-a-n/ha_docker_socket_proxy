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
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME, CONF_URL
from homeassistant.core import callback

from .const import (
    CONF_GRACE_PERIOD_ENABLED,
    CONF_GRACE_PERIOD_SECONDS,
    DEFAULT_GRACE_PERIOD_ENABLED,
    DEFAULT_GRACE_PERIOD_SECONDS,
    DEFAULT_NAME,
    DEFAULT_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_URL, default=DEFAULT_URL): str,
    }
)


class DockerProxyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Docker Socket Proxy."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step when the user adds the integration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")

            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()

            try:
                timeout = ClientTimeout(total=5)

                async with (
                    aiohttp.ClientSession() as session,
                    session.get(f"{url}/version", timeout=timeout) as response,
                ):
                    if response.status != 200:
                        errors["base"] = "cannot_connect"
                    else:
                        return self.async_create_entry(
                            title=user_input[CONF_NAME],
                            data={
                                CONF_NAME: user_input[CONF_NAME],
                                CONF_URL: url,
                            },
                        )
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during Docker Proxy validation")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DockerOptionsFlowHandler:
        """Get the options flow for this handler."""
        # Entferne das config_entry Argument hier:
        return DockerOptionsFlowHandler()


class DockerOptionsFlowHandler(OptionsFlow):
    """Handle Docker Socket Proxy options."""

    # Wir benötigen kein __init__, da die Basisklasse alles regelt.

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Die Property self.config_entry ist automatisch verfügbar
        options = self.config_entry.options

        enabled = options.get(CONF_GRACE_PERIOD_ENABLED, DEFAULT_GRACE_PERIOD_ENABLED)
        seconds = options.get(CONF_GRACE_PERIOD_SECONDS, DEFAULT_GRACE_PERIOD_SECONDS)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GRACE_PERIOD_ENABLED, default=enabled): bool,
                    vol.Required(CONF_GRACE_PERIOD_SECONDS, default=seconds): vol.All(
                        vol.Coerce(int), vol.Range(min=0)
                    ),
                }
            ),
        )
