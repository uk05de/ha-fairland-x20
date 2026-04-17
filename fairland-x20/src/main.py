# -*- coding: utf-8 -*-
#
# Fairland X20 Pool Heat Pump - Main Entry Point
#

import asyncio
import logging
import signal
import socket
import sys

from fairland_x20 import FairlandX20Client
from mqtt_discovery import MqttBridge

log = logging.getLogger("fairland-x20")


class FairlandX20Addon:
    """Main addon loop: poll Modbus, publish to MQTT, handle commands."""

    def __init__(self, config: dict):
        self.scan_interval = config["scan_interval"]

        self.modbus = FairlandX20Client(
            host=config["modbus_host"],
            port=config["modbus_port"],
            slave=config["modbus_slave"],
            message_delay=config["message_delay_ms"] / 1000.0,
            timeout=3,
        )

        self.mqtt = MqttBridge(
            host=config["mqtt_host"],
            port=config["mqtt_port"],
            username=config.get("mqtt_user", ""),
            password=config.get("mqtt_password", ""),
            fallback_temp_topic=config.get("fallback_temp_topic", ""),
        )

        self._running = True
        self._command_queue = asyncio.Queue()
        self._reachable = False
        self._reachability_interval = 60  # check every 60s when offline

    async def start(self):
        log.info("Starting Fairland X20 Addon")
        log.info("Modbus: %s:%d (slave %d)",
                 self.modbus.host, self.modbus.port, self.modbus.slave)
        log.info("MQTT: %s:%d", self.mqtt.host, self.mqtt.port)
        log.info("Scan interval: %ds", self.scan_interval)

        # Connect MQTT and publish discovery immediately
        self.mqtt.connect()
        # Wait briefly for MQTT connection to establish
        await asyncio.sleep(2)
        self.mqtt.publish_offline()

        # Register command callbacks
        self.mqtt.set_command_callback("power", self._queue_cmd("power"))
        self.mqtt.set_command_callback("hvac_mode", self._queue_cmd("hvac_mode"))
        self.mqtt.set_command_callback("fan_mode", self._queue_cmd("fan_mode"))
        self.mqtt.set_command_callback("target_temp", self._queue_cmd("target_temp"))

        # Main loop
        consecutive_errors = 0
        max_errors = 10
        was_active = False

        while self._running:
            # Manual override: polling disabled via switch
            if not self.mqtt.polling_enabled:
                if was_active:
                    log.info("Polling disabled - disconnecting Modbus, marking offline")
                    await self.modbus.disconnect()
                    self.mqtt.publish_offline()
                    self._reachable = False
                    was_active = False
                await asyncio.sleep(self.scan_interval)
                continue

            # Auto-detect: check if WP is reachable
            reachable = await self._check_reachable()

            if not reachable:
                if was_active:
                    log.info("Heat pump not reachable - disconnecting, marking offline")
                    await self.modbus.disconnect()
                    self.mqtt.publish_offline()
                    was_active = False
                    consecutive_errors = 0
                elif not self._reachable:
                    log.debug("Heat pump still not reachable, waiting...")
                self._reachable = False
                await asyncio.sleep(self._reachability_interval)
                continue

            if not self._reachable:
                log.info("Heat pump is reachable again at %s:%d",
                         self.modbus.host, self.modbus.port)
            self._reachable = True

            # Connect if needed
            if not was_active:
                log.info("Connecting to Modbus")
                await self.modbus.connect()
                consecutive_errors = 0
                was_active = True

            try:
                # Process pending commands
                await self._process_commands()

                # Poll state
                state = await self.modbus.poll()
                self.mqtt.publish_state(state)

                if state.available:
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                    log.warning("Poll unavailable (%d/%d)", consecutive_errors, max_errors)
                    if consecutive_errors >= max_errors:
                        log.error("%d consecutive errors, exiting for watchdog restart",
                                  max_errors)
                        sys.exit(1)

            except Exception as e:
                log.error("Main loop error: %s", e)
                consecutive_errors += 1
                if consecutive_errors >= max_errors:
                    log.error("%d consecutive errors, exiting for watchdog restart",
                              max_errors)
                    sys.exit(1)

            await asyncio.sleep(self.scan_interval)

    async def _check_reachable(self) -> bool:
        """Quick TCP connect check to see if the heat pump is on the network."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.modbus.host, self.modbus.port),
                timeout=2
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
            return False

    def _queue_cmd(self, name):
        """Return a callback that queues a command for async processing."""
        def callback(value):
            self._command_queue.put_nowait((name, value))
        return callback

    async def _process_commands(self):
        """Process all queued commands from MQTT."""
        while not self._command_queue.empty():
            cmd, value = self._command_queue.get_nowait()
            log.info("Processing command: %s = %s", cmd, value)

            if cmd == "power":
                await self.modbus.set_power(value)
            elif cmd == "hvac_mode":
                await self.modbus.set_hvac_mode(value)
            elif cmd == "fan_mode":
                await self.modbus.set_fan_mode(value)
            elif cmd == "target_temp":
                await self.modbus.set_target_temp(value)

            await asyncio.sleep(self.modbus.message_delay)

        # After commands, do a fresh poll to reflect changes
        if not self._command_queue.empty():
            state = await self.modbus.poll()
            self.mqtt.publish_state(state)

    async def stop(self):
        log.info("Stopping Fairland X20 Addon")
        self._running = False
        await self.modbus.disconnect()
        self.mqtt.disconnect()


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        format="%(asctime)s %(levelname)8s %(name)s: %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )


def main():
    """Entry point when called from run.sh with options file path."""
    import json

    if len(sys.argv) < 2:
        print("Usage: main.py /data/options.json")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        config = json.load(f)
    setup_logging(config.get("loglevel", "INFO"))

    addon = FairlandX20Addon(config)

    def shutdown(sig, frame):
        log.info("Signal %s received, shutting down...", sig)
        addon._running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        asyncio.run(addon.start())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
