"""AI Task integration for the OpenClaw integration."""

from __future__ import annotations

from json import JSONDecodeError
import logging
import re
from typing import TYPE_CHECKING

from homeassistant.components import ai_task, conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.json import json_loads

from .entity import OpenClawBaseLLMEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigSubentry

    from . import OpenClawConfigEntry

_LOGGER = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Best-effort extraction of a JSON object from an LLM response.

    The OpenClaw gateway forwards ``response_format`` to the backing agent but
    does not enforce it, so the model may wrap the JSON in markdown fences or
    add prose around it.
    """
    candidate = text.strip()

    if match := _CODE_FENCE_RE.search(candidate):
        candidate = match.group(1).strip()

    # Fall back to the outermost {...} block.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = candidate[start : end + 1]

    return candidate


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "ai_task_data":
            continue

        async_add_entities(
            [OpenClawTaskEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class OpenClawTaskEntity(
    ai_task.AITaskEntity,
    OpenClawBaseLLMEntity,
):
    """OpenClaw AI Task entity."""

    def __init__(
        self, entry: OpenClawConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Initialize the entity."""
        super().__init__(entry, subentry)
        self._attr_supported_features = (
            ai_task.AITaskEntityFeature.GENERATE_DATA
            | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
        )

    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Handle a generate data task."""
        # Call _async_handle_chat_log with empty custom_functions and exposed_entities
        # AI Task operates without functions
        await self._async_handle_chat_log(
            chat_log,
            function_tools=[],
            exposed_entities=[],
            llm_context=None,
            structure_name=task.name,
            structure=task.structure,
        )

        # Extract response
        if not isinstance(chat_log.content[-1], conversation.AssistantContent):
            raise HomeAssistantError(
                "Last content in chat log is not an AssistantContent"
            )

        text = chat_log.content[-1].content or ""

        # Handle structured output
        if not task.structure:
            return ai_task.GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data=text,
            )

        try:
            data = json_loads(_extract_json(text))
        except JSONDecodeError as err:
            _LOGGER.error(
                "Failed to parse JSON response: %s. Response: %s",
                err,
                text,
            )
            raise HomeAssistantError("Error with structured response") from err

        return ai_task.GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=data,
        )
