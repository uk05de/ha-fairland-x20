# CLAUDE.md

## Project
- Home Assistant Addon for Fairland X20 pool heat pump
- Repo: uk05de/ha-fairland-x20
- Replaces the old ha-modbusproxy addon (generic modbus proxy with filters)

## Architecture
- Python addon using pymodbus (Modbus TCP) + paho-mqtt (MQTT Discovery)
- No proxy layer — reads registers directly from heat pump
- Publishes to local MQTT broker (192.168.2.158:1883) with MQTT Discovery
- Config via /data/options.json (HA addon options)
- Startup: run.sh -> main.py

## Key Files
- fairland-x20/src/fairland_x20.py — Modbus client, register definitions, state dataclass
- fairland-x20/src/mqtt_discovery.py — MQTT Discovery configs, state publishing, polling switch
- fairland-x20/src/main.py — Main loop, reachability check, command queue
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

## Important Notes
- Heat pump is offline in winter — addon detects this and waits
- User's network: 192.168.2.0/24
- MQTT broker requires authentication (user: homeassistant)
- Don't mask mqtt_password in logs was already handled in run.sh
- Always bump version in config.yaml with every functional change
