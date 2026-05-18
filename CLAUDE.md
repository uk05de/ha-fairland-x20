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
- fairland-x20/src/main.py — Main loop, reachability check, command queue
- fairland-x20/src/ha_api.py — HA Supervisor REST client (read pool pump entity states)
- fairland-x20/src/auto_heat.py — Heizautomatik controller (couples WP to pool pump)
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
- Heizautomatik: couples WP to ha-pool-pump (see below)

## Heizautomatik
Couples the WP to an external pool pump (`ha-pool-pump` integration). The WP
only runs while the pool pump is running and in an allowed mode, with a
configurable prerun delay and a postrun where the WP shuts off before the
pool pump's scheduled stop so the pump keeps flushing residual heat.

### Reads (via HA Supervisor REST API, requires `homeassistant_api: true`)
- `sensor.pool_pump_status` — "running (X%)" / "stopped"
- `sensor.pool_pump_mode` — "Automatik" / "Manuell" / "Frostschutz" / program name
- `sensor.pool_pump_next_transition` — ISO timestamp of next state change

### MQTT entities exposed
- `switch.fairland_x20_heizautomatik` — master switch, retained
- `sensor.fairland_x20_heizautomatik_status` — text status (`aus`, `wartet auf Pool-Pumpe`, `Vorlauf (Xs)`, `läuft`, `Nachlauf`, `blockiert (Modus: ...)`)
- `binary_sensor.fairland_x20_durchfluss_ok` — safety gate, visible

### Safety
- power=ON commands are rejected when flow_ok is false, even when the
  Heizautomatik switch is off. This is enforced in `_process_commands()`
  via `auto_heat.is_command_allowed()`.
- If WP is found running without flow_ok during a tick, it's forced off.
- Pool status sensor older than 60s → treated as "off" (HA restart, network).

### Config options (config.yaml)
- `pool_status_entity`, `pool_mode_entity`, `pool_next_transition_entity`
- `pool_allowed_modes` — list, default `["Automatik"]` (must match HA display labels)
- `auto_heat_prerun_seconds` — pool must run this long before WP powers on
- `auto_heat_postrun_seconds` — WP powers off this many seconds before pool's planned stop
- `auto_heat_hvac_mode` — `heat` or `auto`, set once when WP is powered on

### Allowlist semantics
Pool pump's mode string is matched literally against `pool_allowed_modes`.
Defaults exclude `Manuell` because manual mode has no `next_transition` →
no postrun warning → hard stop on pump shutoff. Add `Manuell` only if you
accept that tradeoff.

## Important Notes
- Heat pump is offline in winter — addon detects this and waits
- User's network: 192.168.2.0/24
- MQTT broker requires authentication
- Don't mask mqtt_password in logs was already handled in run.sh
- Always bump version in config.yaml with every functional change
