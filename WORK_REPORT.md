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
5. **Manifest key ordering** — surfaced only after the errors above were fixed
   (hassfest runs the sort check only when the integration has no other
   errors). Reordered the top-level keys to the required *domain, name, then
   alphabetical* order: `domain`, `name`, `after_dependencies`, `codeowners`,
   `config_flow`, `dependencies`, `documentation`, `integration_type`,
   `iot_class`, `issue_tracker`, `requirements`, `version`. (The old file had
   `after_dependencies` after `dependencies`, which is not alphabetical.)

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

**HACS `license` check and the default branch.** The `LICENSE` file is present
on `openclaw-integration` (verified via the contents API: `LICENSE`, 1229 B),
but HACS validates the **repository-level** license object returned by the
GitHub API (`repo.repository_object.attributes["license"]`), which is computed
from the **default branch**. This fork's default branch is `develop`, which does
not contain a `LICENSE` file, so the API returns `license: null` and the check
fails even though the file exists on the feature branch. It will pass
automatically once this branch is merged into `develop`. No file change can fix
it from a non-default branch; do **not** add an `ignore:` entry to the workflow
to mask it.

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
- HACS `topics`/`issues` cannot be satisfied from files (see §11), and the HACS
  `license` check reads the default branch (`develop`), so it clears only after
  this branch is merged.

---

# Continuation — fix ImportError + blocking platform import

Base for this continuation: `openclaw-integration` @
`1df64862a4e93a56f9de006e07b70cf0f9881e47`.

Two load-time defects reported from a real Home Assistant install are fixed.
The previous worker verified only `py_compile`, which cannot catch either
defect; the verification below is deliberately stronger (§17).

## 15. Defect 1 — `ImportError: EVENT_AUTOMATION_REGISTERED`

During the domain rename, `const.py` lost
`EVENT_AUTOMATION_REGISTERED` while `functions/native.py` still imported and
used it (line 23 import, line ~167 `hass.bus.async_fire(...)`), so the whole
integration failed to import.

Restored in `const.py`, following the **new** domain naming convention of its
neighbours:

```python
EVENT_CONVERSATION_FINISHED = "openclaw.conversation.finished"
EVENT_MESSAGE_RECEIVED = f"{DOMAIN}_message_received"
EVENT_TOOL_INVOKED = f"{DOMAIN}_tool_invoked"
EVENT_AUTOMATION_REGISTERED = f"{DOMAIN}_automation_registered"   # added
```

**Chosen value: `EVENT_AUTOMATION_REGISTERED = f"{DOMAIN}_automation_registered"`,
i.e. the runtime string `"openclaw_automation_registered"`.** The old upstream
string `"automation_registered_via_extended_openai_conversation"` was **not**
reintroduced. `grep -rn extended_openai_conversation custom_components/openclaw
hacs.json` is empty (§17.4).

## 16. Defect 2 — blocking `import_module` inside the event loop

`async_forward_entry_setups(entry, PLATFORMS)` triggered a blocking import of
`custom_components.openclaw.conversation` inside the event loop. Fixed the
canonical HA way: the three platform modules are now imported at module top
level in `__init__.py`, so they are already in `sys.modules` before
`async_forward_entry_setups` runs:

```python
from . import ai_task as ai_task, conversation as conversation, sensor as sensor
from .api import OpenClawApiClient, OpenClawApiError
```

The redundant `X as X` aliases are the HA-canonical way to mark an
intentional side-effect import (and keep `ruff` F401 quiet).

### 16.1 Supporting change required to make the fix valid

The prescribed top-level import cannot be placed naively: `conversation.py`
did `from . import OpenClawConfigEntry` **unguarded at runtime**, while
`OpenClawConfigEntry` is defined later in `__init__.py`
(`type OpenClawConfigEntry = ConfigEntry[AsyncClient]`, line ~85). Importing
`conversation` before that line is reached raises a circular `ImportError`
(verified with a minimal reproduction: `from . import sub` before
`type X = int` fails, after it succeeds). `conversation.py` uses the name only
in an annotation (`config_entry: OpenClawConfigEntry`, line 57) under
`from __future__ import annotations`, so it is never evaluated at runtime.

