"""
Custom integration to integrate Docker Socket Proxy with Home Assistant.

For more details about this integration, please refer to
https://github.com/s-t-e-f-a-n/ha-docker-socket-proxy
"""
# Copyright 2026 Stefan Schmitt (s-t-e-f-a-n)
# Licensed under the Apache License, Version 2.0

"""The Docker Socket Proxy integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import DockerDataUpdateCoordinator

# Define the platforms that this integration supports
PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Docker Socket Proxy from a config entry."""

    # Initialize the coordinator with the full entry object
    # This allows the coordinator to access entry.title and entry.data["url"]
    coordinator = DockerDataUpdateCoordinator(hass, entry)

    # Trigger the first refresh to ensure we have data before creating entities
    await coordinator.async_config_entry_first_refresh()

    # Store the coordinator instance using the entry_id to support multiple hosts
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward the setup to the defined platforms (sensor.py)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    # Unload all platforms associated with this entry
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Remove the coordinator from hass.data to free up memory
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
