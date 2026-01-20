# Docker Socket Proxy Integration - AI Coding Guidelines

## Architecture Overview
This is a Home Assistant custom integration that monitors Docker containers via a Docker socket proxy API. It uses the coordinator pattern for data fetching and dynamic sensor entities.

**Key Components:**
- `coordinator.py`: Fetches data from `/containers/json` and `/version` endpoints in parallel
- `sensor.py`: Creates host sensor (running/total ratio) and per-container sensors with detailed attributes
- `config_flow.py`: Handles setup with URL validation via `/version` endpoint
- Dynamic entity management with grace period cleanup for orphaned containers

## Data Flow
1. Coordinator polls Docker API every 30s, parsing containers with health status, uptime, ports, and service URLs from `ha.web_port` labels
2. Sensors update state and attributes; containers auto-discover via `async_manage_entities` callback
3. Unique IDs use `{entry.entry_id}_{container_name}` pattern for multi-host support

## Key Patterns
- **Entity Discovery**: Containers added dynamically when found; removed after grace period (default 1 week)
- **Service URLs**: Generated from `ha.web_port` label (e.g., `8080:http,8443:https`) with IP binding logic
- **Health Parsing**: Extracts from status string (e.g., "Up 2 hours (healthy)") 
- **Port Mappings**: Deduplicates IPv4/IPv6, formats as "8080:80/tcp"
- **Network Settings**: Enriches with known drivers (bridge, host, overlay, etc.)

## Configuration
- Supports multiple Docker hosts via separate config entries
- Options flow for grace period settings (enabled/disabled, seconds)
- URL validation in config flow ensures proxy connectivity

## Development Notes
- No external dependencies; uses aiohttp for API calls
- Logging includes host name prefixes for multi-instance debugging
- Entity registry cleanup respects grace period to avoid flapping
- Container names stripped of leading `/` for consistency

## Testing
Run Home Assistant with the integration loaded; verify sensors appear for containers and update on state changes.