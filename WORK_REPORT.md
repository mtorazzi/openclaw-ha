# WORK REPORT — OpenClaw Home Assistant integration

Branch: `openclaw-integration` (in `/root/projects/eoc-wt`, pushed to
`origin` = `https://github.com/mtorazzi/openclaw-ha.git`)
Base: `upstream/develop` @ `8118d9e0457ea1540fe8d14989ec9fa27327f773`

## 1. Summary

Hard fork of `jekalmin/extended_openai_conversation`, specialised for a
standalone OpenClaw gateway. The upstream conversation/AI Task architecture is
preserved (LLM Assist API + function calling). The OpenAI/Azure provider
plumbing is replaced by an OpenClaw gateway connection.

Domain is now `openclaw`; display name `OpenClaw`.

Both required platforms are provided:

1. **AI Task** (`ai_task`, `GENERATE_DATA`) — top priority, fixed.
2. **Conversation agent** for Assist/chat.

## 2. What changed

### R1 — AI Task `probatio` fix (top priority)

`entity.py` previously did:

```python
from voluptuous_openapi import convert
result = convert(schema, custom_serializer=...)
```

On HA 2026.9 the schema is a `probatio.Schema`, and
`llm.selector_serializer` returns `probatio.UNSUPPORTED`, which
`voluptuous_openapi` cannot subscript → `'_Unsupported' object is not
subscriptable`.

Now (mirroring HA core `components/openai_conversation/entity.py`):

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

Verification against the real HA core source and the `probatio` library
(`probatio==0.12.1`, pinned in HA core `package_constraints.txt`):

- `homeassistant/helpers/llm.py` imports `probatio` and
  `selector_serializer` returns `probatio.UNSUPPORTED`; it calls
  `probatio.to_openapi(...)`.
- `probatio/codecs/openapi.py`:
  `def to_openapi(schema, *, custom_serializer=None, openapi_version="3.0",
  strict=False) -> dict[str, Any]` — accepts the same `custom_serializer`
  keyword argument and returns a dict.

Executed proof (downloaded the `probatio` 0.12.1 wheel and ran the real
`_format_structured_output`/`_adjust_schema` functions extracted from
`entity.py` with a `custom_serializer` that returns `probatio.UNSUPPORTED`):

```
type: dict
{
  "type": "object",
  "properties": {
    "country": {"type": "string"},
    "capital": {"type": ["string", "null"]},
    "population_millions": {"type": ["integer", "null"]}
  },
  "required": ["country", "capital", "population_millions"],
  "additionalProperties": false,
  "strict": true
}
PROBATIO FIX VERIFIED: to_openapi returned a dict
```

`grep -rn voluptuous_openapi custom_components/openclaw` finds no call site
(only an explanatory comment). `voluptuous-openapi` was removed from
`manifest.json` requirements.

Because the gateway does **not** enforce `response_format`, the AI Task also
prepends an explicit "respond with JSON only, no markdown fences" instruction
containing the schema, and `ai_task.py` strips code fences / extracts the
outermost JSON object before parsing.

### R2 — Domain rename

- Directory: `custom_components/extended_openai_conversation` →
  `custom_components/openclaw` (via `git mv`, history preserved).
- `DOMAIN = "openclaw"`, display name `OpenClaw`.
- `manifest.json` (`domain`, `name`, `codeowners` `@mtorazzi`,
  `documentation`, `issue_tracker`, version `1.0.0`).
- `hass.data` keys, service namespace (`openclaw.*`), entity ids, template
  global (`openclaw` instead of `extended_openai`), events
  (`openclaw_message_received`, `openclaw_tool_invoked`,
  `openclaw.conversation.finished`), working directory (`openclaw/`),
  skills GitHub constants, `services.yaml`, `strings.json`,
  `translations/*.json`, `hacs.json`, `pyproject.toml`, CI workflow and tests.
- `grep -rn extended_openai_conversation` over the shipped component and
  metadata is empty. The only remaining mentions repo-wide are intentional
  attribution/history in `README.md`/`CHANGELOG.md` and the legacy upstream
  Mintlify site under `docs/` and `examples/` (see §6).

