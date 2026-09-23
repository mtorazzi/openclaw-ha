# OpenClaw for Home Assistant

A Home Assistant custom integration that connects Home Assistant to an
**OpenClaw gateway** and exposes it as:

1. an **AI Task** entity (`ai_task`, `GENERATE_DATA`) — schema-constrained
   data generation for automations, scripts and `ai_task.generate_data`; and
2. a **conversation agent** for Assist / chat, using Home Assistant's LLM
   Assist API with native function calling.

This is a hard fork of
[`jekalmin/extended_openai_conversation`](https://github.com/jekalmin/extended_openai_conversation),
specialised for the OpenClaw gateway. The conversation/AI Task architecture is
kept intact; the OpenAI/Azure provider plumbing is replaced with an OpenClaw
gateway connection.

## Requirements

- Home Assistant **2026.8.0** or newer (the AI Task entity relies on the
  `probatio` schema layer introduced in HA core).
- An OpenClaw gateway reachable over the network with the OpenAI-compatible
  API enabled:

  ```json
  {
    "gateway": {
      "http": {
        "endpoints": {
          "chatCompletions": { "enabled": true }
        }
      }
    }
  }
  ```

  The integration uses **only** `POST /v1/chat/completions` and
  `GET /v1/models`. It never calls `POST /v1/responses` (that endpoint rejects
  `include`, `prompt_cache_key`, `service_tier` and `safety_identifier` with
  HTTP 400).

## Installation

### HACS (custom repository)

1. In HACS, open **⋮ → Custom repositories**.
2. Add `https://github.com/mtorazzi/openclaw-ha` as an **Integration**.
3. Install **OpenClaw** and restart Home Assistant.

### Manual

Copy `custom_components/openclaw/` into your Home Assistant `config` directory
and restart Home Assistant.

## Setup

1. Go to **Settings → Devices & Services → Add Integration → OpenClaw**.
2. Fill in the gateway connection details:

   | Field | Default | Notes |
   | --- | --- | --- |
   | Host | `192.168.20.141` | Hostname or IP of the OpenClaw gateway |
   | Port | `18789` | Gateway TCP port |
   | Token | — | `gateway.auth.token` from `openclaw.json` (stored as a secret) |
   | Use SSL | `false` | Connect over HTTPS |
   | Verify SSL certificate | `true` | Disable for self-signed certificates |
   | Agent ID | `main` | Routed as the `openclaw:<agent_id>` model alias |

3. The flow validates the connection with `GET /v1/models`.

The integration creates two subentries by default — a **conversation agent** and
an **AI Task agent** — both using the model alias `openclaw:<agent_id>`. You can
add more of either from the integration's page, and edit the advanced options
(model, temperature, prompt, functions, skills, …) there. Advanced options are
not required at setup time.

## Usage

### AI Task

Point an automation or the `ai_task.generate_data` service at the OpenClaw AI
Task entity:

```yaml
service: ai_task.generate_data
data:
  task_name: classify_message
  entity_id: ai_task.openclaw_ai_task
  instructions: Classify the following message.
  structure:
    message: "I'd like a pizza"
    categories: [food, transport, other]
```

> **Note:** the OpenClaw gateway forwards `response_format` to the backing agent
> but does **not** enforce it. The integration therefore adds an explicit
> "respond with JSON only" instruction to the prompt and strips markdown code
> fences before parsing. Keep instructions precise.

### Conversation agent

Select **OpenClaw Conversation** as the conversation agent for Assist, a voice
satellite or the chat card. Function calling uses Home Assistant's LLM Assist
API (`intent`, exposed entities, custom functions).

### Services

| Service | Description |
| --- | --- |
| `openclaw.send_message` | Send a message to the gateway; the reply is fired as `openclaw_message_received` |
| `openclaw.clear_history` | Clear the in-memory chat history for a session (or all sessions) |
| `openclaw.invoke_tool` | Invoke a single gateway tool via `POST /tools/invoke` |
| `openclaw.query_image` | Ask a question about one or more images |
| `openclaw.reload_skills` / `openclaw.download_skill` | Manage the skills directory |

### Events

- `openclaw_message_received` — fired after `openclaw.send_message` completes and
  after a conversation agent reply.
- `openclaw_tool_invoked` — fired after `openclaw.invoke_tool`, with `tool`,
  `ok`, `duration_ms`, `result`/`error`.

### Sensors

The integration creates a device per config entry with these sensors:

- **Status** — `online` / `offline` (gateway reachability)
- **Model** — model reported by `GET /v1/models`
- **Last activity**
- **Last tool**, **Last tool status**, **Last tool duration**, **Last tool
  invoked** — telemetry from `openclaw.invoke_tool`

## Lovelace chat card

A chat card is bundled and served automatically at
`/openclaw/openclaw-chat-card.js`. On a normal Home Assistant installation the
integration registers it as a dashboard resource automatically.

If automatic registration is unavailable (for example YAML-mode dashboards),
add it manually under **Settings → Dashboards → ⋮ → Resources**:

```text
URL: /openclaw/openclaw-chat-card.js
Resource type: JavaScript module
```

Then add the card to a dashboard:

```yaml
type: custom:openclaw-chat-card
title: OpenClaw
```

The card talks to the gateway through the `openclaw.send_message` service,
subscribes to `openclaw_message_received`, and loads history through the
`openclaw/get_history` websocket command.

## Troubleshooting

- **"Failed to connect"** — check host/port, that the gateway is running, and
  that `gateway.http.endpoints.chatCompletions.enabled` is `true`.
- **"Invalid authentication"** — the token does not match
  `gateway.auth.token`.
- **AI Task returns "Error with structured response"** — the backing agent
  produced non-JSON output. The gateway does not enforce JSON schemas; make the
  task instructions explicit about JSON-only output.
- **SSL errors** — disable **Verify SSL certificate** for self-signed certs.

## Credits

Architecture forked from
[`jekalmin/extended_openai_conversation`](https://github.com/jekalmin/extended_openai_conversation).
OpenClaw gateway wiring adapted from
[`techartdev/OpenClawHomeAssistantIntegration`](https://github.com/techartdev/OpenClawHomeAssistantIntegration).

## License

MIT
