"""Minimal HTTP client for the OpenClaw gateway.

Only the endpoints the integration actually needs are implemented:
  * ``GET  /v1/models``       — connection / model discovery
  * ``POST /tools/invoke``    — single-tool invocation service

Chat completions are handled by the OpenAI Python client (see ``helpers.py``),
which keeps the Home Assistant LLM Assist API function-calling path intact.
``/v1/responses`` is intentionally never used: the gateway rejects several
keys (``include``, ``prompt_cache_key``, ``service_tier``,
``safety_identifier``) on that route with HTTP 400.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import API_MODELS, API_TOOLS_INVOKE, DEFAULT_AGENT_ID

_LOGGER = logging.getLogger(__name__)

# Timeout for regular API calls (seconds)
API_TIMEOUT = aiohttp.ClientTimeout(total=10)
# Timeout for tool invocations (long-running)
TOOL_TIMEOUT = aiohttp.ClientTimeout(total=300, sock_read=120)


class OpenClawApiError(Exception):
    """Base exception for OpenClaw API errors."""


class OpenClawConnectionError(OpenClawApiError):
    """Connection to the OpenClaw gateway failed."""


class OpenClawAuthError(OpenClawApiError):
    """Authentication with the OpenClaw gateway failed."""


class OpenClawApiClient:
    """HTTP client for the OpenClaw gateway API."""

    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        use_ssl: bool = False,
        verify_ssl: bool = True,
        session: aiohttp.ClientSession | None = None,
        agent_id: str = DEFAULT_AGENT_ID,
    ) -> None:
        """Initialize the API client."""
        self._host = host
        self._port = port
        self._token = token
        self._use_ssl = use_ssl
        self._verify_ssl = verify_ssl
        self._session = session
        self._agent_id = agent_id
        self._base_url = f"{'https' if use_ssl else 'http'}://{host}:{port}"
        # ssl=False disables cert verification for self-signed certs;
        # ssl=None uses default verification.
        self._ssl_param: bool | None = False if (use_ssl and not verify_ssl) else None

    @property
    def base_url(self) -> str:
        """Return the root URL of the gateway."""
        return self._base_url

    def update_token(self, token: str) -> None:
        """Update the authentication token."""
        self._token = token

    def _headers(
        self,
        agent_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build request headers with auth token and agent ID."""
        effective_agent = agent_id or self._agent_id or DEFAULT_AGENT_ID
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "x-openclaw-agent-id": effective_agent,
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            if self._session is not None and self._session.closed:
                _LOGGER.warning(
                    "Primary aiohttp session unavailable — creating fallback "
                    "session. This may bypass HA connection management"
                )
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        timeout: aiohttp.ClientTimeout = API_TIMEOUT,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make a JSON request to the gateway."""
        session = await self._get_session()
        url = f"{self._base_url}{path}"

        try:
            async with session.request(
                method,
                url,
                headers=self._headers(),
                timeout=timeout,
                ssl=self._ssl_param,
                **kwargs,
            ) as resp:
                if resp.status in (401, 403):
                    raise OpenClawAuthError(
                        "Authentication failed — check gateway token"
                    )
                if resp.status >= 400:
                    text = await resp.text()
                    raise OpenClawApiError(f"API error {resp.status}: {text[:200]}")
                content_type = resp.content_type or ""
                if "json" not in content_type:
                    text = await resp.text()
                    raise OpenClawApiError(
                        f"Unexpected response content type '{content_type}' "
                        f"(expected JSON). The host/port may be wrong or the "
                        f"gateway returned an error page. Response: {text[:200]}"
                    )
                return await resp.json()

        except aiohttp.ClientConnectorCertificateError as err:
            raise OpenClawConnectionError(
                f"SSL certificate verification failed for {url}. If using "
                f"self-signed certificates, disable 'Verify SSL certificate' "
                f"in the integration config. Error: {err}"
            ) from err
        except (
            aiohttp.ClientConnectorError,
            aiohttp.ClientOSError,
            asyncio.TimeoutError,
        ) as err:
            raise OpenClawConnectionError(
                f"Cannot connect to OpenClaw gateway at {url}: {err}"
            ) from err

    async def async_get_models(self) -> dict[str, Any]:
        """Get available models (OpenAI-compatible)."""
        return await self._request("GET", API_MODELS)

    async def async_check_alive(self) -> bool:
        """Lightweight connectivity check — is the gateway process running?"""
        session = await self._get_session()
        try:
            async with session.get(
                self._base_url,
                timeout=API_TIMEOUT,
                ssl=self._ssl_param,
            ) as resp:
                return resp.status < 500
        except (
            aiohttp.ClientConnectorError,
            aiohttp.ClientOSError,
            asyncio.TimeoutError,
        ) as err:
            raise OpenClawConnectionError(
                f"Cannot connect to OpenClaw gateway: {err}"
            ) from err

    async def async_invoke_tool(
        self,
        tool: str,
        action: str | None = None,
        args: dict[str, Any] | None = None,
        session_key: str | None = None,
        dry_run: bool = False,
        message_channel: str | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Invoke a single OpenClaw tool via the gateway HTTP endpoint."""
        payload: dict[str, Any] = {
            "tool": tool,
            "args": args or {},
            "dryRun": bool(dry_run),
        }
        if action:
            payload["action"] = action
        if session_key:
            payload["sessionKey"] = session_key

        headers = self._headers()
        if message_channel:
            headers["x-openclaw-message-channel"] = message_channel
        if account_id:
            headers["x-openclaw-account-id"] = account_id

        session = await self._get_session()
        url = f"{self._base_url}{API_TOOLS_INVOKE}"

        try:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=TOOL_TIMEOUT,
                ssl=self._ssl_param,
            ) as resp:
                if resp.status in (401, 403):
                    raise OpenClawAuthError("Authentication failed")
                if resp.status >= 400:
                    text = await resp.text()
                    raise OpenClawApiError(
                        f"Tool invoke error {resp.status}: {text[:300]}"
                    )

                content_type = resp.content_type or ""
                if "json" not in content_type:
                    text = await resp.text()
                    raise OpenClawApiError(
                        f"Unexpected tool response content type "
                        f"'{content_type}': {text[:300]}"
                    )
                return await resp.json()

        except (
            aiohttp.ClientConnectorError,
            aiohttp.ClientOSError,
            asyncio.TimeoutError,
        ) as err:
            raise OpenClawConnectionError(
                f"Cannot connect to OpenClaw gateway: {err}"
            ) from err
