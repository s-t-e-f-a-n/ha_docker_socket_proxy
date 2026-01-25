"""Custom integration to integrate Docker Socket Proxy with Home Assistant.

For more details about this integration, please refer to
https://github.com/s-t-e-f-a-n/ha_docker_socket_proxy
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import BLUEPRINT_FILENAME, DOMAIN
from .coordinator import DockerDataUpdateCoordinator

# Define the platforms that this integration supports
PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Docker Socket Proxy from a config entry."""

    # Deploy or update the blueprint before setting up platforms
    await async_install_blueprint(hass)

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

    # This listener detects when "Submit" is clicked in the options menu
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_install_blueprint(hass: HomeAssistant) -> None:
    """Copy the blueprint from the integration folder to the HA blueprints folder."""

    # Source path using pathlib for better readability and robustness
    source_file = Path(
        hass.config.path(
            "custom_components", DOMAIN, "blueprints", "automation", BLUEPRINT_FILENAME
        )
    )

    # Target path in the global blueprints directory
    dest_dir = Path(hass.config.path("blueprints", "automation", DOMAIN))
    dest_file = dest_dir / BLUEPRINT_FILENAME

    def sync_blueprint() -> None:
        """Perform blocking file I/O operations."""
        try:
            if not source_file.exists():
                _LOGGER.warning("Blueprint source file not found at %s", source_file)
                return

            # Create directory tree if missing
            dest_dir.mkdir(parents=True, exist_ok=True)

            # Copy the file while preserving metadata
            shutil.copy2(source_file, dest_file)
            _LOGGER.debug("Blueprint successfully synchronized to %s", dest_file)

        # Catch specific I/O related errors instead of a blind Exception
        except (OSError, shutil.Error) as err:
            _LOGGER.error("FileSystem error while syncing blueprint: %s", err)

    # Use the executor to avoid blocking the HA event loop
    await hass.async_add_executor_job(sync_blueprint)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    # Unload all platforms associated with this entry
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Remove the coordinator from hass.data to free up memory
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
