# HA Docker Socket Proxy

![HA Docker Socket Proxy Logo](assets/logo.png)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![License](https://img.shields.io/github/license/s-t-e-f-a-n/ha_docker_socket_proxy)
![Version](https://img.shields.io/github/v/release/s-t-e-f-a-n/ha_docker_socket_proxy?style=flat-square)
[![HACS Validation](https://github.com/s-t-e-f-a-n/ha_docker_socket_proxy/actions/workflows/hacs.yml/badge.svg)](https://github.com/s-t-e-f-a-n/ha_docker_socket_proxy/actions/workflows/hacs.yml)

A Home Assistant integration that monitors Docker containers through a Docker socket proxy ([Tecnativa's docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy)), providing real-time status, health checks, and service URLs for your containerized applications.

## Features

- **Real-time Monitoring**: Polls Docker Socket Proxy API every 30 seconds (configurable) for live container data
- **Auto-Discovery**: Automatically creates sensors for new containers as they're deployed
- **Health Checks**: Parses Docker health status from container status strings
- **Service URLs**: Generates web URLs from `ha.web_port` container labels
- **Multi-Host Support**: Monitor multiple Docker hosts with separate integrations
- **Grace Period Cleanup**: Configurable cleanup of orphaned container sensors
- **Rich Attributes**: Detailed metadata including ports, networks, uptime, and project info

## Installation

### Via HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance
2. In HACS, go to **Integrations** → **+** → **Add Custom Repository**
3. Enter this repository URL: `https://github.com/s-t-e-f-a-n/ha_docker_socket_proxy`
4. Select **Integration** as the category
5. Click **Add** and then **Install**
6. Restart Home Assistant
7. Add the integration through **Settings** → **Devices & Services** → **+ Add Integration**

### Manual Installation

1. Download the `custom_components/docker_socket_proxy` folder from this repository
2. Copy it to your Home Assistant `custom_components` directory
3. Restart Home Assistant
4. Add the integration through the UI

## Configuration

### Basic Setup

1. In Home Assistant, go to **Settings** → **Devices & Services** → **+ Add Integration**
2. Search for "Docker Socket Proxy" and select it
3. Enter:
   - **Instance Name**: A friendly name for this Docker host (e.g., "NAS", "Server")
   - **Proxy URL**: The URL of your Docker socket proxy (e.g., `http://192.168.1.100:2375`)

### Configuration & Options

The integration can be fine-tuned after the initial setup. Go to **Settings** → **Devices & Services** → **Docker Socket Proxy** and click on **Configure**.

| Option | Description | Default |
| :--- | :--- | :--- |
| **Scan Interval** | How often (in seconds) the integration polls the Docker API. | `30` |
| **Enable Grace Period** | If enabled, sensors for stopped containers are not removed immediately. | `true` |
| **Grace Period** | The time (in seconds) to wait before an orphaned sensor is removed. | `604800` (1 week) |

> [!TIP]
> Changes to the **Scan Interval** are applied immediately without requiring a restart of Home Assistant.

### Docker Socket Proxy Setup

This integration requires a Docker socket proxy for security. You can use [Tecnativa's docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy):

```yaml
version: '3.8'
services:
  dockerproxy:
    image: tecnativa/docker-socket-proxy:latest
    container_name: docker-socket-proxy
    environment:
      - CONTAINERS=1
      - VERSION=1
    ports:
      - "2375:2375"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    restart: unless-stopped
    healthcheck:
      test: wget --spider http://localhost:2375/version || exit 1
      interval: "29s"
      timeout: "5s"
      retries: 3
      start_period: "21s"
```

## Usage

The integration creates sensors for each Docker host and container:

### Host Sensors

- **Host Status**: Shows "X/Y running" where X is running containers and Y is total containers
- Attributes include Docker version, platform, OS, architecture, and hostname

### Container Sensors

- **State**: Current container state (running, exited, paused, etc.)
- **Attributes**:
  - Container name, image, project (from compose labels)
  - Uptime, health status
  - Port mappings, network settings
  - Service URLs (generated from `ha.web_port` labels)

### Container Labels

Add labels to your containers for enhanced functionality:

```yaml
# Generate service URLs
labels:
  - "ha.web_port=8080:http"  # Single port
  - "ha.web_port=8080:http,8443:https"  # Multiple ports
  - "com.docker.compose.project=myproject"  # Project grouping
```

## Dashboard Examples

### Simple Container Card

```yaml
type: entities
entities:
  - entity: sensor.dockersocketproxy_nas_host_status
  - entity: sensor.dockersocketproxy_nas_nginx
  - entity: sensor.dockersocketproxy_nas_postgres
title: Docker Containers
```

### Combined Vertical, Horizontal and Flex Table Card Example

For an extensive table view of all containers, use the [flex-table-card](https://github.com/custom-cards/flex-table-card):

```yaml
type: vertical-stack
cards:
  - type: horizontal-stack
    cards:
      - type: entities
        title: 🖥️ Host Machine
        show_header_toggle: false
        entities:
          - type: attribute
            entity: sensor.dockersocketproxy_my_docker_host_host_status
            attribute: docker_hostname
            name: Docker Hostname
            icon: mdi:dns-outline
          - type: attribute
            entity: sensor.dockersocketproxy_my_docker_host_host_status
            attribute: os
            name: Operating System
            icon: mdi:linux
          - type: attribute
            entity: sensor.dockersocketproxy_my_docker_host_host_status
            attribute: arch
            name: Architecture
            icon: mdi:cpu-64-bit
          - type: attribute
            entity: sensor.dockersocketproxy_my_docker_host_host_status
            attribute: kernel
            name: Kernel Version
            icon: mdi:identifier
      - type: entities
        title: 🐳 Docker Engine
        show_header_toggle: false
        entities:
          - entity: sensor.dockersocketproxy_my_docker_host_host_status
            name: Running/Total
            icon: mdi:docker
          - type: attribute
            entity: sensor.dockersocketproxy_my_docker_host_host_status
            attribute: version
            name: Engine Version
            icon: mdi:engine-outline
          - type: attribute
            entity: sensor.dockersocketproxy_my_docker_host_host_status
            attribute: api_version
            name: API Version
            icon: mdi:api
          - type: attribute
            entity: sensor.dockersocketproxy_my_docker_host_host_status
            attribute: instance_name
            name: Instance Name
            icon: mdi:tag-outline
  - type: custom:flex-table-card
    title: Docker Containers
    entities:
      include: sensor.dockersocketproxy_my_docker_host_*
      exclude: sensor.dockersocketproxy_my_docker_host_host_status
    strict: false
    css:
      table+: "width: 100%; border-collapse: collapse;"
      th+: "white-space: nowrap; padding: 8px; text-align: left;"
      td+: "padding: 8px; vertical-align: middle;"
    columns:
      - name: St.
        data: state
        modify: "x === 'running' ? '🟢' : '🔴'"
      - name: H.
        data: health
        modify: "x === 'healthy' ? '🟢' : (x === 'unhealthy' ? '🔴' : '🟡')"
      - name: Project
        data: project
        modify: x || 'Standalone'
      - name: Container
        data: display_name
      - name: Image
        data: image
        modify: x.split('@')[0]
      - name: IP Address
        data: network_settings
        modify: "x && x.Networks ? Object.values(x.Networks)[0]?.IPAddress || '-' : '-'"
      - name: MAC Address
        data: network_settings
        modify: "x && x.Networks ? Object.values(x.Networks)[0]?.MacAddress || '-' : '-'"
      - name: Network
        data: network_settings
        modify: "x && x.Networks ? Object.values(x.Networks)[0]?.NetworkType || '-' : '-'"
      - name: Ports (Ext:Int)
        data: port_mappings
        modify: "x && x.length > 0 ? x.join('<br>') : '-'"
      - name: Uptime
        data: uptime
        modify: "x === 'unknown' || !x ? '-' : x"
      - name: Created
        data: created_at
        modify: "x && x.includes('T') ? x.split('T')[0] : '-'"
      - name: Updated
        data: last_update
        modify: "x ? new Date(x).toLocaleTimeString('de-DE', {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '-'"
    sort_by: project+
grid_options:
  columns: full
  rows: auto
```

This creates a sortable table showing container status with icons, health indicators, and port information.

#### 🖥️ Host Machine
| Property | Value |
| :--- | :--- |
| **Docker Hostname** | `my-docker-srv` |
| **Operating System** | `Ubuntu 22.04 LTS` |
| **Architecture** | `x86_64` |
| **Kernel Version** | `5.15.0-101-generic` |

#### 🐳 Docker Engine
| Property | Value |
| :--- | :--- |
| **Running/Total** | `2/3 running` |
| **Engine Version** | `24.0.7` |
| **API Version** | `1.43` |
| **Instance Name** | `My Docker Host` |

| St. | H. | Project | Container | Image | IP Address | Ports (Ext:Int) | Uptime | Created | Updated |
|:---:|:---:|:---|:---|:---|:---|:---|:---|:---|:---|
| 🟢 | 🟢 | `web-stack` | [**nginx**](http://your-ip) | `nginx:latest` | `172.18.0.10` | `80:80/tcp`<br>`443:443/tcp` | `2 hours` | `2026-01-15` | `22:26:05` |
| 🟢 | 🟡 | `database` | **postgres** | `postgres:15` | `172.18.0.5` | `5432:5432/tcp` | `1 week` | `2026-01-01` | `22:26:05` |
| 🔴 | 🔴 | `monitoring` | **prometheus** | `prom/prometheus` | `172.19.0.4` | `9090:9090/tcp` | `-` | `2026-01-10` | `22:26:05` |

### Advanced Dashboard with Groups

Group containers by project using card-mod:

```yaml
type: entities
title: Web Services
entities:
  - entity: sensor.dockersocketproxy_nas_nginx
    name: Nginx Web Server
  - entity: sensor.dockersocketproxy_nas_traefik
    name: Traefik Reverse Proxy
card_mod:
  style: |
    ha-card {
      --ha-card-background: var(--card-background-color);
    }
```

## Troubleshooting

### Common Issues

#### Failed to connect to Docker Proxy

- Verify the proxy URL is correct and accessible
- Check that the docker-socket-proxy container is running
- Ensure firewall allows connections to the proxy port

#### Missing containers

- Containers must be running for auto-discovery
- Check proxy logs for API access issues
- Verify CONTAINERS=1 environment variable in proxy

#### Sensors not updating

- Check Home Assistant logs for errors
- Verify network connectivity to proxy
- Restart the integration if needed

### Debug Logging

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.docker_socket_proxy: debug
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is licensed under the Apache License, Version 2.0 - see the [LICENSE](LICENSE) file for details.

## Support

- [GitHub Issues](https://github.com/s-t-e-f-a-n/ha_docker_socket_proxy/issues) for bug reports and feature requests
- [Home Assistant Community](https://community.home-assistant.io) for general questions
