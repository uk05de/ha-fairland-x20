# -*- coding: utf-8 -*-
#
# Heizautomatik Controller
#
# Couples the heat pump to the pool pump:
#   - WP only runs when pool pump is running AND in an allowed mode
#   - Prerun delay before powering on (flow must be stable)
#   - Postrun: WP powers off before pool pump's scheduled stop, so the
#     pool pump keeps running as residual flow for the heat exchanger
#   - Safety: power-on commands are blocked when flow_ok is false,
#     regardless of whether the automation switch is on
#

import logging
import time
from datetime import datetime, timezone

from fairland_x20 import HvacMode

log = logging.getLogger("fairland-x20.auto_heat")

_HVAC_TARGETS = {
    "heat": HvacMode.HEAT,
    "auto": HvacMode.AUTO,
}


class AutoHeatController:
    """Decides when the WP may run, based on pool pump state read via HA API."""

    def __init__(self, config: dict, ha_api, modbus_client, mqtt_bridge):
        self.ha_api = ha_api
        self.modbus = modbus_client
        self.mqtt = mqtt_bridge

        self.pool_status_entity = config.get("pool_status_entity", "")
        self.pool_mode_entity = config.get("pool_mode_entity", "")
        self.pool_next_transition_entity = config.get("pool_next_transition_entity", "")
        self.allowed_modes = set(config.get("pool_allowed_modes", []))
        self.prerun_seconds = int(config.get("auto_heat_prerun_seconds", 60))
        self.postrun_seconds = int(config.get("auto_heat_postrun_seconds", 180))
        self.hvac_mode_when_active = config.get("auto_heat_hvac_mode", "heat")

        # Runtime state
        self.enabled = False                      # set by MQTT switch
        self.flow_ok = False
        self.status_text = "aus"
        self._pump_running_since: float | None = None  # monotonic
        self._last_published_status: str | None = None
        self._last_published_flow_ok: bool | None = None

    def set_enabled(self, enabled: bool):
        """Called from MQTT switch handler."""
        if enabled == self.enabled:
            return
        self.enabled = enabled
        log.info("Heizautomatik %s", "EIN" if enabled else "AUS")
        if not enabled:
            self._set_status("aus")
            self._publish_status_if_changed()

    def is_command_allowed(self, cmd: str, value) -> bool:
        """Safety filter for incoming MQTT commands.

        Blocks power=ON when flow is not OK, regardless of whether the
        Heizautomatik switch is on. Other commands pass through.
        """
        if cmd == "power" and value is True and not self.flow_ok:
            log.warning("Safety: power=ON abgelehnt (flow_ok=False)")
            return False
        return True

    async def tick(self, wp_running: bool):
        """Run one decision cycle. Called from the main poll loop."""
        pool_running, mode_str, mode_allowed = await self._read_pool_state()
        seconds_until_stop = await self._read_seconds_until_stop()

        log.debug(
            "Tick: enabled=%s pool_running=%s mode=%r allowed=%s "
            "sec_until_stop=%s wp_running=%s",
            self.enabled, pool_running, mode_str, mode_allowed,
            seconds_until_stop, wp_running,
        )

        # Update prerun timer
        if pool_running:
            if self._pump_running_since is None:
                self._pump_running_since = time.monotonic()
        else:
            self._pump_running_since = None

        flow_ok = pool_running and mode_allowed
        self.flow_ok = flow_ok
        self._publish_flow_ok_if_changed()

        # Hard safety: WP currently on without flow → force off,
        # even if the automation switch is off (covers manual mistakes).
        if wp_running and not flow_ok:
            log.warning("Safety override: WP läuft ohne Durchfluss → AUS")
            await self.modbus.set_power(False)
            wp_running = False

        if not self.enabled:
            self._set_status("aus")
            self._publish_status_if_changed()
            return

        # Decide target state under automation
        target_on, new_status = self._decide(
            pool_running=pool_running,
            mode_allowed=mode_allowed,
            mode_str=mode_str,
            seconds_until_stop=seconds_until_stop,
        )

        if target_on and not wp_running:
            await self._ensure_hvac_mode()
            log.info("Heizautomatik: WP einschalten")
            await self.modbus.set_power(True)
        elif not target_on and wp_running:
            log.info("Heizautomatik: WP ausschalten (%s)", new_status)
            await self.modbus.set_power(False)

        self._set_status(new_status)
        self._publish_status_if_changed()

    def _decide(self, *, pool_running, mode_allowed, mode_str, seconds_until_stop):
        """Pure decision function. Returns (target_on, status_text)."""
        if not pool_running:
            return False, "wartet auf Pool-Pumpe"
        if not mode_allowed:
            mode_label = mode_str or "unbekannt"
            return False, f"blockiert (Modus: {mode_label})"

        assert self._pump_running_since is not None
        elapsed = time.monotonic() - self._pump_running_since
        if elapsed < self.prerun_seconds:
            remaining = int(self.prerun_seconds - elapsed)
            return False, f"Vorlauf ({remaining}s)"

        if (seconds_until_stop is not None
                and seconds_until_stop <= self.postrun_seconds):
            return False, "Nachlauf"

        return True, "läuft"

    async def _read_pool_state(self):
        """Return (pool_running, mode_str, mode_allowed).

        ha_api.get_state already returns None for unknown/unavailable/missing,
        so any non-None state we get back is the current truth.
        """
        status = await self.ha_api.get_state(self.pool_status_entity)
        mode = await self.ha_api.get_state(self.pool_mode_entity)

        if status is None:
            return False, None, False

        # binary_sensor uses HA convention "on" / "off"
        pool_running = status.state.lower() == "on"

        if mode is None:
            return pool_running, None, False

        mode_allowed = mode.state in self.allowed_modes
        return pool_running, mode.state, mode_allowed

    async def _read_seconds_until_stop(self) -> float | None:
        """Return seconds until pool pump's planned next transition, or None."""
        if not self.pool_next_transition_entity:
            return None
        state = await self.ha_api.get_state(self.pool_next_transition_entity)
        if state is None:
            return None
        return _seconds_until_iso(state.state)

    async def _ensure_hvac_mode(self):
        target_mode = _HVAC_TARGETS.get(self.hvac_mode_when_active, HvacMode.HEAT)
        current = self.modbus.state.hvac_mode
        if current != target_mode:
            log.info("Heizautomatik: setze HVAC-Modus auf %s", target_mode.name)
            await self.modbus.set_hvac_mode(target_mode)

    def _set_status(self, text: str):
        self.status_text = text

    def _publish_status_if_changed(self):
        if self.status_text == self._last_published_status:
            return
        self._last_published_status = self.status_text
        self.mqtt.publish_auto_heat_status(self.status_text)
        log.debug("Heizautomatik Status: %s", self.status_text)

    def _publish_flow_ok_if_changed(self):
        if self.flow_ok == self._last_published_flow_ok:
            return
        self._last_published_flow_ok = self.flow_ok
        self.mqtt.publish_flow_ok(self.flow_ok)


def _seconds_until_iso(iso_ts: str) -> float | None:
    """Parse HA ISO8601 timestamp; return seconds from now (negative if past)."""
    if not iso_ts:
        return None
    try:
        ts = iso_ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (dt - now).total_seconds()
    except (ValueError, AttributeError):
        return None