### R3 — OpenClaw gateway config flow

`config_flow.py` user step:

| Field | Default | Selector |
| --- | --- | --- |
| Host (`gateway_host`) | `192.168.20.141` | text |
| Port (`gateway_port`) | `18789` | int 1–65535 |
| Token (`gateway_token`) | — | password (secret) |
| Use SSL (`use_ssl`) | `false` | boolean |
| Verify SSL (`verify_ssl`) | `true` | boolean |
| Agent ID (`agent_id`) | `main` | text |

Base URL derived as `http(s)://<host>:<port>/v1`
(`const.build_base_url`). The existing advanced subentry options (model,
temperature, prompt, functions, skills, context handling, …) remain reachable
but are not required at setup. The provider dropdown and all Azure/OpenAI
specifics (`api_provider`, `api_version`, `organization`, `skip_authentication`,
`service_tier`, `reasoning_effort`, the `change_config` service) were removed.

### R4 — API contract

The integration uses only:

- `POST /v1/chat/completions` (OpenAI Python client, streaming for Assist/AI
  Task, non-streaming for `send_message`/`query_image`);
- `GET /v1/models` (setup validation + status sensor);
- `POST /tools/invoke` (`invoke_tool` service).

`POST /v1/responses` is never called; `include`, `prompt_cache_key`,
`service_tier`, `safety_identifier` are never sent. Model alias
`openclaw:<agent_id>` (default `openclaw:main`) plus the
`x-openclaw-agent-id` header.

### R5 — Ported from the donor (`techartdev/OpenClawHomeAssistantIntegration`)

Ported (minimal, adapted to `openclaw`):

- **Connection/auth approach** — manual config, bearer token, optional
  `x-openclaw-agent-id` header. Implemented via the OpenAI client
  (`default_headers`) so the upstream function-calling path stays intact.
- **`api.py`** — trimmed gateway HTTP client: `GET /v1/models`,
  `POST /tools/invoke`, connectivity ping, auth/connection error types.
- **Services** — `openclaw.send_message`, `openclaw.clear_history`,
  `openclaw.invoke_tool` (donor logic, new domain), plus the upstream
  `query_image` / `reload_skills` / `download_skill`.
- **Events** — `openclaw_message_received`, `openclaw_tool_invoked`.
- **Coordinator + sensors** — gateway status/model, last activity, and tool
  telemetry (last tool, status, duration, invoked-at).
- **Lovelace chat card** — donor's `openclaw-chat-card.js` (already uses the
  `openclaw` domain), served at `/openclaw/openclaw-chat-card.js`, with
  automatic Lovelace resource registration and the `openclaw/get_history` /
  `openclaw/get_settings` websocket commands.

**Not ported:** the donor's bespoke tool-calling loop. It only honours
`execute_service`/`execute_services`, is default-off, and re-injects results
as plain text. The upstream LLM Assist API function calling is strictly better
and is kept.

## 3. Live gateway contract verification

Gateway: `http://192.168.20.141:18789/v1`; token read from
`/root/.openclaw/openclaw.json` → `gateway.auth.token` (48 chars; never
printed or committed).

### 3.1 `GET /v1/models` → 200

```bash
TOKEN=$(python3 -c "import json;print(json.load(open('/root/.openclaw/openclaw.json'))['gateway']['auth']['token'])")
curl -sS -o /tmp/opencode/models.json -w "HTTP %{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" \
  http://192.168.20.141:18789/v1/models
```

Observed: `HTTP 200`

```json
{"object":"list","data":[
  {"id":"openclaw","object":"model","owned_by":"openclaw"},
  {"id":"openclaw/default","object":"model","owned_by":"openclaw"},
  {"id":"openclaw/main","object":"model","owned_by":"openclaw"}
]}
```

### 3.2 `POST /v1/chat/completions` (plain) → 200

