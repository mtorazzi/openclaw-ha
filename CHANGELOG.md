# Changelog

## 1.0.0

Hard fork of
[`jekalmin/extended_openai_conversation`](https://github.com/jekalmin/extended_openai_conversation),
specialised for the OpenClaw gateway.

### Added

- OpenClaw gateway config flow: host, port (default `18789`), token (secret),
  use SSL, verify SSL, agent ID (default `main`). Base URL derived as
  `http(s)://<host>:<port>/v1`.
- Services `openclaw.send_message`, `openclaw.clear_history` and
  `openclaw.invoke_tool`, adapted from
  [`techartdev/OpenClawHomeAssistantIntegration`](https://github.com/techartdev/OpenClawHomeAssistantIntegration).
- Events `openclaw_message_received` and `openclaw_tool_invoked`.
- Status sensors (status, model, last activity) and tool telemetry sensors
  (last tool, status, duration, invoked-at).
- Bundled Lovelace chat card served at `/openclaw/openclaw-chat-card.js`.

### Changed

- Domain renamed to `openclaw` (directory, `manifest.json`, `const.py`,
  `hass.data` keys, service namespace, entity ids, `services.yaml`,
  `strings.json`, translations, `hacs.json`).
- AI Task structured output now uses `probatio.to_openapi` instead of
  `voluptuous_openapi.convert`, matching HA core after the `probatio`
  migration. Fixes `'_Unsupported' object is not subscriptable` on HA 2026.9.
- AI Task additionally instructs the model to emit JSON only, because the
  OpenClaw gateway forwards but does not enforce `response_format`.
- Conversation/AI Task model aliases use `openclaw:<agent_id>`; the agent is
  also passed via the `x-openclaw-agent-id` header.
- Removed Azure/OpenAI-specific configuration (`api_provider`, `api_version`,
  `organization`, `skip_authentication`, `service_tier`, `reasoning_effort`).
- The integration uses only `POST /v1/chat/completions` and `GET /v1/models`;
  `POST /v1/responses` is never called.
- `manifest.json` requires `openai>=2.21.0` only (dropped
  `voluptuous-openapi`).
- `hacs.json` minimum Home Assistant version `2026.8.0`.

### Preserved

- The upstream LLM Assist API function-calling conversation agent and the
  AI Task entity architecture, including custom functions and the skills
  system.
