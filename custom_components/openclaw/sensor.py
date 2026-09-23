"""Sensor entities for the OpenClaw integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DATA_LAST_ACTIVITY,
    DATA_LAST_TOOL_DURATION_MS,
    DATA_LAST_TOOL_ERROR,
    DATA_LAST_TOOL_INVOKED_AT,
    DATA_LAST_TOOL_NAME,
    DATA_LAST_TOOL_RESULT_PREVIEW,
    DATA_LAST_TOOL_STATUS,
    DATA_MODEL,
    DATA_STATUS,
    DOMAIN,
)
from .coordinator import OpenClawCoordinator

SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key=DATA_STATUS,
        translation_key="status",
        name="Status",
        icon="mdi:robot",
    ),
    SensorEntityDescription(
        key=DATA_MODEL,
        translation_key="model",
        name="Model",
        icon="mdi:brain",
    ),
    SensorEntityDescription(
        key=DATA_LAST_ACTIVITY,
        translation_key="last_activity",
        name="Last Activity",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
    ),
    SensorEntityDescription(
        key=DATA_LAST_TOOL_NAME,
        translation_key="last_tool_name",
        name="Last Tool",
        icon="mdi:tools",
    ),
    SensorEntityDescription(
        key=DATA_LAST_TOOL_STATUS,
        translation_key="last_tool_status",
        name="Last Tool Status",
        icon="mdi:check-decagram",
    ),
    SensorEntityDescription(
        key=DATA_LAST_TOOL_DURATION_MS,
        translation_key="last_tool_duration_ms",
        name="Last Tool Duration",
        icon="mdi:speedometer",
        native_unit_of_measurement="ms",
    ),
    SensorEntityDescription(
        key=DATA_LAST_TOOL_INVOKED_AT,
        translation_key="last_tool_invoked_at",
        name="Last Tool Invoked",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenClaw sensors from a config entry."""
    coordinator: OpenClawCoordinator = hass.data[DOMAIN]["entries"][entry.entry_id][
        "coordinator"
    ]

    async_add_entities(
        [
            OpenClawSensor(coordinator, description, entry)
            for description in SENSOR_DESCRIPTIONS
        ]
    )


class OpenClawSensor(CoordinatorEntity[OpenClawCoordinator], SensorEntity):
    """Sensor entity for OpenClaw data."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OpenClawCoordinator,
        description: SensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "OpenClaw Gateway",
            "manufacturer": "OpenClaw",
            "model": "OpenClaw Gateway",
        }

    @property
    def native_value(self) -> str | int | datetime | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes based on sensor type."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key
        data = self.coordinator.data

        if key == DATA_STATUS:
            return {
                "models": self.coordinator.available_models,
            }

        if key in {
            DATA_LAST_TOOL_NAME,
            DATA_LAST_TOOL_STATUS,
            DATA_LAST_TOOL_DURATION_MS,
        }:
            return {
                "error": data.get(DATA_LAST_TOOL_ERROR),
                "result_preview": data.get(DATA_LAST_TOOL_RESULT_PREVIEW),
                "invoked_at": data.get(DATA_LAST_TOOL_INVOKED_AT),
            }

        return None