```bash
curl -sS -o /tmp/opencode/chat.json -w "HTTP %{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "x-openclaw-agent-id: main" \
  -d '{"model":"openclaw:main","messages":[{"role":"user","content":"Reply with exactly the word: PONG"}],"stream":false}' \
  http://192.168.20.141:18789/v1/chat/completions
```

Observed: `HTTP 200`

```json
{"id":"chatcmpl_...","model":"openclaw:main",
 "choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"PONG"}}],
 "usage":{"prompt_tokens":111777,"completion_tokens":3,"total_tokens":111780}}
```

### 3.3 `POST /v1/chat/completions` with `response_format: json_schema` → 200

```bash
curl -sS -o /tmp/opencode/chat_schema.json -w "HTTP %{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "x-openclaw-agent-id: main" --data @/tmp/opencode/schema_req.json \
  http://192.168.20.141:18789/v1/chat/completions
```

Schema requested: object `{country, capital, population_millions}` (all
required, `additionalProperties: false`).

Observed: `HTTP 200`

```json
{"model":"openclaw:main","finish_reason":"stop",
 "content":"{\"capital\": \"Paris\", \"population_millions\": 2.1}"}
```

Result: content is **valid JSON** but the schema was **NOT honoured** (the
`country` key is missing and the value shape differs). This confirms the
gateway forwards `response_format` but does not enforce it — hence the
integration's JSON-only prompt instruction and fence-stripping parser.

### 3.4 `POST /v1/responses` rejects the forbidden keys (documentation only)

```bash
curl -sS -w "HTTP %{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw:main","input":"hi","include":[]}' \
  http://192.168.20.141:18789/v1/responses
# -> HTTP 400 {"error":{"message":": Unrecognized key: \"include\"","type":"invalid_request_error"}}

curl -sS -w "HTTP %{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw:main","input":"hi","service_tier":"auto"}' \
  http://192.168.20.141:18789/v1/responses
# -> HTTP 400 {"error":{"message":": Unrecognized key: \"service_tier\"","type":"invalid_request_error"}}
```

The integration never calls this endpoint.

## 4. Static verification

- `find custom_components/openclaw -name '*.py' | xargs python3 -m py_compile`
  → all files compile.
- `find tests -name '*.py' | xargs python3 -m py_compile` → all compile.
- `pyflakes` (4.0.0, run from a downloaded wheel) over
  `custom_components/openclaw` → **0 issues** (no undefined names, no unused
  imports).
- `grep -rn extended_openai_conversation custom_components/openclaw hacs.json`
  → empty.
- All JSON files (manifest, strings, translations, hacs) parse; `services.yaml`
  parses.
- Config helpers unit-checked directly: `build_base_url` →
  `http://192.168.20.141:18789/v1`, `model_for_agent("main")` →
  `openclaw:main`.
- `_extract_json` unit-checked for raw / fenced / prose-wrapped responses.

## 5. Config-flow shape

The config flow module compiles and passes pyflakes, and its schema uses
standard HA selectors (`TextSelector`, `NumberSelector`, `BooleanSelector`).
It could not be imported at runtime because Home Assistant is not installed in
this environment (`import homeassistant` → `ModuleNotFoundError`), so the flow
is **not runtime-verified** (see §6).

## 6. Unverified / needs HA runtime

- **Config flow execution**: form rendering, selector round-trips, and the
  `cannot_connect` / `invalid_auth` / `unknown` error mapping. (Schema is
  static-checked only.)
- **Integration setup**: `hass.data` wiring, platform forwarding
  (`ai_task`, `conversation`, `sensor`), template-global registration,
  frontend/static-path and Lovelace resource auto-registration.
- **AI Task end-to-end**: the probatio serialisation is verified in isolation
  against the real library, but the full HA `GenDataTask`/`ChatLog` path is not
  executed.
- **Conversation agent**: LLM Assist API function-calling round trips,
  streaming transform, custom functions and skills.
- **Services/events**: `openclaw.send_message` / `clear_history` /
  `invoke_tool`, event payloads, and the tool telemetry sensors.
- **Chat card**: not loaded in a browser; only static review.
- **`POST /tools/invoke`**: not exercised live (no safe no-op tool was
  identified); the service is wired but the endpoint response shape is
  unverified.
