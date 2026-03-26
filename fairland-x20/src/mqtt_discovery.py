# -*- coding: utf-8 -*-
#
# Fairland X20 - MQTT Discovery & Publishing for Home Assistant
#

import json
import logging
from dataclasses import dataclass

import paho.mqtt.client as mqtt

from fairland_x20 import FairlandState, HvacMode, FanMode

log = logging.getLogger("fairland-x20.mqtt")

DEVICE_INFO = {
    "identifiers": ["fairland_x20"],
    "name": "Fairland X20",
    "manufacturer": "Fairland",
    "model": "X20 Pool Heat Pump",
}

TOPIC_PREFIX = "fairland_x20"
DISCOVERY_PREFIX = "homeassistant"


class MqttBridge:
    """Bridges Fairland X20 state to Home Assistant via MQTT Discovery."""

    def __init__(self, host: str, port: int = 1883,
                 username: str = "", password: str = ""):
        self.host = host
        self.port = port
        self._client = mqtt.Client(client_id="fairland_x20", protocol=mqtt.MQTTv311)
        if username:
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._command_callbacks = {}
        self._discovery_sent = False
        self.polling_enabled = True

    def connect(self):
        self._client.connect(self.host, self.port, keepalive=60)
        self._client.loop_start()
        log.info("MQTT connected to %s:%d", self.host, self.port)

    def disconnect(self):
        self._client.loop_stop()
        self._client.disconnect()
        log.info("MQTT disconnected")

    def set_command_callback(self, name: str, callback):
        self._command_callbacks[name] = callback

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT broker connected")
            # Subscribe to command topics
            client.subscribe(f"{TOPIC_PREFIX}/switch/power/set")
            client.subscribe(f"{TOPIC_PREFIX}/switch/polling/set")
            client.subscribe(f"{TOPIC_PREFIX}/climate/mode/set")
            client.subscribe(f"{TOPIC_PREFIX}/climate/fan/set")
            client.subscribe(f"{TOPIC_PREFIX}/climate/temp/set")
            # Restore polling state from retained message
            client.subscribe(f"{TOPIC_PREFIX}/switch/polling/state")
            self._discovery_sent = False
        else:
            log.error("MQTT connection failed with code %d", rc)

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        log.debug("MQTT received: %s = %s", topic, payload)

        if topic == f"{TOPIC_PREFIX}/switch/polling/set" or \
           topic == f"{TOPIC_PREFIX}/switch/polling/state":
            self.polling_enabled = payload.upper() == "ON"
            log.info("Polling %s", "enabled" if self.polling_enabled else "disabled (Wintermodus)")
            # Publish confirmed state (only on /set to avoid loop)
            if topic.endswith("/set"):
                self._publish(f"{TOPIC_PREFIX}/switch/polling/state",
                              "ON" if self.polling_enabled else "OFF")

        elif topic == f"{TOPIC_PREFIX}/switch/power/set":
            cb = self._command_callbacks.get("power")
            if cb:
                cb(payload.upper() == "ON")

        elif topic == f"{TOPIC_PREFIX}/climate/mode/set":
            cb = self._command_callbacks.get("hvac_mode")
            if cb:
                mode_map = {"auto": HvacMode.AUTO, "heat": HvacMode.HEAT, "cool": HvacMode.COOL}
                mode = mode_map.get(payload.lower())
                if mode is not None:
                    cb(mode)

        elif topic == f"{TOPIC_PREFIX}/climate/fan/set":
            cb = self._command_callbacks.get("fan_mode")
            if cb:
                fan_map = {"low": FanMode.LOW, "medium": FanMode.MEDIUM, "high": FanMode.HIGH}
                mode = fan_map.get(payload.lower())
                if mode is not None:
                    cb(mode)

        elif topic == f"{TOPIC_PREFIX}/climate/temp/set":
            cb = self._command_callbacks.get("target_temp")
            if cb:
                try:
                    cb(float(payload))
                except ValueError:
                    log.warning("Invalid temperature value: %s", payload)

    def send_discovery(self):
        """Publish MQTT Discovery configs so HA auto-creates all entities."""
        if self._discovery_sent:
            return

        # --- Binary Sensors ---
        self._publish_discovery("binary_sensor", "status", {
            "name": "Status",
            "device_class": "running",
            "state_topic": f"{TOPIC_PREFIX}/binary_sensor/status/state",
            "payload_on": "ON",
            "payload_off": "OFF",
        })

        self._publish_discovery("binary_sensor", "error", {
            "name": "Fehler",
            "device_class": "problem",
            "state_topic": f"{TOPIC_PREFIX}/binary_sensor/error/state",
            "payload_on": "ON",
            "payload_off": "OFF",
        })

        self._publish_discovery("binary_sensor", "error_e3", {
            "name": "Fehler E3",
            "device_class": "problem",
            "state_topic": f"{TOPIC_PREFIX}/binary_sensor/error_e3/state",
            "payload_on": "ON",
            "payload_off": "OFF",
        })

        # --- Sensors ---
        self._publish_discovery("sensor", "compressor_percent", {
            "name": "Kompressor",
            "state_topic": f"{TOPIC_PREFIX}/sensor/compressor_percent/state",
            "unit_of_measurement": "%",
            "state_class": "measurement",
            "icon": "mdi:pump",
        })

        self._publish_discovery("sensor", "pfc_voltage", {
            "name": "PFC Spannung",
            "state_topic": f"{TOPIC_PREFIX}/sensor/pfc_voltage/state",
            "unit_of_measurement": "V",
            "device_class": "voltage",
            "state_class": "measurement",
        })

        self._publish_discovery("sensor", "inlet_temp", {
            "name": "Einlasstemperatur",
            "state_topic": f"{TOPIC_PREFIX}/sensor/inlet_temp/state",
            "unit_of_measurement": "°C",
            "device_class": "temperature",
            "state_class": "measurement",
        })

        self._publish_discovery("sensor", "outlet_temp", {
            "name": "Auslasstemperatur",
            "state_topic": f"{TOPIC_PREFIX}/sensor/outlet_temp/state",
            "unit_of_measurement": "°C",
            "device_class": "temperature",
            "state_class": "measurement",
        })

        self._publish_discovery("sensor", "ambient_temp", {
            "name": "Außentemperatur",
            "state_topic": f"{TOPIC_PREFIX}/sensor/ambient_temp/state",
            "unit_of_measurement": "°C",
            "device_class": "temperature",
            "state_class": "measurement",
        })

        self._publish_discovery("sensor", "compressor_current", {
            "name": "Kompressor Strom",
            "state_topic": f"{TOPIC_PREFIX}/sensor/compressor_current/state",
            "unit_of_measurement": "A",
            "device_class": "current",
            "state_class": "measurement",
        })

        # --- Switches ---
        self._publish_discovery("switch", "polling", {
            "name": "Abfrage aktiv",
            "state_topic": f"{TOPIC_PREFIX}/switch/polling/state",
            "command_topic": f"{TOPIC_PREFIX}/switch/polling/set",
            "payload_on": "ON",
            "payload_off": "OFF",
            "icon": "mdi:snowflake-thermometer",
            "entity_category": "config",
        })

        self._publish_discovery("switch", "power", {
            "name": "Ein/Aus",
            "state_topic": f"{TOPIC_PREFIX}/switch/power/state",
            "command_topic": f"{TOPIC_PREFIX}/switch/power/set",
            "payload_on": "ON",
            "payload_off": "OFF",
            "icon": "mdi:heat-pump",
        })

        # --- Climate ---
        self._publish_discovery("climate", "climate", {
            "name": "Modus",
            "modes": ["auto", "heat", "cool"],
            "fan_modes": ["low", "medium", "high"],
            "mode_state_topic": f"{TOPIC_PREFIX}/climate/mode/state",
            "mode_command_topic": f"{TOPIC_PREFIX}/climate/mode/set",
            "fan_mode_state_topic": f"{TOPIC_PREFIX}/climate/fan/state",
            "fan_mode_command_topic": f"{TOPIC_PREFIX}/climate/fan/set",
            "temperature_state_topic": f"{TOPIC_PREFIX}/climate/temp/state",
            "temperature_command_topic": f"{TOPIC_PREFIX}/climate/temp/set",
            "current_temperature_topic": f"{TOPIC_PREFIX}/sensor/inlet_temp/state",
            "min_temp": 18,
            "max_temp": 32,
            "temp_step": 1,
            "temperature_unit": "C",
            "precision": 0.5,
        })

        self._discovery_sent = True
        # Publish initial polling state (if no retained message overrides it)
        self._publish(f"{TOPIC_PREFIX}/switch/polling/state",
                      "ON" if self.polling_enabled else "OFF")
        log.info("MQTT Discovery configs published")

    def _publish_discovery(self, component: str, object_id: str, config: dict):
        """Publish a single MQTT Discovery config."""
        config["unique_id"] = f"fairland_x20_{object_id}"
        config["device"] = DEVICE_INFO
        config["availability_topic"] = f"{TOPIC_PREFIX}/availability"
        config["payload_available"] = "online"
        config["payload_not_available"] = "offline"

        topic = f"{DISCOVERY_PREFIX}/{component}/fairland_x20/{object_id}/config"
        payload = json.dumps(config)
        self._client.publish(topic, payload, qos=1, retain=True)
        log.debug("Discovery: %s", topic)

    def publish_state(self, state: FairlandState):
        """Publish current state values to MQTT."""
        self.send_discovery()

        # Availability
        avail = "online" if state.available else "offline"
        self._client.publish(f"{TOPIC_PREFIX}/availability", avail, retain=True)

        if not state.available:
            return

        # Binary sensors
        self._publish(f"{TOPIC_PREFIX}/binary_sensor/status/state",
                      "ON" if state.running else "OFF")
        self._publish(f"{TOPIC_PREFIX}/binary_sensor/error/state",
                      "ON" if state.error else "OFF")
        self._publish(f"{TOPIC_PREFIX}/binary_sensor/error_e3/state",
                      "ON" if state.error_e3 else "OFF")

        # Sensors
        self._publish(f"{TOPIC_PREFIX}/sensor/compressor_percent/state",
                      str(state.compressor_percent))
        self._publish(f"{TOPIC_PREFIX}/sensor/pfc_voltage/state",
                      str(state.pfc_voltage))
        self._publish(f"{TOPIC_PREFIX}/sensor/inlet_temp/state",
                      str(state.inlet_temp))
        self._publish(f"{TOPIC_PREFIX}/sensor/outlet_temp/state",
                      str(state.outlet_temp))
        self._publish(f"{TOPIC_PREFIX}/sensor/ambient_temp/state",
                      str(state.ambient_temp))
        self._publish(f"{TOPIC_PREFIX}/sensor/compressor_current/state",
                      str(state.compressor_current))

        # Switch
        self._publish(f"{TOPIC_PREFIX}/switch/power/state",
                      "ON" if state.running else "OFF")

        # Climate
        hvac_map = {HvacMode.AUTO: "auto", HvacMode.HEAT: "heat", HvacMode.COOL: "cool"}
        fan_map = {FanMode.LOW: "low", FanMode.MEDIUM: "medium", FanMode.HIGH: "high"}
        self._publish(f"{TOPIC_PREFIX}/climate/mode/state",
                      hvac_map.get(state.hvac_mode, "auto"))
        self._publish(f"{TOPIC_PREFIX}/climate/fan/state",
                      fan_map.get(state.fan_mode, "low"))
        self._publish(f"{TOPIC_PREFIX}/climate/temp/state",
                      str(state.target_temp))

    def publish_offline(self):
        """Mark device as offline (used when polling is disabled)."""
        self.send_discovery()
        self._client.publish(f"{TOPIC_PREFIX}/availability", "offline", retain=True)

    def _publish(self, topic: str, payload: str):
        self._client.publish(topic, payload, retain=True)