The name was therefore moved under a `TYPE_CHECKING` guard — exactly the
pattern the two sibling platform modules already use (`entity.py:53`,
`ai_task.py:22`):

```python
from typing import TYPE_CHECKING, Any, Literal
...
if TYPE_CHECKING:
    from . import OpenClawConfigEntry
```

This is the "precise form HA expects for this pattern", not an alternative
refactor: without it the mandated top-level import is impossible. No other
code was restructured.

## 17. Verification (this continuation)

### 17.1 Cross-module import audit — static, clean

A `grep` only lists the imports; it does not prove the names exist. An AST audit
(`/tmp/opencode/import_audit.py`) resolves every relative `from .x import a, b`
in the package to its target module and checks each imported name against the
names actually defined there (assignments, defs, classes, PEP 695 `type`
aliases, imports, `TYPE_CHECKING` blocks).

Command:

```bash
python3 /tmp/opencode/import_audit.py
```

Output after the fix:

```
checked 238 relative-import names; failures=0
```

**Before** the `const.py` fix the same audit printed exactly the reported
defect (and nothing else):

```
MISSING NAME    custom_components/openclaw/functions/native.py:23  from const.py import EVENT_AUTOMATION_REGISTERED
checked 235 relative-import names; failures=1
```

The supporting `grep`:

```bash
grep -rn "from \.\.\?const import" custom_components/openclaw/ --include=*.py
```

lists all 16 `const` import sites, including
`functions/native.py:23:from ..const import EVENT_AUTOMATION_REGISTERED`.

### 17.2 Real import of every module — passes

Home Assistant is **not installed** (and was not installed). A minimal stub
tree was built with `sys.modules`/meta-path injection
(`/tmp/opencode/import_harness.py`) that fakes only the missing external
packages (`homeassistant.*`, `openai`, `voluptuous`, `orjson`, `probatio`,
`bs4`, `aiohttp`) with real, subclassable classes, then imports the integration
for real.

Command:

```bash
python3 /tmp/opencode/import_harness.py
```

Output:

```
Step A: platform modules present in sys.modules right after importing the package:
  custom_components.openclaw.ai_task: YES
  custom_components.openclaw.conversation: YES
  custom_components.openclaw.sensor: YES

Step B: explicit import of every module:
  OK    custom_components.openclaw.ai_task
  OK    custom_components/openclaw.api
  OK    custom_components/openclaw.config_flow
  OK    custom_components/openclaw.const
  OK    custom_components/openclaw.conversation
  OK    custom_components/openclaw.coordinator
  OK    custom_components.openclaw.entity
  OK    custom_components.openclaw.exceptions
  OK    custom_components.openclaw.functions
  OK    custom_components.openclaw.functions.base
  OK    custom_components.openclaw.functions.bash
  OK    custom_components.openclaw.functions.composite
  OK    custom_components.openclaw.functions.file
  OK    custom_components.openclaw.functions.native
  OK    custom_components.openclaw.functions.script
  OK    custom_components/openclaw.functions.sqlite
  OK    custom_components/openclaw.functions.template
  OK    custom_components/openclaw.functions.web
  OK    custom_components.openclaw.helpers
  OK    custom_components.openclaw.sensor
  OK    custom_components.openclaw.services
  OK    custom_components/openclaw.skills
  OK    custom_components.openclaw.template

PASS — failures: []
```

Step A is the direct evidence for Defect 2: **before** the fix the three
platforms reported `NO` (the package import did not pull them in, so
`async_forward_entry_setups` imported them in the loop); **after** the fix all
three report `YES`.

Caveat, stated honestly: the stubs satisfy the *import graph* (names resolve,
class bodies execute, module-level statements run), but they are not Home
Assistant. Runtime behaviour (setup, config flow, entities, services) remains
unverified here, as before (§14).

### 17.3 `py_compile`

```bash
find custom_components/openclaw -name "*.py" -print0 | xargs -0 python3 -m py_compile
```

→ clean, exit 0. (Noted only as a floor: `py_compile` is what let both defects
ship, so it is not treated as evidence on its own.)

### 17.4 No legacy domain string

```bash
grep -rn "extended_openai_conversation" custom_components/openclaw hacs.json
```

