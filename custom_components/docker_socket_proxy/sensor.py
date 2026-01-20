"""
Custom integration to integrate Docker Socket Proxy with Home Assistant.

For more details about this integration, please refer to
https://github.com/s-t-e-f-a-n/ha-docker-socket-proxy
"""
# Copyright 2026 Stefan Schmitt (s-t-e-f-a-n)
# Licensed under the Apache License, Version 2.0

"""Sensor platform for Docker Socket Proxy."""

from __future__ import annotations

from datetime import datetime
import logging
import time
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util, slugify

# Use constants for consistency
from .const import (
    ATTR_CONTAINERS,
    ATTR_DOCKER_HOSTNAME,
    ATTR_VERSION,
    CONF_GRACE_PERIOD_ENABLED,
    CONF_GRACE_PERIOD_SECONDS,
    DEFAULT_GRACE_PERIOD_ENABLED,
    DEFAULT_GRACE_PERIOD_SECONDS,
    DOMAIN,
)
from .coordinator import DockerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Docker sensors from a config entry."""
    coordinator: DockerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Initialize with the Host Status sensor
    entities: list[SensorEntity] = [DockerHostSensor(coordinator, entry)]

    # Track created container names and their last seen timestamp
    current_container_names: set[str] = set()
    last_seen: dict[str, float] = {}

    @callback
    def async_manage_entities() -> None:
        """Add new containers and cleanup orphaned entities with a grace period."""
        new_entities: list[SensorEntity] = []
        containers = coordinator.data.get(ATTR_CONTAINERS, [])

        # 1. Map current names from Docker API and update last seen
        now_ts = time.time()
        active_docker_names = {c.get("Names", [""])[0].lstrip("/") for c in containers}
        active_docker_names.discard("")  # Remove empty strings

        for name in active_docker_names:
            last_seen[name] = now_ts

        # 2. DISCOVERY: Add new containers found in the socket
        for name in active_docker_names:
            if name not in current_container_names:
                _LOGGER.debug("Discovering new Docker container: %s", name)
                new_entities.append(DockerContainerSensor(coordinator, name, entry))
                current_container_names.add(name)

        if new_entities:
            async_add_entities(new_entities)

        # 3. CLEANUP: Remove orphaned entities after grace period
        cleanup_enabled = entry.options.get(
            CONF_GRACE_PERIOD_ENABLED, DEFAULT_GRACE_PERIOD_ENABLED
        )
        if not cleanup_enabled:
            return

        grace_period = entry.options.get(
            CONF_GRACE_PERIOD_SECONDS, DEFAULT_GRACE_PERIOD_SECONDS
        )

        entity_reg = er.async_get(hass)
        registered_entities = er.async_entries_for_config_entry(
            entity_reg, entry.entry_id
        )

        # Determine valid unique_ids (active OR within grace period)
        valid_unique_ids = {f"{entry.entry_id}_host_status"}

        for name, ts in list(last_seen.items()):
            if name in active_docker_names or (now_ts - ts) < grace_period:
                valid_unique_ids.add(f"{entry.entry_id}_{name}")
            else:
                last_seen.pop(name)

        for entity_entry in registered_entities:
            if entity_entry.unique_id not in valid_unique_ids:
                _LOGGER.info(
                    "Grace period expired for Docker entity: %s, removing",
                    entity_entry.entity_id,
                )
                entity_reg.async_remove(entity_entry.entity_id)

                name_in_id = entity_entry.unique_id.replace(f"{entry.entry_id}_", "")
                current_container_names.discard(name_in_id)

    # Initial run to setup existing containers
    async_manage_entities()

    # Link management to coordinator updates
    entry.async_on_unload(coordinator.async_add_listener(async_manage_entities))

    # Add the initial batch (Host sensor and initial containers)
    async_add_entities(entities)


class DockerHostSensor(CoordinatorEntity[DockerDataUpdateCoordinator], SensorEntity):
    """Sensor representing the overall status of a Docker Host."""

    _attr_icon = "mdi:server-network"
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DockerDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the host sensor."""
        super().__init__(coordinator)
        self._attr_name = "Host Status"
        self._attr_unique_id = f"{entry.entry_id}_host_status"
        self._host_name = entry.title
        instance_slug = slugify(entry.title)
        self.entity_id = f"sensor.dockersocketproxy_{instance_slug}_host_status"

    @property
    def native_value(self) -> str:
        """Return the ratio of running containers to total containers."""
        containers = self.coordinator.data.get(ATTR_CONTAINERS, [])
        total = len(containers)
        running = sum(1 for c in containers if c.get("State") == "running")
        return f"{running}/{total} running"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed host metadata."""
        v_info = self.coordinator.data.get(ATTR_VERSION, {})
        return {
            "docker_hostname": self.coordinator.data.get(
                ATTR_DOCKER_HOSTNAME, "unknown"
            ),
            "instance_name": self._host_name,
            "platform_name": v_info.get("Platform", {}).get("Name", "unknown"),
            "version": v_info.get("Version", "unknown"),
            "api_version": v_info.get("ApiVersion", "unknown"),
            "os": v_info.get("Os", "unknown"),
            "arch": v_info.get("Arch", "unknown"),
            "kernel": v_info.get("KernelVersion", "unknown"),
            "last_update": datetime.now().isoformat(),
        }


class DockerContainerSensor(
    CoordinatorEntity[DockerDataUpdateCoordinator], SensorEntity
):
    """Sensor representing an individual Docker container."""

    def __init__(
        self,
        coordinator: DockerDataUpdateCoordinator,
        container_name: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the container sensor."""
        super().__init__(coordinator)
        self._container_name = container_name
        self._host_name = entry.title

        self._attr_name = f"{self._host_name} {self._container_name}"
        self._attr_unique_id = f"{entry.entry_id}_{self._container_name}"

        self.entity_id = f"sensor.dockersocketproxy_{slugify(self._host_name)}_{slugify(self._container_name)}"

    def _get_container_data(self) -> dict[str, Any] | None:
        """Find this container's data by name in the current dataset."""
        return next(
            (
                c
                for c in self.coordinator.data.get(ATTR_CONTAINERS, [])
                if c.get("Names", [""])[0].lstrip("/") == self._container_name
            ),
            None,
        )

    @property
    def native_value(self) -> str:
        """Return the current state of the container."""
        if data := self._get_container_data():
            return str(data.get("State", "unavailable"))
        return "unavailable"

    @property
    def icon(self) -> str:
        """Return icon based on container state."""
        if (data := self._get_container_data()) and data.get("State") == "running":
            return "mdi:docker"
        return "mdi:package-variant-closed"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all enriched container attributes including ports."""
        data = self._get_container_data()
        if not data:
            return {}

        # Extract and format unique Port Mappings (e.g., 8080:80/tcp)
        # Using a set to automatically filter duplicate IPv4/IPv6 entries
        port_mappings_set: set[str] = set()
        raw_ports = data.get("Ports", [])

        for port in raw_ports:
            p_type = port.get("Type", "tcp")
            private = port.get("PrivatePort")
            public = port.get("PublicPort")

            if public:
                # Result: "8080:80/tcp"
                port_mappings_set.add(f"{public}:{private}/{p_type}")
            elif private:
                # Result: "80/tcp"
                port_mappings_set.add(f"{private}/{p_type}")

        # sorted() returns a new list from the set directly
        port_mappings = sorted(port_mappings_set)

        # Handle Service URLs for the display name link
        urls: list[dict[str, Any]] = data.get("ServiceUrls", [])
        if urls:
            primary_url = urls[0].get("url")
            display_name = (
                f"<a href='{primary_url}' target='_blank' "
                "style='color:var(--primary-color);text-decoration:none;font-weight:bold;'>"
                f"{self._container_name}</a>"
            )
        else:
            display_name = self._container_name

        created_iso = "unknown"
        if raw_created := data.get("Created"):
            try:
                created_iso = datetime.fromtimestamp(float(raw_created)).isoformat()
            except (ValueError, TypeError):
                created_iso = "unknown"

        return {
            "host_name": self._host_name,
            "container_name": self._container_name,
            "display_name": display_name,
            "project": data.get("Project"),
            "state": data.get("State"),
            "uptime": data.get("uptime"),
            "health": data.get("health"),
            "created_at": created_iso,
            "image": data.get("Image"),
            "network_settings": data.get("NetworkSettings"),
            "port_mappings": port_mappings,
            "last_update": dt_util.now().isoformat(),
        }
