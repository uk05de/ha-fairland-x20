# CLAUDE.md

## Project
- Home Assistant Addon for Fairland X20 pool heat pump
- Repo: uk05de/ha-fairland-x20
- Replaces the old ha-modbusproxy addon (generic modbus proxy with filters)

## Architecture
- Python addon using pymodbus (Modbus TCP) + paho-mqtt (MQTT Discovery)
- No proxy layer — reads registers directly from heat pump
- Publishes to local MQTT broker with MQTT Discovery
- Config via /data/options.json (HA addon options)
- Startup: run.sh -> main.py

## Key Files
- fairland-x20/src/fairland_x20.py — Modbus client, register definitions, state dataclass
- fairland-x20/src/mqtt_discovery.py — MQTT Discovery configs, state publishing, polling switch
- fairland-x20/src/main.py — Main loop, reachability check, command queue, pool-running safety
- fairland-x20/src/ha_api.py — HA Supervisor REST client (read pool pump state for safety)
- fairland-x20/config.yaml — HA addon config (version, options schema)
- fairland-x20/run.sh — Reads /data/options.json, activates venv, starts main.py

## Hardware
- Fairland X20 pool heat pump with non-standard Modbus TCP behavior
- Sends unsolicited data on queries — pymodbus handles this via transaction ID matching
- Slave ID: 1 (configurable)
- 200ms delay between Modbus requests required

## Modbus Registers
- FC1 Coil 0: Running status (bool)
- FC2 Discrete Input 16: Error status, 51: E3 error
- FC3 Holding Registers 0-3: HVAC mode (0=Auto,1=Heat,2=Cool), Fan mode (0=Low,1=Med,2=High), _, Target temp
- FC4 Input Registers 0-5: Compressor %, _, PFC Volt, Inlet temp, Outlet temp, Ambient temp
- FC4 Input Register 11: Compressor current
- FC5 Write Coil 0: Power on/off
- Temperature formula: raw * 0.5 - 30

## pymodbus Compatibility
- pymodbus 3.12+ uses `device_id` parameter (not `slave` or `unit`)
- Auto-detection via inspect.signature at startup
- Uses **self._slave_kwargs pattern to support all versions

## Features
- Auto-detects heat pump reachability (TCP check every 60s when offline)
- "Abfrage aktiv" MQTT switch to disable polling (Wintermodus)
- Polling switch state retained via MQTT (survives restarts)
- Auto-exit after 10 consecutive errors for watchdog restart
- Climate entity with HVAC mode, fan mode, target temperature control
- Heizautomatik switch: passive user-intent flag (see below)
- Pool-running safety: power-on is gated on the pool pump being on

## Heizautomatik & Pool Coupling

The WP-addon does *not* drive the coupling itself. Instead:

- **`switch.fairland_x20_heizautomatik`** is a passive retained MQTT flag.
  ha-pool-pump reads it to decide whether to switch the WP on/off when
  starting/stopping a pool program. The addon doesn't act on this switch.
- ha-pool-pump is the master: it powers the WP on when starting an allowed
  program, and powers the WP off (then waits for residual-flow delay
  before stopping itself) when ending a program.
- Prerun is handled by the WP hardware (soft-start with internal flow
  check). Postrun is handled by ha-pool-pump (keeps running after WP-off).

### Safety (defense-in-depth, requires `homeassistant_api: true`)
- `pool_status_entity` (default `binary_sensor.pool_pumpe_status`) is
  consulted via the HA Supervisor REST API whenever:
  - a `power=ON` command arrives → rejected if the pool isn't running
  - the periodic poll observes WP running → WP is shut down if the pool
    sensor reports off, unavailable, or unreadable
- If `pool_status_entity` is left empty, both safety checks are disabled
  (use with caution).

### Config options (config.yaml)
- `pool_status_entity` — entity ID consulted for the safety gate
- All previous `pool_mode_entity` / `pool_allowed_modes` /
  `auto_heat_hvac_mode` / prerun/postrun options were removed in 0.10.0:
  mode-filtering and start/stop logic now live in ha-pool-pump.

## Important Notes
- Heat pump is offline in winter — addon detects this and waits
- User's network: 192.168.2.0/24
- MQTT broker requires authentication
- Don't mask mqtt_password in logs was already handled in run.sh
- Always bump version in config.yaml with every functional change
