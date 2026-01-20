"""
Custom integration to integrate Docker Socket Proxy with Home Assistant.

For more details about this integration, please refer to
https://github.com/s-t-e-f-a-n/ha-docker-socket-proxy
"""
# Copyright 2026 Stefan Schmitt (s-t-e-f-a-n)
# Licensed under the Apache License, Version 2.0

"""Constants for the Docker Socket Proxy integration."""

from typing import Final

# Domain
DOMAIN: Final = "docker_socket_proxy"

# Defaults
DEFAULT_NAME: Final = "Docker Host"
DEFAULT_URL: Final = "http://192.168.1.100:2375"
DEFAULT_SCAN_INTERVAL: Final = 30

# Coordinator Keys
ATTR_CONTAINERS: Final = "containers"
ATTR_VERSION: Final = "version"
ATTR_DOCKER_HOSTNAME: Final = "docker_hostname"

# Grace Period Configuration
CONF_GRACE_PERIOD_ENABLED: Final = "grace_period_enabled"
CONF_GRACE_PERIOD_SECONDS: Final = "grace_period_seconds"

# Default: 1 week (604800 seconds)
DEFAULT_GRACE_PERIOD_SECONDS: Final = 604800
DEFAULT_GRACE_PERIOD_ENABLED: Final = True