- The legacy upstream Mintlify documentation site under `docs/` and the
  `examples/` snippets still describe the upstream integration and were left
  untouched; they are not part of the shipped component. `README.md`,
  `DOCS.md` and `CHANGELOG.md` are updated for OpenClaw.

## 7. Files added / notable

- Added: `custom_components/openclaw/api.py`, `coordinator.py`, `sensor.py`,
  `www/openclaw-chat-card.js`, `DOCS.md`, `CHANGELOG.md`, `WORK_REPORT.md`.
- Removed: `voluptuous-openapi` requirement; Azure/OpenAI provider config;
  the `change_config` service.
- `hacs.json` minimum HA: `2026.8.0`; `manifest.json` version `1.0.0`.

---

# Continuation — rebrand to "OpenClaw OpenAI Integration" + CI fixes

Base for this continuation: `openclaw-integration` @
`6cc9484c8cc16544249f3edab51da47090f3ea10`.

## 8. R1 — display name (domain unchanged)

The **domain stays `openclaw`**. Only the human-facing label changed to
**`OpenClaw OpenAI Integration`**:

- `hacs.json` → `"name": "OpenClaw OpenAI Integration"`.
- `custom_components/openclaw/manifest.json` → `"name": "OpenClaw OpenAI Integration"`
  (`"domain"` remains exactly `openclaw`).
- `README.md` → H1 is now `# OpenClaw OpenAI Integration`; the intro and
  install/usage sentences present the new name.
- `DOCS.md` → H1 updated for consistency.
- `strings.json` / `translations/en.json` have **no integration-title key**; the
  only `title` present is the config-flow step title
  (`"Connect to OpenClaw gateway"`), which describes the gateway connection, not
  the integration name, so it was left unchanged. Entity names and the
  `const.py` service/event constants were **not** touched.

## 9. R2 — README reflects the fork honestly

`README.md` was rewritten and every claim checked against the shipped code
(see §12). It now contains:

