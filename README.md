# OpenClaw OpenAI Integration

A Home Assistant custom integration that connects Home Assistant to an
**OpenClaw gateway** and exposes it as:

1. an **AI Task** entity (`ai_task`, `GENERATE_DATA`) — schema-constrained
   data generation for automations, scripts and `ai_task.generate_data`; and
2. a **conversation agent** for Assist / chat, using Home Assistant's LLM
   Assist API with native function calling.

It also ships gateway services, events, status/telemetry sensors and a
bundled Lovelace chat card.

> **This is a hard fork, not an official upstream release.** It is maintained by
> [@mtorazzi](https://github.com/mtorazzi) and published from
> [mtorazzi/openclaw-ha](https://github.com/mtorazzi/openclaw-ha). It is not
> affiliated with, endorsed by, or released by the upstream project.

## Credits and attribution

- **Upstream project** — the conversation/AI Task architecture is forked from
  [`jekalmin/extended_openai_conversation`](https://github.com/jekalmin/extended_openai_conversation).
  The OpenAI/Azure provider plumbing has been replaced with an OpenClaw gateway
  connection; the LLM Assist API function-calling design is preserved.
- **Donor project** — the OpenClaw gateway wiring (connection/auth approach,
  `api.py` HTTP client, `send_message` / `clear_history` / `invoke_tool`
  services, events, coordinator/sensors) and the Lovelace chat card were ported
  and adapted from
  [`techartdev/OpenClawHomeAssistantIntegration`](https://github.com/techartdev/OpenClawHomeAssistantIntegration).
- **Maintainer** — [https://github.com/mtorazzi](https://github.com/mtorazzi)

## Requirements

- Home Assistant **2026.9.0** or newer. The AI Task entity uses the `probatio`
  schema layer that Home Assistant introduced in the `helpers.llm` module in
  2026.9.0 (`probatio` is absent from `homeassistant/helpers/llm.py` in
  2026.8.0), and the code imports `probatio` directly.
- An OpenClaw gateway reachable over the network with the OpenAI-compatible
  **`/v1/chat/completions`** endpoint enabled:

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

### Gateway API contract

The integration uses exactly these gateway endpoints:

| Endpoint | Method | Used for |
| --- | --- | --- |
| `/v1/chat/completions` | `POST` | Chat / conversation / AI Task / `query_image` (via the OpenAI Python client) |
| `/v1/models` | `GET` | Connection validation at setup and the status/model sensors |
| `/tools/invoke` | `POST` | The `openclaw.invoke_tool` service |

It **never** calls `POST /v1/responses`. That endpoint rejects `include`,
`prompt_cache_key`, `service_tier` and `safety_identifier` with HTTP 400, so the
integration does not send them and does not use the Responses API.

> **Caveat:** the gateway forwards `response_format` to the backing agent but
> does **not** enforce JSON schemas. The AI Task therefore prepends an explicit
> "respond with JSON only" instruction containing the schema and strips markdown
> code fences before parsing.

## Installation

### HACS (custom repository)

1. In HACS, open **⋮ → Custom repositories**.
2. Add `https://github.com/mtorazzi/openclaw-ha` as an **Integration**.
3. Install **OpenClaw OpenAI Integration** and restart Home Assistant.

### Manual

Copy `custom_components/openclaw/` into your Home Assistant `config` directory
and restart Home Assistant.

## Setup

1. Go to **Settings → Devices & Services → Add Integration → OpenClaw OpenAI
   Integration**.
2. Fill in the gateway connection details:

   | Field | Default | Notes |
   | --- | --- | --- |
   | Host | `192.168.20.141` | Hostname or IP of the OpenClaw gateway |
   | Port | `18789` | Gateway TCP port |
   | Token | — | `gateway.auth.token` from `openclaw.json` (stored as a secret) |
   | Use SSL | `false` | Connect over HTTPS |
   | Verify SSL certificate | `true` | Disable for self-signed certificates |
   | Agent ID | `main` | Used to build the `openclaw:AGENT_ID` model alias |

   The base URL is derived as `http(s)://<host>:<port>/v1`, and the flow
   validates the connection with `GET /v1/models`.

3. The integration creates two subentries by default — a **conversation agent**
   and an **AI Task agent** — both using the model alias `openclaw:<agent_id>`.
   You can add more of either from the integration's page, and edit the advanced
   options (model, temperature, prompt, functions, skills, …) there. Advanced
   options are not required at setup time.

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

> **Note:** because the gateway does not enforce `response_format`, keep the
> task instructions precise and ask for JSON-only output. The integration adds
> that instruction and strips code fences, but it cannot force the backing agent
> to follow a schema.

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
- `openclaw.conversation.finished` — fired when a conversation turn finishes.
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
`openclaw/get_history` websocket command (settings via `openclaw/get_settings`).

## Troubleshooting

- **"Failed to connect"** — check host/port, that the gateway is running, and
  that `gateway.http.endpoints.chatCompletions.enabled` is `true`.
- **"Invalid authentication"** — the token does not match
  `gateway.auth.token`.
- **AI Task returns "Error with structured response"** — the backing agent
  produced non-JSON output. The gateway does not enforce JSON schemas; make the
  task instructions explicit about JSON-only output.
- **SSL errors** — disable **Verify SSL certificate** for self-signed certs.

## License

MIT. See [LICENSE](LICENSE). This fork keeps the upstream and donor copyright
notices; see [Credits and attribution](#credits-and-attribution).
