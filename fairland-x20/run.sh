#!/usr/bin/with-contenv bashio

set +x

# Read configuration from Home Assistant
CONFIG_MODBUS_HOST=$(bashio::config 'modbus_host')
CONFIG_MODBUS_PORT=$(bashio::config 'modbus_port')
CONFIG_MODBUS_SLAVE=$(bashio::config 'modbus_slave')
CONFIG_SCAN_INTERVAL=$(bashio::config 'scan_interval')
CONFIG_MESSAGE_DELAY=$(bashio::config 'message_delay_ms')
CONFIG_MQTT_HOST=$(bashio::config 'mqtt_host')
CONFIG_MQTT_PORT=$(bashio::config 'mqtt_port')
CONFIG_MQTT_USER=$(bashio::config 'mqtt_user')
CONFIG_MQTT_PASS=$(bashio::config 'mqtt_password')
CONFIG_LOGLEVEL=$(bashio::config 'loglevel')

echo "============================================"
echo "  Fairland X20 Pool Heat Pump Addon"
echo "============================================"
echo "Modbus:  ${CONFIG_MODBUS_HOST}:${CONFIG_MODBUS_PORT} (slave ${CONFIG_MODBUS_SLAVE})"
echo "MQTT:    ${CONFIG_MQTT_HOST}:${CONFIG_MQTT_PORT}"
echo "Scan:    ${CONFIG_SCAN_INTERVAL}s"
echo "Delay:   ${CONFIG_MESSAGE_DELAY}ms"
echo "Log:     ${CONFIG_LOGLEVEL}"
echo "============================================"

# Build JSON config for Python
CONFIG_JSON=$(cat <<EOF
{
  "modbus_host": "${CONFIG_MODBUS_HOST}",
  "modbus_port": ${CONFIG_MODBUS_PORT},
  "modbus_slave": ${CONFIG_MODBUS_SLAVE},
  "scan_interval": ${CONFIG_SCAN_INTERVAL},
  "message_delay_ms": ${CONFIG_MESSAGE_DELAY},
  "mqtt_host": "${CONFIG_MQTT_HOST}",
  "mqtt_port": ${CONFIG_MQTT_PORT},
  "mqtt_user": "${CONFIG_MQTT_USER}",
  "mqtt_password": "${CONFIG_MQTT_PASS}",
  "loglevel": "${CONFIG_LOGLEVEL}"
}
EOF
)

# Activate virtual environment
if [ -f "./venv/bin/activate" ]; then
    source ./venv/bin/activate
fi

cd /srv/src
exec python3 main.py "${CONFIG_JSON}"
