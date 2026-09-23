"""The OpenClaw integration.

OpenClaw is an OpenAI-compatible gateway for a standalone agent runtime.
This integration exposes it to Home Assistant as both an AI Task entity
(``GENERATE_DATA``) and a conversation agent for Assist/chat, and adds a
handful of gateway-specific services, events and status sensors.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

from openai import AsyncClient
from openai._exceptions import APIConnectionError, AuthenticationError, OpenAIError
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

try:
    from homeassistant.components.lovelace.const import LOVELACE_DATA
except ImportError:  # pragma: no cover
    LOVELACE_DATA = "lovelace"

from . import ai_task as ai_task, conversation as conversation, sensor as sensor
from .api import OpenClawApiClient, OpenClawApiError
from .const import (
    ATTR_ACCOUNT_ID,
    ATTR_ACTION,
    ATTR_AGENT_ID,
    ATTR_ARGS,
    ATTR_DRY_RUN,
    ATTR_DURATION_MS,
    ATTR_ERROR,
    ATTR_MESSAGE,
    ATTR_MESSAGE_CHANNEL,
    ATTR_MODEL,
    ATTR_OK,
    ATTR_RESULT,
    ATTR_SESSION_ID,
    ATTR_SESSION_KEY,
    ATTR_SOURCE,
    ATTR_TIMESTAMP,
    ATTR_TOOL,
    CONF_AGENT_ID,
    CONF_CHAT_MODEL,
    CONF_GATEWAY_HOST,
    CONF_GATEWAY_PORT,
    CONF_GATEWAY_TOKEN,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_AGENT_ID,
    DEFAULT_CHAT_MODEL,
    DOMAIN,
    EVENT_MESSAGE_RECEIVED,
    EVENT_TOOL_INVOKED,
    SERVICE_CLEAR_HISTORY,
    SERVICE_INVOKE_TOOL,
    SERVICE_SEND_MESSAGE,
    model_for_agent,
)
from .coordinator import OpenClawCoordinator
from .helpers import get_openclaw_client
from .services import async_setup_services
from .template import async_setup_templates, async_unload_templates

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.AI_TASK, Platform.CONVERSATION, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type OpenClawConfigEntry = ConfigEntry[AsyncClient]

_MAX_CHAT_HISTORY = 200

# Path to the chat card JS inside the integration package
_CARD_FILENAME = "openclaw-chat-card.js"
_CARD_PATH = Path(__file__).parent / "www" / _CARD_FILENAME
_CARD_STATIC_URL = f"/{DOMAIN}/{_CARD_FILENAME}"
_CARD_URL = f"{_CARD_STATIC_URL}?v=1.0.0"


SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_SOURCE): cv.string,
        vol.Optional(ATTR_SESSION_ID): cv.string,
        vol.Optional(ATTR_AGENT_ID): cv.string,
    }
)

CLEAR_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_SESSION_ID): cv.string,
    }
)

INVOKE_TOOL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TOOL): cv.string,
        vol.Optional(ATTR_ACTION): cv.string,
        vol.Optional(ATTR_ARGS, default={}): dict,
        vol.Optional(ATTR_SESSION_KEY): cv.string,
        vol.Optional(ATTR_DRY_RUN, default=False): cv.boolean,
        vol.Optional(ATTR_MESSAGE_CHANNEL): cv.string,
        vol.Optional(ATTR_ACCOUNT_ID): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the OpenClaw integration."""
    await async_migrate_integration(hass)
    await async_setup_services(hass, config)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OpenClawConfigEntry) -> bool:
    """Set up OpenClaw from a config entry."""
    try:
        client = get_openclaw_client(hass, entry.data)
    except (AuthenticationError, OpenAIError) as err:
        _LOGGER.error("Invalid OpenClaw gateway token: %s", err)
        return False

    entry.runtime_data = client

    # Gateway HTTP client (models/tools/connectivity) + coordinator
    use_ssl = entry.data.get(CONF_USE_SSL, False)
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    api = OpenClawApiClient(
        host=entry.data[CONF_GATEWAY_HOST],
        port=int(entry.data[CONF_GATEWAY_PORT]),
        token=entry.data[CONF_GATEWAY_TOKEN],
        use_ssl=use_ssl,
        verify_ssl=verify_ssl,
        session=session,
        agent_id=entry.data.get(CONF_AGENT_ID, DEFAULT_AGENT_ID),
    )
    coordinator = OpenClawCoordinator(hass, api)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("entries", {})[entry.entry_id] = {
        "client": client,
        "api": api,
        "coordinator": coordinator,
        "entry": entry,
        "entry_id": entry.entry_id,
    }

    # Verify connectivity/auth before forwarding platforms. The gateway exposes
    # GET /v1/models; a connection failure is retried later, an auth failure
    # disables the entry.
    try:
        await client.models.list()
    except AuthenticationError as err:
        _LOGGER.error("OpenClaw gateway rejected the token: %s", err)
        return False
    except APIConnectionError as err:
        raise ConfigEntryNotReady(f"Cannot reach OpenClaw gateway: {err}") from err
    except OpenAIError as err:  # pragma: no cover - defensive
        raise ConfigEntryNotReady(err) from err

    # First data fetch — the coordinator reports offline instead of failing.
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    _async_register_services(hass)
    _async_register_websocket_api(hass)
    hass.async_create_task(_async_register_frontend(hass))

    await async_setup_templates(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload OpenClaw."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        domain_data = hass.data.get(DOMAIN, {})
        domain_data.get("entries", {}).pop(entry.entry_id, None)
    await async_unload_templates(hass)
    return unloaded


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_integration(hass: HomeAssistant) -> None:
    """Migrate integration entry structure from version 1 to version 2."""
    entries = sorted(
        hass.config_entries.async_entries(DOMAIN),
        key=lambda e: e.disabled_by is not None,
    )
    if not any(entry.version == 1 for entry in entries):
        return

    for entry in entries:
        if entry.version != 1:
            continue
        _LOGGER.warning(
            "Migrating OpenClaw config entry %s from version %s to version 2",
            entry.entry_id,
            entry.version,
        )
        subentry = ConfigSubentry(
            data=entry.options,
            subentry_type="conversation",
            title=entry.title,
            unique_id=None,
        )
        hass.config_entries.async_add_subentry(entry, subentry)
        hass.config_entries.async_update_entry(
            entry, title=entry.title, options={}, version=2
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_first_entry_data(hass: HomeAssistant) -> dict[str, Any] | None:
    """Return entry data dict for the first configured OpenClaw entry."""
    domain_data: dict = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.get("entries", {}).values():
        if isinstance(entry_data, dict) and "client" in entry_data:
            return entry_data
    return None


def _resolve_model(entry: ConfigEntry) -> str:
    """Resolve the configured conversation model for an entry."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type == "conversation":
            return subentry.data.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
    return DEFAULT_CHAT_MODEL


def _get_chat_history_store(hass: HomeAssistant) -> dict[str, list[dict[str, str]]]:
    """Return in-memory per-session chat history store."""
    store_key = f"{DOMAIN}_chat_history"
    store = hass.data.get(store_key)
    if store is None:
        store = {}
        hass.data[store_key] = store
    return store


def _append_chat_history(
    hass: HomeAssistant, session_id: str, role: str, content: str
) -> None:
    """Append a message to in-memory chat history."""
    store = _get_chat_history_store(hass)
    history = store.setdefault(session_id, [])
    history.append(
        {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    if len(history) > _MAX_CHAT_HISTORY:
        del history[:-_MAX_CHAT_HISTORY]


def _summarize_tool_result(value: Any, max_len: int = 240) -> str | None:
    """Return compact string preview of a tool result payload."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    text = text.strip()
    if not text:
        return None
    if len(text) > max_len:
        return f"{text[:max_len]}…"
    return text


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register the OpenClaw gateway services (idempotent)."""

    def _normalize_optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    async def handle_send_message(call: ServiceCall) -> None:
        """Handle the openclaw.send_message service call."""
        message: str = call.data[ATTR_MESSAGE]
        session_id: str = call.data.get(ATTR_SESSION_ID) or "default"
        call_agent_id = _normalize_optional_text(call.data.get(ATTR_AGENT_ID))

        entry_data = _get_first_entry_data(hass)
        if not entry_data:
            _LOGGER.error("No OpenClaw integration configured")
            return

        client: AsyncClient = entry_data["client"]
        coordinator: OpenClawCoordinator = entry_data["coordinator"]
        entry: ConfigEntry = entry_data["entry"]
        model = (
            model_for_agent(call_agent_id)
            if call_agent_id
            else _resolve_model(entry)
        )

        store = _get_chat_history_store(hass)
        history = store.setdefault(session_id, [])
        messages: list[dict[str, str]] = [
            {"role": item["role"], "content": item["content"]} for item in history
        ]
        messages.append({"role": "user", "content": message})

        extra_headers: dict[str, str] = {}
        if call_agent_id:
            extra_headers["x-openclaw-agent-id"] = call_agent_id

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                extra_headers=extra_headers or None,
            )
            assistant_message = (
                response.choices[0].message.content if response.choices else None
            ) or ""
            model_used = response.model or model
        except OpenAIError as err:
            _LOGGER.error("Failed to send message to OpenClaw: %s", err)
            assistant_message = f"OpenClaw error: {err}"
            model_used = model

        _append_chat_history(hass, session_id, "user", message)
        _append_chat_history(hass, session_id, "assistant", assistant_message)

        hass.bus.async_fire(
            EVENT_MESSAGE_RECEIVED,
            {
                ATTR_MESSAGE: assistant_message,
                ATTR_SESSION_ID: session_id,
                ATTR_MODEL: model_used,
                ATTR_TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )
        coordinator.update_last_activity()

    async def handle_clear_history(call: ServiceCall) -> None:
        """Handle the openclaw.clear_history service call."""
        session_id: str | None = call.data.get(ATTR_SESSION_ID)
        store = _get_chat_history_store(hass)
        if session_id:
            store.pop(session_id, None)
        else:
            store.clear()

    async def handle_invoke_tool(call: ServiceCall) -> None:
        """Handle the openclaw.invoke_tool service call."""
        tool_name: str = call.data[ATTR_TOOL]
        action: str | None = call.data.get(ATTR_ACTION)
        args: dict[str, Any] = call.data.get(ATTR_ARGS) or {}
        session_key: str | None = call.data.get(ATTR_SESSION_KEY)
        dry_run: bool = bool(call.data.get(ATTR_DRY_RUN, False))
        message_channel: str | None = call.data.get(ATTR_MESSAGE_CHANNEL)
        account_id: str | None = call.data.get(ATTR_ACCOUNT_ID)

        entry_data = _get_first_entry_data(hass)
        if not entry_data:
            _LOGGER.error("No OpenClaw integration configured")
            return

        api: OpenClawApiClient = entry_data["api"]
        coordinator: OpenClawCoordinator = entry_data["coordinator"]

        started = perf_counter()
        ok = False
        result: Any = None
        error_message: str | None = None

        try:
            response = await api.async_invoke_tool(
                tool=tool_name,
                action=action,
                args=args,
                session_key=session_key,
                dry_run=dry_run,
                message_channel=message_channel,
                account_id=account_id,
            )
            ok = bool(response.get("ok", True)) if isinstance(response, dict) else True
            result = response.get("result") if isinstance(response, dict) else response
            if isinstance(response, dict) and response.get("error"):
                error_message = str(response.get("error"))
        except OpenClawApiError as err:
            ok = False
            error_message = str(err)

        duration_ms = int((perf_counter() - started) * 1000)
        coordinator.record_tool_invocation(
            tool_name=tool_name,
            ok=ok,
            duration_ms=duration_ms,
            error_message=error_message,
            result_preview=_summarize_tool_result(result),
        )

        hass.bus.async_fire(
            EVENT_TOOL_INVOKED,
            {
                ATTR_TOOL: tool_name,
                ATTR_ACTION: action,
                ATTR_SESSION_KEY: session_key,
                ATTR_DRY_RUN: dry_run,
                ATTR_OK: ok,
                ATTR_RESULT: result,
                ATTR_ERROR: error_message,
                ATTR_DURATION_MS: duration_ms,
                ATTR_TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )

        if not ok:
            raise OpenClawApiError(error_message or "Tool invocation failed")

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_MESSAGE,
            handle_send_message,
            schema=SEND_MESSAGE_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_HISTORY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_HISTORY,
            handle_clear_history,
            schema=CLEAR_HISTORY_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_INVOKE_TOOL):
        hass.services.async_register(
            DOMAIN,
            SERVICE_INVOKE_TOOL,
            handle_invoke_tool,
            schema=INVOKE_TOOL_SCHEMA,
        )


# ---------------------------------------------------------------------------
# Websocket API (chat card)
# ---------------------------------------------------------------------------


@callback
def _async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register websocket API for chat history retrieval."""
    key = f"{DOMAIN}_ws_registered"
    if hass.data.get(key):
        return
    hass.data[key] = True

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/get_history",
            vol.Optional("session_id"): cv.string,
        }
    )
    @callback
    def websocket_get_history(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        """Return chat history for a session."""
        session_id = msg.get("session_id") or "default"
        history = _get_chat_history_store(hass).get(session_id, [])
        connection.send_result(
            msg["id"], {"session_id": session_id, "messages": history}
        )

    websocket_api.async_register_command(hass, websocket_get_history)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/get_settings",
        }
    )
    @callback
    def websocket_get_settings(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        """Return frontend-related integration settings."""
        connection.send_result(
            msg["id"],
            {
                "language": hass.config.language,
            },
        )

    websocket_api.async_register_command(hass, websocket_get_settings)


# ---------------------------------------------------------------------------
# Frontend registration (Lovelace chat card)
# ---------------------------------------------------------------------------


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register static path + Lovelace resource for the chat card.

    Wrapped entirely in try/except so it can NEVER crash the integration.
    """
    frontend_done_key = f"{DOMAIN}_frontend_registered"
    frontend_task_key = f"{DOMAIN}_frontend_registration_task"

    if hass.data.get(frontend_done_key):
        return

    existing_task = hass.data.get(frontend_task_key)
    if existing_task and not existing_task.done():
        return

    async def _register_with_retries() -> None:
        for _ in range(60):
            url = await _async_register_static_path(hass)
            if url and await _async_add_lovelace_resource(hass, url):
                hass.data[frontend_done_key] = True
                return
            await asyncio.sleep(5)

        _LOGGER.warning(
            "Could not auto-register OpenClaw chat card resource after retries. "
            "Add it manually in Dashboard resources: %s",
            _CARD_URL,
        )

    task = hass.async_create_task(_register_with_retries())
    hass.data[frontend_task_key] = task
    task.add_done_callback(lambda _fut: hass.data.pop(frontend_task_key, None))


async def _async_register_static_path(hass: HomeAssistant) -> str | None:
    """Register the packaged chat-card JS as a static path when HTTP is ready."""
    static_key = f"{DOMAIN}_static_registered"
    if hass.data.get(static_key):
        return _CARD_URL

    if not _CARD_PATH.exists():
        _LOGGER.warning("Chat card JS not found at %s", _CARD_PATH)
        return None

    if hass.http is None:
        return None

    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(_CARD_STATIC_URL, str(_CARD_PATH), cache_headers=True)]
        )
    except (ImportError, AttributeError):  # pragma: no cover - legacy HA
        hass.http.register_static_path(_CARD_STATIC_URL, str(_CARD_PATH), True)

    hass.data[static_key] = True
    _LOGGER.debug("Registered static path: %s", _CARD_STATIC_URL)
    return _CARD_URL


async def _async_add_lovelace_resource(hass: HomeAssistant, url: str) -> bool:
    """Add the card URL to Lovelace's resource store if not already present."""
    lovelace_data = hass.data.get(LOVELACE_DATA) or hass.data.get("lovelace")
    if not lovelace_data:
        return False

    if isinstance(lovelace_data, dict):
        resource_collection = lovelace_data.get("resources")
    else:
        resource_collection = getattr(lovelace_data, "resources", None)

    if resource_collection is None:
        return False

    try:
        existing_items = list(resource_collection.async_items())
        legacy_paths = {
            "/openclaw/openclaw-chat-card.js",
            "/local/openclaw-chat-card.js",
            "/hacsfiles/openclaw/openclaw-chat-card.js",
        }

        for item in existing_items:
            item_id = item.get("id")
            item_url = item.get("url")
            if not item_id or not item_url:
                continue
            if urlsplit(item_url).path in legacy_paths and item_url != url:
                await resource_collection.async_delete_item(item_id)

        existing_urls = {item["url"] for item in resource_collection.async_items()}
        if url in existing_urls:
            return True

        await resource_collection.async_create_item(
            {"res_type": "module", "url": url}
        )
        _LOGGER.info("Auto-registered Lovelace resource: %s", url)
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Could not auto-register Lovelace resource '%s': %s. "
            "Add it manually: Settings → Dashboards → Resources.",
            url,
            err,
        )
        return False