→ empty, exit 1.

### 17.5 Lint / format regression check

`ruff 0.16.8` (the version CI installs) was run against the component. The
branch already had 11 pre-existing `ruff check` errors and 4 files the formatter
would change (`UP017`/`UP041`/`RUF100`/`I001`, py3.14 PEP 758 `except`
formatting) **before** this change. After this change the count is still **11**;
the only diff is line-number shifts. **No new `ruff check` error and no new
`ruff format` diff was introduced** (the added import line and the
`TYPE_CHECKING` block are format-clean and in the isort-canonical position).

## 18. Files changed in this continuation

- `custom_components/openclaw/const.py` — added `EVENT_AUTOMATION_REGISTERED`.
- `custom_components/openclaw/__init__.py` — top-level platform imports.
- `custom_components/openclaw/conversation.py` — `OpenClawConfigEntry` import
  moved under `TYPE_CHECKING` (required for the top-level import; see §16.1).
- `WORK_REPORT.md` — this section.

Nothing else was touched; `domain` remains `openclaw`, the integration name is
unchanged, no tags were created, and no branch other than
`openclaw-integration` was touched.

---

# Continuation — four gateway/session/privacy defects

Base for this continuation: `openclaw-integration` @
`b0092b9aa716d03419c76bccd5cc4494a8c9ffc4`.

Architecture respected: chat is performed by the `AsyncOpenAI` SDK client from
`helpers.get_openclaw_client()` via `entity.py:_async_handle_chat_log` →
`self._client.chat.completions.create(...)`. `api.py` (aiohttp) is **not** on the
chat path and was not touched. The gateway is stateless per request unless the
request carries an OpenAI `user` string.

## 19. D1 — default agent must delegate (`openclaw/default`), not pin a model

`const.model_for_agent()` previously always returned `openclaw:<agentId>`, which
is an **explicit** model selection that bypasses the gateway's configured
`primary` + `fallbacks` chain. Now:

| call | result |
| --- | --- |
| `model_for_agent(None)` | `openclaw/default` |
| `model_for_agent("main")` (== `DEFAULT_AGENT_ID`) | `openclaw/default` |
| `model_for_agent("")` | `openclaw/default` |
| `model_for_agent("other")` | `openclaw:other` |

`DEFAULT_CHAT_MODEL = model_for_agent(DEFAULT_AGENT_ID)` therefore becomes
`openclaw/default`, and every call site stays consistent automatically because
they all route through the helper / constant:

- `const.py:112` (`DEFAULT_CHAT_MODEL`) and `const.py:287`
  (`DEFAULT_AI_TASK_OPTIONS`).
- `config_flow.py:159-160` (`model = model_for_agent(agent_id)`); the
  subentry defaults `config_flow.py:109/373/497` use `DEFAULT_CHAT_MODEL`.
- `__init__.py:334-335` (`model_for_agent(call_agent_id)` for an explicit
  caller, else `_resolve_model(entry)` which returns the subentry's
  `CONF_CHAT_MODEL`, i.e. `openclaw/default`).