- a prominent **hard-fork / not-official** disclaimer;
- a **Credits and attribution** section linking
  [`jekalmin/extended_openai_conversation`](https://github.com/jekalmin/extended_openai_conversation)
  (upstream architecture) and
  [`techartdev/OpenClawHomeAssistantIntegration`](https://github.com/techartdev/OpenClawHomeAssistantIntegration)
  (donor wiring + chat card), plus the maintainer profile
  [`https://github.com/mtorazzi`](https://github.com/mtorazzi);
- installation pointed at the owner's repo
  `https://github.com/mtorazzi/openclaw-ha`;
- what the integration does (AI Task + conversation agent for an OpenClaw
  gateway), the setup fields, the gateway endpoint table
  (`POST /v1/chat/completions`, `GET /v1/models`, `POST /tools/invoke`) and the
  `/v1/responses` caveat (never used; rejects `include`,
  `prompt_cache_key`, `service_tier`, `safety_identifier` with HTTP 400).

## 10. R3 — CI fixes

Actual failing run: `35906630087` (`hacs` workflow, branch
`openclaw-integration`). Two jobs failed. The real errors (from the run log)
differ slightly from the brief, so both are recorded verbatim.

### 10.1 `validate` (hassfest) — exact errors

```
[ERROR] [DEPENDENCIES] Using component http but it's not in 'dependencies' or 'after_dependencies'
[ERROR] [TRANSLATIONS] Invalid strings.json: the string should not contain HTML at
        'config.step.user.data_description.agent_id'. Got
        'OpenClaw agent to route requests to. Used as the openclaw:<agent_id> model alias.'
[ERROR] [TRANSLATIONS] Invalid translations/en.json: the string should not contain HTML at
        'config.step.user.data_description.agent_id'. ...
```

Fixes:

1. **`http` dependency** — `__init__.py:588` does
   `from homeassistant.components.http import StaticPathConfig`, but `http` was
   not declared. Added `"http"` to `dependencies` (it must be a hard dependency
   because the static path is registered at setup).
2. **HTML in translations** — the literal `<agent_id>` was parsed as an HTML
   tag by `cv.string_with_no_html`. Reworded to
   `"…Used to build the openclaw:AGENT_ID model alias."` in both
   `strings.json` and `translations/en.json`. Only these two files contained
   the offending text.
3. **Unused dependency** — `history` was not imported anywhere (the
   `get_history` native tool uses
   `homeassistant.components.recorder.history`). Removed it. The remaining
   dependencies `ai_task`, `conversation`, `energy`, `recorder`, `rest`,
   `scrape` are each imported by shipped code (`ai_task.py`,
   `conversation.py`, `functions/native.py`, `functions/sqlite.py`,
   `functions/web.py`).
4. **strings.json vs translations/en.json** — key sets are **identical** (171
   keys each). The size difference is only the `[%key:common::…%]` references in
   `strings.json` resolved to literal English in `translations/en.json`, which
   is the expected HA layout. No structural change was needed.

> Note: hassfest (current `dev`) has **no** brand-image validator and does not
> reject oversized brand images; the brand folder is required by **HACS**
> (see 10.2). The `~10 KB` figure in the brief is not enforced by hassfest.

### 10.2 `validate-hacs` (HACS action) — exact errors

```
[ERROR] <Validation topics> failed:  The repository has no valid topics
[ERROR] <Validation issues> failed:  The repository does not have issues enabled
[ERROR] <Validation license> failed:  The repository has no license
[ERROR] <Validation brands> failed:  The repository does not provide brand assets and is not
        listed in the Home Assistant brands repository.
[WARNING] The repository does not contain brands assets at
        custom_components/openclaw/brand/icon.png. Falling back to checking the brands repository.
<Integration mtorazzi/openclaw-ha> 4/9 checks failed
```

Fixes applied (file-based):

1. **Brand assets** — copied byte-identical from the donor to
   `custom_components/openclaw/brand/`:
   - `icon.png` — 256×256, RGBA PNG, **63,133 bytes**
   - `logo.png` — 256×256, RGBA PNG, **63,133 bytes**
   Both satisfy the `home-assistant/brands` rules that apply (PNG, icon 1:1 at
   256×256). The brands guidelines define **dimensions, not a file-size limit**;
   there is no `~10 KB` cap in the current brands repo, HACS action or hassfest,
   so the assets are shipped unmodified. (PIL `optimize=True` only reduced them
   to ~57 KB, so no lossy re-encode was applied.)
2. **License** — the repo had no license file (HACS requires one). Added
   `LICENSE` (MIT) preserving the upstream and donor notices
   (`jekalmin`, `techartdev, Tech Art Ltd`) and the fork copyright.
3. **Topics / Issues** — repository settings, not files. See §11.

### 10.3 `hacs.json` / HA minimum version

`hacs.json` now declares `"homeassistant": "2026.9.0"` (was `2026.8.0`).
Verified against `home-assistant/core`:

- `2026.8.0` is a real, reachable release, **but** `probatio` is **absent**
  from `homeassistant/helpers/llm.py` at `2026.8.0` (`grep -c probatio` → `0`)
  and **present** at `2026.9.0` (`→ 1`). `entity.py` imports `probatio` at
  module import time and the AI Task schema layer depends on it, so `2026.9.0`
  is the genuine minimum.

## 11. R4 — repo metadata to set by hand (cannot be changed from files)

The maintainer must set these in GitHub repo settings; they are the reason
`validate-hacs` still reports failures after the file fixes:

| Setting | Current state | What to set |
| --- | --- | --- |
| **Description** | Inherited from jekalmin (upstream wording) | Replace with an OpenClaw-specific description, e.g. *"OpenClaw OpenAI Integration — AI Task + conversation agent for a Home Assistant OpenClaw gateway."* |
| **Issues** | Disabled | **Enable Issues** (Settings → General → Features → Issues). `manifest.json` `issue_tracker` points at `https://github.com/mtorazzi/openclaw-ha/issues`, which currently 404s until Issues is enabled. |
| **Topics** | Empty | Add e.g. `home-assistant`, `hacs`, `hacs-integration`, `openclaw`, `ai-task`, `conversation`, `llm`. |

(HACS `description` check already passes because a description exists; the
above is about making it accurate. HACS `topics` and `issues` checks will keep
failing until these settings are changed.)

## 12. Verification performed (this continuation)

1. `find custom_components/openclaw -name "*.py" -print0 | xargs -0 python3 -m py_compile`
   → **no errors**.
2. `grep -rn "extended_openai_conversation" custom_components/openclaw hacs.json`
   → **empty** (exit 1). Attribution text in `README.md`/`CHANGELOG.md`/`LICENSE`
   is intentional.
3. `manifest.json` → `domain = openclaw`, `name = OpenClaw OpenAI Integration`,
   `dependencies = [ai_task, conversation, energy, http, recorder, rest, scrape]`.
4. `ls -la custom_components/openclaw/brand/` → `icon.png` and `logo.png`, each
   **63,133 bytes**, 256×256 RGBA.
5. All JSON files parse (`manifest.json`, `strings.json`, `translations/en.json`,
   `hacs.json`); no `<agent_id>` left in any translation.
6. README factual claims quoted against code:
   - *"`POST /v1/chat/completions`"* — `const.py:368 API_CHAT_COMPLETIONS`, used
     by the OpenAI client in `helpers.py`.
   - *"`GET /v1/models`"* — `const.py:367 API_MODELS`; `config_flow.validate_input`
     calls `client.models.list()`; status sensor in `coordinator.py`.
   - *"`POST /tools/invoke`"* — `const.py:369 API_TOOLS_INVOKE`; `api.py:209`.
   - *"never calls `POST /v1/responses`"* — no `/v1/responses` call site exists
     (`api.py` docstring only).
   - Setup fields/defaults — `config_flow.py:87-100` (`gateway_host`
     `192.168.20.141`, `gateway_port` `18789`, token required, `use_ssl` false,
     `verify_ssl` true, `agent_id` `main`) and `const.py:19-26`.
   - Platforms — `__init__.py:81 PLATFORMS = [AI_TASK, CONVERSATION, SENSOR]`.
   - Services — `const.py:265,297,298,338,339,340` and `services.yaml`.
   - Events — `const.py:47-49` (`openclaw.conversation.finished`,
     `openclaw_message_received`, `openclaw_tool_invoked`).
   - Chat card — `__init__.py` registers `/openclaw/openclaw-chat-card.js` and
     the `openclaw/get_history` / `openclaw/get_settings` websocket commands.

## 13. Release steps for the maintainer (do NOT create tags in this task)

`validate-hacs` expects a published release for a HACS integration. **No tag was
created or moved by this task.**

- Integration version is already `1.0.0` in `manifest.json`; `hacs.json` is
  consistent.
- **Chosen tag: `v1.0.0`.** It must **not** collide with the inherited jekalmin
  tags: the origin repo already carries `1.0.0` (plus 79 others such as
  `2.0.0`, `3.0.0-betaN`). The `v`-prefixed tag `v1.0.0` is not among the
  existing 80 tags.

Steps (after review/merge to the default branch):

1. Confirm the default branch contains the reviewed code.
2. Create the release: `gh release create v1.0.0 --repo mtorazzi/openclaw-ha --title "v1.0.0" --notes-from-tag`
   (or the GitHub UI → Releases → Draft a new release → tag `v1.0.0`, target the
   default branch).
3. Re-run the `hacs` workflow (or push the tag) so `validate-hacs` sees a
   published release.

## 14. Still unverified (unchanged from §6)

- No Home Assistant runtime in this environment; config-flow rendering, setup,
  AI Task/conversation end-to-end, services/events and the chat card remain
  **static-checked only**.
- hassfest cannot be run locally (no Docker); the fixes above are derived from
  the exact run-log errors and the hassfest source (`script/hassfest/*`), and
  must be confirmed by CI.
- HACS `topics`/`issues` cannot be satisfied from files (see §11).
