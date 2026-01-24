"""Custom integration to integrate Docker Socket Proxy with Home Assistant.

For more details about this integration, please refer to
https://github.com/s-t-e-f-a-n/ha_docker_socket_proxy

DataUpdateCoordinator for Docker Socket Proxy.

"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import ClientResponse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_CONTAINERS,
    ATTR_DOCKER_HOSTNAME,
    ATTR_VERSION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class DockerDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Docker data from the proxy."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.url = entry.data[CONF_URL].rstrip("/")
        self.host_name = entry.title

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({self.host_name})",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    def _validate_result(self, result: Any) -> ClientResponse:
        """Throw exception if result is a BaseException."""
        if isinstance(result, BaseException):
            raise result
        return result

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch container and host data from Docker Proxy in parallel."""
        session = async_get_clientsession(self.hass)

        try:
            async with asyncio.timeout(10):
                results = await asyncio.gather(
                    session.get(f"{self.url}/containers/json?all=1"),
                    session.get(f"{self.url}/version"),
                    return_exceptions=True,
                )

                container_res = self._validate_result(results[0])
                containers = await self._parse_container_response(container_res)

                version_data: dict[str, Any] = {}
                try:
                    version_res = self._validate_result(results[1])
                    version_data = await self._parse_version_response(version_res)
                except (aiohttp.ClientError, TimeoutError) as err:
                    _LOGGER.warning(
                        "[%s] Optional version info could not be fetched: %s",
                        self.host_name,
                        err,
                    )

                parsed_url = urlparse(self.url)
                docker_hostname = parsed_url.hostname or self.url

                return {
                    ATTR_CONTAINERS: containers,
                    ATTR_VERSION: version_data,
                    ATTR_DOCKER_HOSTNAME: docker_hostname,
                }

        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error(
                "[%s] Critical communication error with Docker Proxy at %s: %s",
                self.host_name,
                self.url,
                err,
            )
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def _parse_container_response(
        self, response: ClientResponse
    ) -> list[dict[str, Any]]:
        """Parse containers and enrich with Project, Health and Port logic."""
        if response.status != 200:
            return []

        raw_data: list[dict[str, Any]] = await response.json()
        filtered_data: list[dict[str, Any]] = []

        # Extract Host IP from the Proxy URL
        host_ip = self.url.split("//")[-1].split(":")[0]
        known_drivers = ["bridge", "host", "macvlan", "overlay", "ipvlan", "none"]

        for container in raw_data:
            labels = container.get("Labels", {})
            status_str = container.get("Status", "")

            # Health check logic
            health_value = "unknown"
            if "(" in status_str and ")" in status_str:
                raw_health = status_str.split("(")[1].split(")")[0].lower()
                if "unhealthy" in raw_health:
                    health_value = "unhealthy"
                elif "healthy" in raw_health:
                    health_value = "healthy"

            # Clean uptime string
            uptime_value = status_str.split(" (")[0].replace("Up ", "").strip()

            # Port logic
            active_ports_raw = container.get("Ports", [])
            port_bindings = {
                str(p.get("PublicPort")): p.get("IP", "0.0.0.0")
                for p in active_ports_raw
                if p.get("PublicPort") is not None
            }

            # URL Generation based on label 'ha.web_port'
            web_ports_label = labels.get("ha.web_port", "")
            service_urls = []

            if web_ports_label:
                entries = [e.strip() for e in web_ports_label.split(",") if e.strip()]
                for entry in entries:
                    parts = entry.split(":")
                    port = parts[0]
                    protocol = parts[1] if len(parts) > 1 else "http"

                    # If port is mapped to a specific IP (like 127.0.0.1), use it
                    bind_ip = port_bindings.get(port, "0.0.0.0")
                    final_host = host_ip if bind_ip != "127.0.0.1" else "127.0.0.1"

                    service_urls.append(
                        {
                            "url": f"{protocol}://{final_host}:{port}",
                            "is_local": bind_ip == "127.0.0.1",
                        }
                    )

            filtered_data.append(
                {
                    "Id": container.get("Id"),
                    "Names": container.get("Names"),
                    "Image": container.get("Image"),
                    "State": container.get("State"),
                    "Status": status_str,
                    "uptime": uptime_value,
                    "health": health_value,
                    "Project": labels.get("com.docker.compose.project", "Standalone"),
                    "ServiceUrls": service_urls,
                    "Created": container.get("Created"),
                    "Ports": active_ports_raw,
                    "NetworkSettings": {
                        "Networks": {
                            net_name: {
                                "IPAddress": net_data.get("IPAddress"),
                                "MacAddress": net_data.get("MacAddress"),
                                "NetworkType": net_name
                                if net_name in known_drivers
                                else "bridge",
                            }
                            for net_name, net_data in container.get(
                                "NetworkSettings", {}
                            )
                            .get("Networks", {})
                            .items()
                        }
                    },
                }
            )

        return filtered_data

    async def _parse_version_response(self, response: ClientResponse) -> dict[str, Any]:
        """Parse version response for host info."""
        if response.status != 200:
            return {}
        raw_version = await response.json()
        return {
            "Platform": raw_version.get("Platform", {}),
            "Version": raw_version.get("Version"),
            "ApiVersion": raw_version.get("ApiVersion"),
            "Os": raw_version.get("Os"),
            "Arch": raw_version.get("Arch"),
            "KernelVersion": raw_version.get("KernelVersion"),
        }