**Parameter-set check (required).** `helpers.get_model_config(model)` ignores its
`model` argument entirely and returns `DEFAULT_MODEL_CONFIG` for every alias
(`helpers.py:36-42`); there is no code anywhere that branches on the `openclaw:`
prefix. So switching the default to `openclaw/default` loses **no** parameter set.
The comment at `const.py:285` ("generic OpenAI-compatible parameter set is used
for all ``openclaw:*`` aliases") remains true.

Docstrings that described the old default were corrected (`DOCS.md` §"Model
aliases", `helpers.get_openclaw_client`). The `openclaw:main` strings still left
in `strings.json` / `translations/en.json` / `services.yaml` are **examples** of
the explicit form, not defaults, so they were intentionally left.

## 20. D2 — remove the literal `"main"` from the service schema

`services.py` `QUERY_IMAGE_SCHEMA`:

```python
vol.Required("model", default=model_for_agent(DEFAULT_AGENT_ID)): cv.string,
```

(`DEFAULT_AGENT_ID` + `model_for_agent` imported from `.const`.) Because of D1
this default is the delegating `openclaw/default`, not `openclaw:main`.
Runtime-verified with a minimal real `voluptuous` shim over the stub import
harness: `query_image model default = 'openclaw/default'`.

## 21. D3 — one gateway session per Home Assistant conversation

`entity._async_handle_chat_log` now derives a stable, namespaced OpenAI `user`
value from the chat log and sends it on every `chat.completions.create` call
(including each tool-call iteration, since `api_kwargs` is built once):

```python
conversation_id = chat_log.conversation_id or self.entity_id
session_user = f"ha:{conversation_id}"
...
api_kwargs = { "model": model, "stream": True,
               "stream_options": {"include_usage": True},
               "user": session_user }
```

`chat_log.conversation_id` is already reachable at the call site (the method
receives `chat_log`), and is the same value already used at
`conversation.py:200` and `ai_task.py:110`, so **both** the conversation agent
and the AI Task map to the same scheme: `user = "ha:" + conversation_id`, i.e.
one gateway session per HA conversation. The `ha:` prefix namespaces the value.
If `conversation_id` is ever empty/absent the fallback is `self.entity_id`
(deterministic per entity) — never a random value, which would recreate the
defect. This mirrors the donor's `payload["user"] = session_id`
(`oc-donor .../api.py:232`), namespaced and made deterministic.

### 21.1 Live gateway proof

Gateway `http://192.168.20.141:18789/v1`; token read from
`/root/.openclaw/openclaw.json` → `gateway.auth.token` (never printed). Baseline
`openclaw sessions list --agent main --active 30 --json` showed **1** active
session (`agent:main:main`). Then the same payload was sent twice with a stable
`user`, and twice without:

```bash
TOKEN=$(python3 -c "import json;print(json.load(open('/root/.openclaw/openclaw.json'))['gateway']['auth']['token'])")
URL=http://192.168.20.141:18789/v1/chat/completions
# WITH user (twice):
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "x-openclaw-agent-id: main" \
  -d '{"model":"openclaw/default","messages":[{"role":"user","content":"Reply with exactly the word: PONG"}],"stream":false,"user":"ha:defect3-proof-20260923"}' \
  "$URL"
# WITHOUT user (twice):
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "x-openclaw-agent-id: main" \
  -d '{"model":"openclaw/default","messages":[{"role":"user","content":"Reply with exactly the word: PONG"}],"stream":false}' \
  "$URL"
```

All four returned `HTTP 200`, `content="PONG"`, `model="openclaw/default"`.
Session-store diffs (real `openclaw sessions list --json`):

| phase | requests | new sessions created |
| --- | --- | --- |
| baseline | — | 1 (`agent:main:main`, pre-existing) |
| 2× **with** `user=ha:defect3-proof-20260923` | 2 | **1** → `agent:main:openai-user:ha:defect3-proof-20260923` |
| 2× **without** `user` | 2 | **2** → `agent:main:openai:44a19786-…`, `agent:main:openai:8e29b208-…` |

So with a stable `user` the second request **reuses** the session derived from
it; without `user` the gateway opens one orphan
`agent:main:openai:<random-uuid>` session **per request** — exactly the reported
defect, now fixed. The session store also showed the resolved model as
`deepseek-v4.1-flash`, the configured `primary`, confirming `openclaw/default`
delegates to the agent's configured chain.

Raw session keys observed after each phase:

```
baseline : agent:main:main
after+user: agent:main:main
            agent:main:openai-user:ha:defect3-proof-20260923
after no-user: agent:main:main
               agent:main:openai-user:ha:defect3-proof-20260923
               agent:main:openai:44a19786-8bb3-4ce6-8bcc-b4c984f7dbbd
               agent:main:openai:8e29b208-b184-46ea-b60d-3e3e866924c6
```

The three test sessions created by this proof were left in place (no
`session delete` was run) to avoid destructive operations; they are clearly
named (`openai-user:ha:defect3-proof-20260923`, and two random-uuid
`openai:` sessions).

## 22. D4 — prompt/message content no longer logged at INFO

Primary fix (`entity.py`, was `_LOGGER.info("Prompt for %s: %s", model,
json.dumps(messages))`): the full prompt is now `_LOGGER.debug`; INFO logs only
coarse signal:

```python
_LOGGER.info("Sending prompt to %s: %d messages, %d chars", model,
             len(messages), len(json.dumps(messages)))
_LOGGER.debug("Prompt for %s: %s", model, json.dumps(messages))
```

Audit of `_LOGGER.info|warning|error` across `custom_components/openclaw/`
(the requested grep) found the same class of leak in three more places, all
fixed to keep INFO signal while removing content:

1. `services.py:77` — `query_image` logged the full prompt messages at INFO →
   INFO now logs message/char counts, content at DEBUG.
2. `services.py:91` — `query_image` logged the entire completion
   (`response.model_dump()`, i.e. assistant content) at INFO → DEBUG.
3. `entity.py:326` — logged all `pending_tool_calls` (model-produced arguments)
   at INFO → INFO now logs only the count, content at DEBUG.
4. `entity.py:401` — a WARNING logged the raw non-string response content →
   now logs only the type (no content).
5. `functions/sqlite.py:95` — logged the fully rendered SQL query (which can
   embed conversation-derived values) at INFO → DEBUG.

The remaining INFO/WARNING/ERROR sites log identifiers, paths, counts, HTTP
status or exception objects only — no prompt/message/token content.

## 23. Verification (this continuation)

1. **AST cross-module import audit** (`/tmp/opencode/import_audit.py`; the
   parser handles `ast.TypeAlias`/PEP 695 for the `type OpenClawConfigEntry`
   alias, so the three `TYPE_CHECKING` importers do not false-positive):

   ```
   checked 240 relative-import names; failures=0
   ```

   (240 = the previous 238 plus the two new `services.py` names
   `DEFAULT_AGENT_ID` and `model_for_agent`.)

2. **Real import of every module** with the stubbed `homeassistant`/`openai`/
   `probatio`/… tree (`/tmp/opencode/import_harness.py`): **23/23 modules
   imported, `PASS — failures: []`**; the three platform modules are still
   preimported by the package (`Step A: YES/YES/YES`).

3. `find custom_components/openclaw -name "*.py" -print0 | xargs -0 python3 -m
   py_compile` → clean (exit 0).

4. `grep -rn "extended_openai_conversation" custom_components/openclaw hacs.json`
   → **empty** (exit 1).

5. Live gateway proof for D3 → §21.1 (real evidence: session-store diffs).

6. `manifest.json` → `domain = "openclaw"` (exact), `name = "OpenClaw OpenAI
   Integration"`, `version = 1.0.0`.

7. `ruff 0.16.8` (the CI version): still **11** pre-existing `check` errors
   (all in `__init__.py`/`api.py`/`conversation.py`/`coordinator.py`, none in the
   files changed here) and `ruff format --check` reports the five changed files
   already formatted. No new lint/format regression.

### 23.1 Honestly unverified

- No Home Assistant runtime here: the full conversation/AI-Task execution path,
  the config flow and the service registration are **static/import-level only**.
  The `user` value is proven correct against the real gateway (§21.1), and the
  SDK call accepts `user`, but the HA→SDK→gateway path was not run inside HA.
- D1 delegation is evidenced by the gateway accepting `openclaw/default` and
  resolving to the configured `primary` (`deepseek-v4.1-flash`). A real
  fallback (primary unavailable → fallback) was **not** forced; only the
  delegating form and primary resolution were observed.
- The `openclaw:main` example strings in `strings.json`,
  `translations/en.json` and `services.yaml` were deliberately left (they are
  examples, not defaults).

## 24. Files changed in this continuation

- `custom_components/openclaw/const.py` — `model_for_agent` delegating default.
- `custom_components/openclaw/services.py` — schema default via constant;
  `query_image` prompt/response logging; `json` import.
- `custom_components/openclaw/entity.py` — stable `user`; prompt/tool-call/
  non-string logging.
- `custom_components/openclaw/helpers.py` — docstring only.
- `custom_components/openclaw/functions/sqlite.py` — rendered-query log level.
- `DOCS.md` — model-alias description.
- `WORK_REPORT.md` — this section.

`domain` remains exactly `openclaw`; the display name is unchanged; no tags were
created and no branch other than `openclaw-integration` was touched.


