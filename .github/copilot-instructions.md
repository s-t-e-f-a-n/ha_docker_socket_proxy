# Docker Socket Proxy Integration - AI Coding Guidelines

## Architecture Overview
This is a Home Assistant custom integration that monitors Docker containers via a Docker socket proxy API. It uses the coordinator pattern for data fetching and dynamic sensor entities.

**Key Components:**
- `coordinator.py`: Fetches data from `/version` and `/containers/json` sequentially; passes the optional SSL context via `ssl=` and logs each distinct failure reason once
- `tls.py`: Builds an `ssl.SSLContext` from PEM text in the config entry (optional private CA, mTLS client cert/key/passphrase). Server verification is always on; there is intentionally no skip-verify option
- `diagnostics.py`: Redacts keys, passphrases, certificate PEMs and the proxy host
- `sensor.py`: Creates host sensor (running/total ratio) and per-container sensors with detailed attributes
- `config_flow.py`: Setup and in-place Reconfigure (URL + TLS file uploads) with validation via `/version`; reconfigure keeps the config entry so entities and history survive, and updates the entry's unique ID (the URL)
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
- TLS fields are optional; entries saved before TLS support (no TLS keys) must keep working unchanged

## Development Notes
- No external dependencies; uses aiohttp for API calls
- Logging includes host name prefixes for multi-instance debugging
- Entity registry cleanup respects grace period to avoid flapping
- Container names stripped of leading `/` for consistency

## Testing
`pip install -r requirements_test.txt && pytest` (Python 3.13+). Tests live in `tests/` and use `pytest-homeassistant-custom-component`; `tests/pki.py` generates throwaway certificates in memory and `test_integration.py` talks to a real local mTLS server. Also verify manually that sensors appear for containers and update on state changes.