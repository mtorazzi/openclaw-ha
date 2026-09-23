"""Helper functions for the OpenClaw integration."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncClient, AsyncOpenAI

from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.template import Template

from .const import (
    CONF_AGENT_ID,
    CONF_GATEWAY_HOST,
    CONF_GATEWAY_PORT,
    CONF_GATEWAY_TOKEN,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_AGENT_ID,
    DEFAULT_GATEWAY_HOST,
    DEFAULT_GATEWAY_PORT,
    DEFAULT_MODEL_CONFIG,
    DEFAULT_USE_SSL,
    DEFAULT_VERIFY_SSL,
    build_base_url,
)

_LOGGER = logging.getLogger(__name__)


def get_model_config(model: str) -> dict[str, bool]:
    """Get model-specific parameter configuration.

    All OpenClaw model aliases use the generic OpenAI-compatible parameter
    set; the gateway forwards the request to the backing agent.
    """
    return DEFAULT_MODEL_CONFIG


def get_exposed_entities(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Get exposed entities."""
    states = [
        state
        for state in hass.states.async_all()
        if async_should_expose(hass, conversation.DOMAIN, state.entity_id)
    ]
    entity_registry = er.async_get(hass)
    exposed_entities = []
    for state in states:
        entity_id = state.entity_id
        entity = entity_registry.async_get(entity_id)

        aliases: list[str] = []
        if entity and entity.aliases:
            aliases = [str(a) for a in entity.aliases]

        exposed_entities.append(
            {
                "entity_id": entity_id,
                "name": state.name,
                "state": state.state,
                "aliases": aliases,
            }
        )
    return exposed_entities


def convert_to_template(
    settings: Any,
    template_keys: list[str] | None = None,
    hass: HomeAssistant | None = None,
) -> None:
    if template_keys is None:
        template_keys = ["data", "event_data", "target", "service"]
    if hass is None:
        raise ValueError("hass is required to convert settings to templates")
    _convert_to_template(settings, template_keys, hass, [])


def _convert_to_template(
    settings: Any,
    template_keys: list[str],
    hass: HomeAssistant,
    parents: list[str],
) -> None:
    if isinstance(settings, dict):
        for key, value in settings.items():
            if isinstance(value, str) and (
                key in template_keys or set(parents).intersection(template_keys)
            ):
                settings[key] = Template(value, hass)
            if isinstance(value, dict):
                parents.append(key)
                _convert_to_template(value, template_keys, hass, parents)
                parents.pop()
            if isinstance(value, list):
                parents.append(key)
                for item in value:
                    _convert_to_template(item, template_keys, hass, parents)
                parents.pop()
    if isinstance(settings, list):
        for setting in settings:
            _convert_to_template(setting, template_keys, hass, parents)


def get_openclaw_client(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> AsyncClient:
    """Build an OpenAI-compatible client pointed at the OpenClaw gateway.

    The gateway implements ``POST /v1/chat/completions`` and ``GET /v1/models``.
    Authentication uses the gateway bearer token; the selected agent is passed
    both via the ``x-openclaw-agent-id`` header and, when no explicit model is
    chosen, via the ``openclaw:<agent_id>`` model alias.
    """
    host = data.get(CONF_GATEWAY_HOST, DEFAULT_GATEWAY_HOST)
    port = int(data.get(CONF_GATEWAY_PORT, DEFAULT_GATEWAY_PORT))
    token = data[CONF_GATEWAY_TOKEN]
    use_ssl = data.get(CONF_USE_SSL, DEFAULT_USE_SSL)
    verify_ssl = data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    agent_id = data.get(CONF_AGENT_ID, DEFAULT_AGENT_ID) or DEFAULT_AGENT_ID

    headers: dict[str, str] = {}
    if agent_id:
        headers["x-openclaw-agent-id"] = agent_id

    return AsyncOpenAI(
        api_key=token,
        base_url=build_base_url(host, port, use_ssl),
        http_client=get_async_client(hass, verify_ssl=verify_ssl),
        default_headers=headers,
    )
