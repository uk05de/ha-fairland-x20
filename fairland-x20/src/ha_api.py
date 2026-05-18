# -*- coding: utf-8 -*-
#
# Home Assistant Supervisor REST API client
#
# Reads entity states from HA Core via the Supervisor proxy.
# Requires `homeassistant_api: true` in config.yaml — the Supervisor then
# injects a valid SUPERVISOR_TOKEN env var into the addon container.
#

import asyncio
import logging
import os
import time
from dataclasses import dataclass

import aiohttp

log = logging.getLogger("fairland-x20.ha_api")

SUPERVISOR_URL = "http://supervisor/core/api"


@dataclass
class HaState:
    """A single HA entity state at a point in time."""
    state: str
    age_seconds: float  # seconds since HA last_updated
    fetched_at: float   # monotonic time of this fetch


class HomeAssistantApi:
    """Tolerant async client for HA Core via the Supervisor proxy."""

    def __init__(self, timeout: float = 3.0):
        self.timeout = timeout
        self._token = os.environ.get("SUPERVISOR_TOKEN", "")
        self._session: aiohttp.ClientSession | None = None
        if not self._token:
            log.warning("SUPERVISOR_TOKEN not set — HA API calls will fail. "
                        "Is homeassistant_api: true in config.yaml?")

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_state(self, entity_id: str) -> HaState | None:
        """Fetch the current state of an HA entity.

        Returns None on any error (auth, network, missing entity, unavailable).
        Callers must treat None as "unknown" and fall back conservatively.
        """
        if not entity_id or not self._token:
            return None

        try:
            await self._ensure_session()
            url = f"{SUPERVISOR_URL}/states/{entity_id}"
            assert self._session is not None
            async with self._session.get(url) as resp:
                if resp.status == 404:
                    log.debug("Entity %s not found", entity_id)
                    return None
                if resp.status != 200:
                    log.warning("HA API %s returned %d for %s",
                                url, resp.status, entity_id)
                    return None
                data = await resp.json()

            state = data.get("state")
            if state in (None, "", "unknown", "unavailable"):
                log.debug("HA API %s state=%r — treated as unavailable",
                          entity_id, state)
                return None

            age = _parse_age_seconds(data.get("last_updated", ""))
            log.debug("HA API %s = %r (last_updated %.0fs ago)",
                      entity_id, state, age)
            return HaState(state=state, age_seconds=age, fetched_at=time.monotonic())

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("HA API error for %s: %s", entity_id, e)
            return None
        except Exception as e:
            log.error("Unexpected HA API error for %s: %s", entity_id, e)
            return None


def _parse_age_seconds(iso_ts: str) -> float:
    """Parse HA's ISO8601 timestamp and return seconds since now.

    Returns 0.0 if parsing fails — better to assume fresh than stale,
    since the staleness check is a secondary safety net.
    """
    if not iso_ts:
        return 0.0
    try:
        from datetime import datetime, timezone
        ts = iso_ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - dt).total_seconds())
    except (ValueError, ImportError):
        return 0.0
