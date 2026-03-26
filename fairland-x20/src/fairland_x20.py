# -*- coding: utf-8 -*-
#
# Fairland X20 Pool Heat Pump - Modbus Register Definitions & Client
#

import asyncio
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

log = logging.getLogger("fairland-x20")


# --- Register Definitions ---

class HvacMode(IntEnum):
    AUTO = 0
    HEAT = 1
    COOL = 2


class FanMode(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


def decode_temp(raw: int) -> float:
    """Decode Fairland temperature: raw * 0.5 - 30"""
    return round(raw * 0.5 - 30, 1)


def encode_temp(temp: float) -> int:
    """Encode temperature to Fairland format: (temp + 30) / 0.5"""
    return int((temp + 30) / 0.5)


@dataclass
class FairlandState:
    """Current state of the Fairland X20 heat pump."""
    # Binary sensors
    running: bool = False
    error: bool = False
    error_e3: bool = False

    # Sensors (input registers)
    compressor_percent: int = 0
    pfc_voltage: int = 0
    inlet_temp: float = 0.0
    outlet_temp: float = 0.0
    ambient_temp: float = 0.0
    compressor_current: float = 0.0

    # Climate (holding registers)
    hvac_mode: HvacMode = HvacMode.AUTO
    fan_mode: FanMode = FanMode.LOW
    target_temp: float = 26.0

    # Availability
    available: bool = False


class FairlandX20Client:
    """Modbus TCP client for the Fairland X20 heat pump."""

    def __init__(self, host: str, port: int = 502, slave: int = 1,
                 message_delay: float = 0.2, timeout: float = 3):
        self.host = host
        self.port = port
        self.slave = slave
        self.message_delay = message_delay
        self.timeout = timeout
        self._client = None
        self.state = FairlandState()

    async def connect(self):
        self._client = AsyncModbusTcpClient(
            self.host,
            port=self.port,
            timeout=self.timeout,
        )
        connected = await self._client.connect()
        if connected:
            log.info("Connected to Fairland X20 at %s:%d", self.host, self.port)
        else:
            log.error("Failed to connect to %s:%d", self.host, self.port)
        return connected

    async def disconnect(self):
        if self._client:
            self._client.close()
            log.info("Disconnected from Fairland X20")

    async def _delay(self):
        """Delay between Modbus requests to not overwhelm the heat pump."""
        await asyncio.sleep(self.message_delay)

    async def poll(self) -> FairlandState:
        """Read all registers and return current state."""
        try:
            if not self._client or not self._client.connected:
                await self.connect()

            # Read Coils - FC1: address 0 (running status)
            result = await self._client.read_coils(address=0, count=1, slave=self.slave)
            if not result.isError():
                self.state.running = result.bits[0]
            else:
                log.warning("Failed to read coil 0: %s", result)
            await self._delay()

            # Read Discrete Inputs - FC2: address 16 (error status)
            result = await self._client.read_discrete_inputs(address=16, count=1, slave=self.slave)
            if not result.isError():
                self.state.error = result.bits[0]
            else:
                log.warning("Failed to read discrete input 16: %s", result)
            await self._delay()

            # Read Discrete Inputs - FC2: address 51 (E3 error)
            result = await self._client.read_discrete_inputs(address=51, count=1, slave=self.slave)
            if not result.isError():
                self.state.error_e3 = result.bits[0]
            else:
                log.warning("Failed to read discrete input 51: %s", result)
            await self._delay()

            # Read Holding Registers - FC3: address 0-3 (HVAC mode, fan mode, _, target temp)
            result = await self._client.read_holding_registers(address=0, count=4, slave=self.slave)
            if not result.isError():
                self.state.hvac_mode = HvacMode(result.registers[0])
                self.state.fan_mode = FanMode(result.registers[1])
                self.state.target_temp = decode_temp(result.registers[3])
            else:
                log.warning("Failed to read holding registers 0-3: %s", result)
            await self._delay()

            # Read Input Registers - FC4: address 0-5
            result = await self._client.read_input_registers(address=0, count=6, slave=self.slave)
            if not result.isError():
                self.state.compressor_percent = result.registers[0]
                self.state.pfc_voltage = result.registers[2]
                self.state.inlet_temp = decode_temp(result.registers[3])
                self.state.outlet_temp = decode_temp(result.registers[4])
                self.state.ambient_temp = decode_temp(result.registers[5])
            else:
                log.warning("Failed to read input registers 0-5: %s", result)
            await self._delay()

            # Read Input Registers - FC4: address 11 (compressor current)
            result = await self._client.read_input_registers(address=11, count=1, slave=self.slave)
            if not result.isError():
                self.state.compressor_current = round(result.registers[0] * 0.1, 2)
            else:
                log.warning("Failed to read input register 11: %s", result)

            self.state.available = True

        except (ModbusException, ConnectionError, asyncio.TimeoutError) as e:
            log.error("Poll failed: %s", e)
            self.state.available = False
            # Force reconnect on next poll
            if self._client:
                self._client.close()

        return self.state

    async def set_power(self, on: bool) -> bool:
        """Turn heat pump on/off via FC5 (Write Single Coil)."""
        try:
            result = await self._client.write_coil(
                address=0, value=on, slave=self.slave
            )
            if not result.isError():
                log.info("Set power to %s", "ON" if on else "OFF")
                self.state.running = on
                return True
            log.error("Failed to set power: %s", result)
        except (ModbusException, ConnectionError) as e:
            log.error("Set power failed: %s", e)
        return False

    async def set_hvac_mode(self, mode: HvacMode) -> bool:
        """Set HVAC mode (Auto/Heat/Cool) via FC6 (Write Single Register)."""
        try:
            result = await self._client.write_register(
                address=0, value=int(mode), slave=self.slave
            )
            if not result.isError():
                log.info("Set HVAC mode to %s", mode.name)
                self.state.hvac_mode = mode
                return True
            log.error("Failed to set HVAC mode: %s", result)
        except (ModbusException, ConnectionError) as e:
            log.error("Set HVAC mode failed: %s", e)
        return False

    async def set_fan_mode(self, mode: FanMode) -> bool:
        """Set fan mode (Low/Medium/High) via FC6 (Write Single Register)."""
        try:
            result = await self._client.write_register(
                address=1, value=int(mode), slave=self.slave
            )
            if not result.isError():
                log.info("Set fan mode to %s", mode.name)
                self.state.fan_mode = mode
                return True
            log.error("Failed to set fan mode: %s", result)
        except (ModbusException, ConnectionError) as e:
            log.error("Set fan mode failed: %s", e)
        return False

    async def set_target_temp(self, temp: float) -> bool:
        """Set target temperature via FC6 (Write Single Register)."""
        temp = max(18.0, min(32.0, temp))
        raw = encode_temp(temp)
        try:
            result = await self._client.write_register(
                address=3, value=raw, slave=self.slave
            )
            if not result.isError():
                log.info("Set target temp to %.1f°C (raw=%d)", temp, raw)
                self.state.target_temp = temp
                return True
            log.error("Failed to set target temp: %s", result)
        except (ModbusException, ConnectionError) as e:
            log.error("Set target temp failed: %s", e)
        return False
