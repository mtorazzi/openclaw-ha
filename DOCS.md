# OpenClaw OpenAI Integration — documentation

## Overview

`openclaw` is a Home Assistant custom integration for an OpenClaw gateway. It
provides:

- an **AI Task** entity (`ai_task`, feature `GENERATE_DATA`) that produces
  schema-constrained data;
- a **conversation agent** for Assist / chat built on Home Assistant's LLM
  Assist API with function calling;
- gateway **services**, **events** and **status sensors**;
- a bundled **Lovelace chat card**.

## Gateway API contract

The integration deliberately restricts itself to the endpoints that are known
to work on the OpenClaw gateway:

| Endpoint | Method | Used for |
| --- | --- | --- |
| `/v1/chat/completions` | POST | Conversation, AI Task, `query_image`, `send_message` |
| `/v1/models` | GET | Setup validation, connection status, model sensor |
| `/tools/invoke` | POST | `invoke_tool` service |

`POST /v1/responses` is **never** called. The gateway rejects the keys
`include`, `prompt_cache_key`, `service_tier` and `safety_identifier` on that
route with HTTP 400, and the integration has no use for it.

### Model aliases

The gateway accepts the alias form `openclaw:<agentId>` and `openclaw/default`.
For the configured default agent the integration sends `openclaw/default`, which
delegates model selection to the gateway so the agent's configured `primary` and
`fallbacks` chain still applies; `openclaw:<agentId>` (an explicit selection that
bypasses the chain) is used only when a specific non-default agent is targeted.
The `x-openclaw-agent-id` header is also sent.

### Structured output

The gateway forwards `response_format` (`json_schema`) to the backing agent but
does **not** enforce it. For AI Task, the integration:

1. serialises the HA `probatio` schema to an OpenAPI schema (see below);
2. sends `response_format` with `type: json_schema`;
3. prepends an explicit "respond with JSON only, no markdown fences" system
   instruction including the schema;
4. strips markdown code fences and extracts the outermost JSON object before
   parsing.

## The `probatio` fix (AI Task)

Home Assistant migrated its schema layer from `voluptuous`/`voluptuous_openapi`
to `probatio`. `llm.selector_serializer` now returns the sentinel
`probatio.UNSUPPORTED`, which `voluptuous_openapi.convert` does not understand;
on HA 2026.9 this raised `'_Unsupported' object is not subscriptable` when the
AI Task serialised its output schema.

The fix (in `entity.py`) mirrors HA core's `openai_conversation` integration:

```python
import probatio

def _format_structured_output(schema, llm_api):
    result = probatio.to_openapi(
        schema,
        custom_serializer=(
            llm_api.custom_serializer if llm_api else llm.selector_serializer
        ),
        openapi_version="3.1.0",
    )
    _adjust_schema(result)
    return result
```

`probatio.to_openapi(schema, *, custom_serializer=None, openapi_version="3.0",
strict=False) -> dict` accepts the same `custom_serializer` keyword argument
and returns a dict. No other call site in the component uses
`voluptuous_openapi`.

## Configuration

### Config entry

| Key | Default | Description |
| --- | --- | --- |
| `gateway_host` | `192.168.20.141` | Gateway host/IP |
| `gateway_port` | `18789` | Gateway port |
| `gateway_token` | — | Bearer token (secret) |
| `use_ssl` | `false` | HTTPS |
| `verify_ssl` | `true` | Verify TLS certificate |
| `agent_id` | `main` | Routed via `openclaw:<agent_id>` |

The base URL is derived as `http(s)://<host>:<port>/v1`.

### Subentries

- **Conversation agent** — prompt template, model, max tokens, max function
  calls per conversation, skills, functions, context threshold/truncation, and
  advanced options (temperature, top_p, extra_body, shorten tool call IDs).
- **AI Task agent** — model, max tokens, advanced options.

## Services

### `openclaw.send_message`

```yaml
service: openclaw.send_message
data:
  message: "Turn off the kitchen lights"
  session_id: "automation-1"   # optional
  agent_id: "main"             # optional override
```

The reply is fired as an `openclaw_message_received` event and stored in the
in-memory session history.

### `openclaw.clear_history`

```yaml
service: openclaw.clear_history
data:
  session_id: "automation-1"   # optional; omit to clear all
```

### `openclaw.invoke_tool`

```yaml
service: openclaw.invoke_tool
data:
  tool: sessions_list
  action: json
  args: {}
```

Fires `openclaw_tool_invoked` and updates the tool telemetry sensors.

### `openclaw.query_image`

Ask a question about one or more images (URL or local allowlisted path).

### `openclaw.reload_skills` / `openclaw.download_skill`

Manage the skills directory under `<config>/openclaw/skills`.

## Events

### `openclaw_message_received`

```yaml
event_type: openclaw_message_received
event_data:
  message: "..."
  session_id: "..."
  model: "openclaw:main"
  timestamp: "..."
```

### `openclaw_tool_invoked`

```yaml
event_type: openclaw_tool_invoked
event_data:
  tool: sessions_list
  action: json
  ok: true
  result: ...
  error: null
  duration_ms: 42
  timestamp: "..."
```

## Chat card

The card bundle lives at `custom_components/openclaw/www/openclaw-chat-card.js`
and is served at `/openclaw/openclaw-chat-card.js`. The integration attempts to
register it as a Lovelace resource automatically; otherwise add it manually:

```text
Settings → Dashboards → ⋮ → Resources → Add resource
URL: /openclaw/openclaw-chat-card.js
Type: JavaScript module
```

Card configuration:

```yaml
type: custom:openclaw-chat-card
title: OpenClaw
session_id: dashboard-1   # optional
```

Websocket commands used by the card:

- `openclaw/get_history` → `{ session_id, messages }`
- `openclaw/get_settings` → `{ language }`

## Sensors

| Sensor | Description |
| --- | --- |
| Status | `online` / `offline` |
| Model | First model from `/v1/models` |
| Last activity | Timestamp of last conversation/message |
| Last tool | Last invoked tool name |
| Last tool status | `ok` / `error` |
| Last tool duration | Duration in ms |
| Last tool invoked | Timestamp of last tool invocation |

## Unverified / requires HA runtime

The following cannot be exercised without a running Home Assistant instance and
are therefore unverified by the build:

- Config flow UI rendering and validation error mapping.
- Entity/platform setup and `hass.data` wiring.
- Actual AI Task schema serialisation at runtime (verified statically against
  the HA core source, not executed).
- Conversation agent function-calling round trips.
- Sensor/coordinator updates and Lovelace resource auto-registration.
