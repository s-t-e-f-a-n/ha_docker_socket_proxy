# Docker Socket Proxy

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant integration that monitors Docker containers through a Docker socket proxy, providing real-time status, health checks, and service URLs for your containerized applications.

## Features

- **Real-time Monitoring**: Polls Docker API every 30 seconds for live container data
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
3. Enter this repository URL: `https://github.com/s-t-e-f-a-n/ha-docker-socket-proxy`
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
```

### Options

After setup, you can configure:

- **Enable Grace Period**: Whether to automatically remove sensors for stopped containers
- **Grace Period (seconds)**: How long to wait before removing orphaned sensors (default: 1 week)

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

### Flex Table Card Example

For a comprehensive table view of all containers, use the [flex-table-card](https://github.com/custom-cards/flex-table-card):

```yaml
type: custom:flex-table-card
title: Docker Containers
entities:
  include: sensor.dockersocketproxy_*
columns:
  - name: Container
    data: attributes
    modify: x.display_name
    align: left
  - name: State
    data: state
    align: center
    modify: |
      if (x === 'running') return '🟢 Running';
      if (x === 'exited') return '🔴 Stopped';
      if (x === 'paused') return '🟡 Paused';
      return '⚪ ' + x;
  - name: Health
    data: attributes
    modify: x.health
    align: center
    modify: |
      if (x === 'healthy') return '✅ Healthy';
      if (x === 'unhealthy') return '❌ Unhealthy';
      return '❓ Unknown';
  - name: Uptime
    data: attributes
    modify: x.uptime
    align: center
  - name: Project
    data: attributes
    modify: x.project
    align: left
  - name: Ports
    data: attributes
    modify: x.port_mappings.join(', ')
    align: left
sort_by: attributes.container_name
```

This creates a sortable table showing container status with icons, health indicators, and port information.

### Sample Data Table

| Container | State      | Health     | Uptime  | Project  | Ports                  |
|-----------|------------|------------|---------|----------|-----------------------|
| nginx     | 🟢 Running | ✅ Healthy | 2 hours | web      | 80:80/tcp, 443:443/tcp|
| postgres  | 🟢 Running | ❓ Unknown  | 1 week  | database | 5432:5432/tcp         |
| redis     | 🔴 Stopped | ❓ Unknown  | -       | cache    | 6379:6379/tcp         |

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

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- [GitHub Issues](https://github.com/s-t-e-f-a-n/ha-docker-socket-proxy/issues) for bug reports and feature requests
- [Home Assistant Community](https://community.home-assistant.io) for general questions
