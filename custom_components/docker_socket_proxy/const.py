"""Custom integration to integrate Docker Socket Proxy with Home Assistant.

For more details about this integration, please refer to
https://github.com/s-t-e-f-a-n/ha_docker_socket_proxy

Constants for the Docker Socket Proxy integration.
"""

from typing import Final

# Domain
DOMAIN: Final = "docker_socket_proxy"

# Defaults
DEFAULT_NAME: Final = "Docker Host"
DEFAULT_URL: Final = "http://192.168.1.100:2375"
DEFAULT_SCAN_INTERVAL: Final = 30               # in seconds
DEFAULT_GRACE_PERIOD_SECONDS: Final = 604800    # 7 days in seconds
DEFAULT_GRACE_PERIOD_ENABLED: Final = True

# User Configuration Keys
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_GRACE_PERIOD_ENABLED: Final = "grace_period_enabled"
CONF_GRACE_PERIOD_SECONDS: Final = "grace_period_seconds"

# Coordinator Keys from Docker API
ATTR_CONTAINERS: Final = "containers"
ATTR_VERSION: Final = "version"
ATTR_DOCKER_HOSTNAME: Final = "docker_hostname"

# Constant for the blueprint filename to ensure consistency
BLUEPRINT_FILENAME = "docker_proxy_health_alert.yaml"
