"""DataUpdateCoordinator for the OpenClaw integration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import (
    OpenClawApiClient,
    OpenClawApiError,
    OpenClawAuthError,
    OpenClawConnectionError,
)
from .const import (
    DATA_CONNECTED,
    DATA_LAST_ACTIVITY,
    DATA_LAST_TOOL_DURATION_MS,
    DATA_LAST_TOOL_ERROR,
    DATA_LAST_TOOL_INVOKED_AT,
    DATA_LAST_TOOL_NAME,
    DATA_LAST_TOOL_RESULT_PREVIEW,
    DATA_LAST_TOOL_STATUS,
    DATA_MODEL,
    DATA_STATUS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class OpenClawCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the OpenClaw gateway for status updates."""

    def __init__(self, hass: HomeAssistant, client: OpenClawApiClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self._last_activity: datetime | None = None
        self._model_cache: dict[str, Any] = {}
        self._available_models: list[str] = []
        self._consecutive_failures = 0
        self._last_tool_state: dict[str, Any] = {
            DATA_LAST_TOOL_NAME: None,
            DATA_LAST_TOOL_STATUS: None,
            DATA_LAST_TOOL_DURATION_MS: None,
            DATA_LAST_TOOL_INVOKED_AT: None,
            DATA_LAST_TOOL_ERROR: None,
            DATA_LAST_TOOL_RESULT_PREVIEW: None,
        }

    def _offline_data(self) -> dict[str, Any]:
        """Return a data dict representing the offline state."""
        return {
            DATA_STATUS: "offline",
            DATA_CONNECTED: False,
            DATA_MODEL: self._model_cache.get(DATA_MODEL),
            DATA_LAST_ACTIVITY: self._last_activity,
            DATA_LAST_TOOL_NAME: self._last_tool_state.get(DATA_LAST_TOOL_NAME),
            DATA_LAST_TOOL_STATUS: self._last_tool_state.get(DATA_LAST_TOOL_STATUS),
            DATA_LAST_TOOL_DURATION_MS: self._last_tool_state.get(
                DATA_LAST_TOOL_DURATION_MS
            ),
            DATA_LAST_TOOL_INVOKED_AT: self._last_tool_state.get(
                DATA_LAST_TOOL_INVOKED_AT
            ),
            DATA_LAST_TOOL_ERROR: self._last_tool_state.get(DATA_LAST_TOOL_ERROR),
            DATA_LAST_TOOL_RESULT_PREVIEW: self._last_tool_state.get(
                DATA_LAST_TOOL_RESULT_PREVIEW
            ),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the OpenClaw gateway."""
        data = self._offline_data()

        # ── Connectivity check (base URL ping) ─────────────────────
        try:
            alive = await self.client.async_check_alive()
            if not alive:
                return data

            data[DATA_STATUS] = "online"
            data[DATA_CONNECTED] = True
            data[DATA_LAST_ACTIVITY] = self._last_activity
            self._consecutive_failures = 0

        except OpenClawConnectionError:
            self._consecutive_failures += 1
            if self._consecutive_failures == 4:
                _LOGGER.warning(
                    "Gateway has been unreachable for %d consecutive polls",
                    self._consecutive_failures,
                )
            return data

        # ── Best-effort model info (/v1/models) ────────────────────
        try:
            models_resp = await self.client.async_get_models()
            models = models_resp.get("data", [])
            if models:
                current = models[0]
                self._model_cache = {DATA_MODEL: current.get("id", "unknown")}
                self._available_models = [
                    m.get("id") for m in models if m.get("id")
                ]
        except OpenClawAuthError as err:
            _LOGGER.warning("Gateway auth failed during poll: %s", err)
        except OpenClawApiError:
            # /v1/models not implemented — not fatal
            pass

        data.update(self._model_cache)
        data.update(self._last_tool_state)
        return data

    def update_last_activity(self) -> None:
        """Update the last activity timestamp to now."""
        self._last_activity = datetime.now(timezone.utc)

    @property
    def available_models(self) -> list[str]:
        """Return the list of model IDs from the last successful poll."""
        return list(self._available_models)

    def record_tool_invocation(
        self,
        *,
        tool_name: str,
        ok: bool,
        duration_ms: int,
        error_message: str | None = None,
        result_preview: str | None = None,
    ) -> None:
        """Store latest tool invocation metadata and update entities immediately."""
        self._last_tool_state = {
            DATA_LAST_TOOL_NAME: tool_name,
            DATA_LAST_TOOL_STATUS: "ok" if ok else "error",
            DATA_LAST_TOOL_DURATION_MS: duration_ms,
            DATA_LAST_TOOL_INVOKED_AT: datetime.now(timezone.utc),
            DATA_LAST_TOOL_ERROR: error_message,
            DATA_LAST_TOOL_RESULT_PREVIEW: result_preview,
        }
        current = dict(self.data or self._offline_data())
        current.update(self._last_tool_state)
        self.async_set_updated_data(current)
