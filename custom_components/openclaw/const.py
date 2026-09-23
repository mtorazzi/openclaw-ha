"""Constants for the OpenClaw integration."""

DOMAIN = "openclaw"
DEFAULT_NAME = "OpenClaw"
DEFAULT_CONVERSATION_NAME = "OpenClaw Conversation"
DEFAULT_AI_TASK_NAME = "OpenClaw AI Task"

# ---------------------------------------------------------------------------
# OpenClaw gateway connection
# ---------------------------------------------------------------------------
CONF_GATEWAY_HOST = "gateway_host"
CONF_GATEWAY_PORT = "gateway_port"
CONF_GATEWAY_TOKEN = "gateway_token"
CONF_USE_SSL = "use_ssl"
CONF_VERIFY_SSL = "verify_ssl"
CONF_AGENT_ID = "agent_id"

DEFAULT_GATEWAY_HOST = "192.168.20.141"
DEFAULT_GATEWAY_PORT = 18789
DEFAULT_USE_SSL = False
DEFAULT_VERIFY_SSL = True
DEFAULT_AGENT_ID = "main"

# Legacy key kept for backwards compatibility with the previous base_url-based
# config entries. The value is always derived from host/port/use_ssl.
CONF_BASE_URL = "base_url"


def build_base_url(host: str, port: int, use_ssl: bool = False) -> str:
    """Return the OpenAI-compatible base URL for the gateway."""
    scheme = "https" if use_ssl else "http"
    return f"{scheme}://{host}:{port}/v1"


def model_for_agent(agent_id: str | None) -> str:
    """Return the OpenClaw model alias for an agent ID.

    The gateway accepts the alias form ``openclaw:<agentId>`` as well as
    ``openclaw/default``. ``openclaw/default`` *delegates* agent selection to
    the gateway, so the agent's configured ``primary`` model and its
    ``fallbacks`` chain still apply. ``openclaw:<agentId>`` is an **explicit**
    selection: it bypasses that chain and pins the request to one model.

    The configured default agent therefore emits the delegating
    ``openclaw/default`` form; the explicit form is reserved for a caller that
    deliberately targets a specific non-default agent.
    """
    if not agent_id or agent_id == DEFAULT_AGENT_ID:
        return "openclaw/default"
    return f"openclaw:{agent_id}"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
EVENT_CONVERSATION_FINISHED = "openclaw.conversation.finished"
EVENT_MESSAGE_RECEIVED = f"{DOMAIN}_message_received"
EVENT_TOOL_INVOKED = f"{DOMAIN}_tool_invoked"
EVENT_AUTOMATION_REGISTERED = f"{DOMAIN}_automation_registered"

# ---------------------------------------------------------------------------
# Conversation / AI Task options
# ---------------------------------------------------------------------------
CONF_PROMPT = "prompt"
DEFAULT_PROMPT = """You are a helpful AI voice assistant of Home Assistant that controls a real home.
Your goal is to proactively improve the user's comfort.

## Environment State
- Current Time: {{now()}}
- Current Area: {{area_id(current_device_id)}}

## Workspace
Your workspace is at: {{openclaw.working_directory()}}

## Guidelines
- Answer in plain text only.
- No symbols or parentheses
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Prefer one sentence

## Personality
- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Behavior Policy
- If the user explicitly names a device and action, execute it directly.
- Otherwise, infer the user's goal and select the most likely target entity, preferring primary environmental controls. Use get_attributes to check adjustable state values alone is not sufficient.
- If the selected entity is already at its limit, evaluate the next most likely entity. Repeat until a viable adjustment is found or all candidates are exhausted.
- Ask user a minimum adjustment proposal about selected entity. If no entity can further improve the situation, inform the user that conditions are already optimal.

## Devices
Available Devices:
```csv
entity_id,name,state,area_id,aliases
{% for entity in openclaw.exposed_entities() -%}
{{ entity.entity_id }},{{ entity.name }},{{ entity.state }},{{area_id(entity.entity_id)}},{{entity.aliases | join('/')}}
{% endfor -%}
```

{%- if skills %}
## Skills
The following skills extend your capabilities. To use a skill, call load_skill with the skill name to read its instructions.
When a skill file references a relative path, resolve it against the skill's location directory (e.g., skill at `/a/b/SKILL.md` references `scripts/run.py` → use `/a/b/scripts/run.py`) and always use the resulting absolute path in bash commands, as relative paths will fail.

<available_skills>
{%- for skill in skills %}
  <skill>
    <name>{{ skill.name }}</name>
    <description>{{ skill.description }}</description>
    <location>{{skill.path}}</location>
  </skill>
 {%- endfor %}
</available_skills>
{% endif %}

{{user_input.extra_system_prompt | default('', true)}}
"""
CONF_CHAT_MODEL = "chat_model"
DEFAULT_CHAT_MODEL = model_for_agent(DEFAULT_AGENT_ID)

DEFAULT_TOKEN_PARAM = "max_tokens"
CONF_MAX_TOKENS = "max_tokens"
DEFAULT_MAX_TOKENS = 500
CONF_TOP_P = "top_p"
DEFAULT_TOP_P = 1
CONF_TEMPERATURE = "temperature"
DEFAULT_TEMPERATURE = 0.5
CONF_MAX_FUNCTION_CALLS_PER_CONVERSATION = "max_function_calls_per_conversation"
DEFAULT_MAX_FUNCTION_CALLS_PER_CONVERSATION = 10
CONF_SHORTEN_TOOL_CALL_ID = "shorten_tool_call_id"
DEFAULT_SHORTEN_TOOL_CALL_ID = False
CONF_FUNCTION_TOOLS = "functions"
# Reference set of client-side function tools for the conversation agent.
#
# This is **not** applied automatically: a conversation with no configured
# ``functions`` value sends no ``tools`` array at all (see
# ``conversation._get_function_tools``). It exists so a user can explicitly
# paste it into the Functions field to opt in. It intentionally contains no
# shell-execution tool: ``bash`` is a reserved OpenClaw gateway tool name and
# the gateway rejects any client tool that collides with its own namespace
# (HTTP 400 "invalid tool configuration").
DEFAULT_CONF_FUNCTION_TOOLS = [
    {
        "spec": {
            "name": "execute_services",
            "description": "Execute service in Home Assistant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "delay": {
                        "type": "object",
                        "description": "Time to wait before execution",
                        "properties": {
                            "hours": {
                                "type": "integer",
                                "minimum": 0,
                            },
                            "minutes": {
                                "type": "integer",
                                "minimum": 0,
                            },
                            "seconds": {
                                "type": "integer",
                                "minimum": 0,
                            },
                        },
                    },
                    "list": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "domain": {
                                    "type": "string",
                                    "description": "The domain of the service.",
                                },
                                "service": {
                                    "type": "string",
                                    "description": "The service to be called",
                                },
                                "service_data": {
                                    "type": "object",
                                    "description": "The service data object to indicate what to control.",
                                    "properties": {
                                        "entity_id": {
                                            "type": "array",
                                            "items": {
                                                "type": "string",
                                                "description": "The entity_id retrieved from available devices. It must start with domain, followed by dot character.",
                                            },
                                        },
                                        "area_id": {
                                            "type": "array",
                                            "items": {
                                                "type": "string",
                                                "description": "The id retrieved from areas. You can specify only area_id without entity_id to act on all entities in that area",
                                            },
                                        },
                                    },
                                },
                            },
                            "required": ["domain", "service", "service_data"],
                        },
                    },
                },
            },
        },
        "function": {"type": "native", "name": "execute_service"},
    },
    {
        "spec": {
            "name": "get_attributes",
            "description": "Get attributes of entity or multiple entities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "array",
                        "description": "entity_id of entity or multiple entities",
                        "items": {"type": "string"},
                    }
                },
                "required": ["entity_id"],
            },
        },
        "function": {
            "type": "template",
            "value_template": "```csv\nentity,attributes\n{%for entity in entity_id%}\n{{entity}},{{states[entity].attributes}}\n{%endfor%}\n```",
        },
    },
    {
        "spec": {
            "name": "load_skill",
            "description": "Load a file from a skill's directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill name",
                    },
                    "file": {
                        "type": "string",
                        "description": "Relative file path within the skill directory",
                    },
                },
                "required": ["name", "file"],
            },
        },
        "function": {
            "type": "read_file",
            "path": "{{openclaw.skill_dir(name)}}/{{file}}",
        },
    },
]

# ---------------------------------------------------------------------------
# Reserved OpenClaw tool names
# ---------------------------------------------------------------------------
# A client-declared function tool whose name collides with a tool that already
# exists in the OpenClaw agent runtime is rejected by the gateway with HTTP 400
# ("invalid tool configuration", see ``isClientToolNameConflictError`` in
# ``dist/agent-tool-definition-adapter-*.mjs``). ``bash`` is the collision that
# broke conversations: it is accepted as an alias for the built-in ``exec``.
#
# The set below is derived from the actual gateway namespace, not guessed:
#   * ``AGENT_RESERVED_TOOL_NAMES`` in
#     ``/usr/lib/node_modules/openclaw/dist/builtin-openclaw-*.mjs``
#     (always present in the embedded runtime): bash, edit, find, grep, ls,
#     read, write.
#   * the core built-in tool groups documented in
#     ``docs/gateway/config-tools/tool-policy.md`` of the OpenClaw package
#     (``group:runtime``, ``group:fs``, ``group:sessions``, ``group:memory``,
#     ``group:web``, ``group:ui``, ``group:automation``, ``group:messaging``,
#     ``group:nodes``, ``group:agents``, ``group:media``) plus the ``cron``
#     alias for ``automations``.
# Names that could not be confirmed as reserved are not included; see
# ``WORK_REPORT.md`` for the provenance and the residual uncertainty.
RESERVED_TOOL_NAMES = frozenset(
    {
        # AGENT_RESERVED_TOOL_NAMES (embedded runtime, always present)
        "bash",
        "edit",
        "find",
        "grep",
        "ls",
        "read",
        "write",
        # group:runtime
        "exec",
        "process",
        "code_execution",
        # group:fs
        "apply_patch",
        # group:sessions
        "sessions",
        "sessions_list",
        "sessions_history",
        "sessions_search",
        "conversations_list",
        "conversations_send",
        "conversations_turn",
        "sessions_send",
        "sessions_spawn",
        "sessions_yield",
        "subagents",
        "session_status",
        "suggest_task",
        "dismiss_task",
        # group:memory
        "memory_search",
        "memory_get",
        # group:web
        "web_search",
        "x_search",
        "web_fetch",
        # group:ui
        "browser",
        "screen",
        "dashboard",
        "terminal",
        "portal",
        "canvas",
        "show_widget",
        # group:automation
        "heartbeat_respond",
        "automations",
        "cron",
        "gateway",
        "plugins",
        "openclaw",
        # group:messaging
        "message",
        # group:nodes
        "nodes",
        "computer",
        # group:agents
        "agents_list",
        "get_goal",
        "create_goal",
        "update_goal",
        "progress_card",
        "ask_user",
        "skill_workshop",
        # group:media
        "view_image",
        "image_generate",
        "music_generate",
        "video_generate",
        "tts",
        "pdf",
    }
)

CONF_CONTEXT_THRESHOLD = "context_threshold"
DEFAULT_CONTEXT_THRESHOLD = 40000
CONTEXT_TRUNCATE_STRATEGIES = [{"key": "clear", "label": "Clear All Messages"}]
CONF_CONTEXT_TRUNCATE_STRATEGY = "context_truncate_strategy"
DEFAULT_CONTEXT_TRUNCATE_STRATEGY = CONTEXT_TRUNCATE_STRATEGIES[0]["key"]

CONF_EXTRA_BODY = "extra_body"
DEFAULT_EXTRA_BODY = ""

SERVICE_QUERY_IMAGE = "query_image"

CONF_PAYLOAD_TEMPLATE = "payload_template"

# Advanced Options
CONF_ADVANCED_OPTIONS = "advanced_options"
DEFAULT_ADVANCED_OPTIONS = False

# Model-specific parameter configurations
# The OpenClaw gateway forwards model aliases to the backing agent; the
# generic OpenAI-compatible parameter set is used for all ``openclaw:*``
# aliases.
DEFAULT_MODEL_CONFIG = {
    "supports_top_p": True,
    "supports_temperature": True,
    "supports_max_tokens": True,
    "supports_max_completion_tokens": False,
}

# AI Task default options (simpler than conversation - no prompt, just model/token settings)
DEFAULT_AI_TASK_OPTIONS = {
    CONF_CHAT_MODEL: DEFAULT_CHAT_MODEL,
    CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
    CONF_ADVANCED_OPTIONS: DEFAULT_ADVANCED_OPTIONS,
}

# Skill System Constants
CONF_SKILLS = "skills"
DEFAULT_SKILLS_DIRECTORY = "skills"
SKILL_FILE_NAME = "SKILL.md"

# Skill Services
SERVICE_RELOAD_SKILLS = "reload_skills"
SERVICE_DOWNLOAD_SKILL = "download_skill"

# GitHub repository for downloadable skills
GITHUB_REPO_OWNER = "mtorazzi"
GITHUB_REPO_NAME = "openclaw-ha"
GITHUB_SKILLS_BRANCH = "develop"
GITHUB_SKILLS_PATH = "examples/skills"

# Working Directory
DEFAULT_WORKING_DIRECTORY = "openclaw/"  # /config/openclaw/

# File system and shell security settings
SHELL_TIMEOUT = 300  # seconds
SHELL_OUTPUT_LIMIT = 10000  # characters
SHELL_DENY_PATTERNS = [
    r"\brm\s+-r",  # Recursive delete
    r"\brm\s+-rf",  # Force recursive delete
    r"\bdel\s+/[fqs]",  # Windows delete with flags
    r"\brmdir\s+/s",  # Windows recursive directory delete
    r"\bformat\b",  # Disk format
    r"\bmkfs\b",  # Make filesystem
    r"\bdiskpart\b",  # Windows disk partition
    r"\bdd\b",  # Disk duplicator
    r"\bshutdown\b",  # System shutdown
    r"\breboot\b",  # System reboot
    r"\bpoweroff\b",  # Power off
    r":\(\)\{.*:\|:.*\}",  # Fork bomb pattern
]

# File system limits
FILE_READ_SIZE_LIMIT = 1024 * 1024  # 1 MB

# Default allowed directories for file operations
DEFAULT_ALLOWED_DIRS = [
    DEFAULT_WORKING_DIRECTORY,  # /config/openclaw/
]

# ---------------------------------------------------------------------------
# OpenClaw gateway services
# ---------------------------------------------------------------------------
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_CLEAR_HISTORY = "clear_history"
SERVICE_INVOKE_TOOL = "invoke_tool"

# Service / event attributes
ATTR_MESSAGE = "message"
ATTR_SOURCE = "source"
ATTR_SESSION_ID = "session_id"
ATTR_MODEL = "model"
ATTR_TIMESTAMP = "timestamp"
ATTR_TOOL = "tool"
ATTR_ACTION = "action"
ATTR_ARGS = "args"
ATTR_SESSION_KEY = "session_key"
ATTR_DRY_RUN = "dry_run"
ATTR_MESSAGE_CHANNEL = "message_channel"
ATTR_ACCOUNT_ID = "account_id"
ATTR_AGENT_ID = "agent_id"
ATTR_OK = "ok"
ATTR_RESULT = "result"
ATTR_ERROR = "error"
ATTR_DURATION_MS = "duration_ms"

# ---------------------------------------------------------------------------
# OpenClaw gateway API endpoints
# ---------------------------------------------------------------------------
# The gateway exposes the OpenAI-compatible endpoints. The integration only
# ever uses /v1/chat/completions and /v1/models; /v1/responses is never
# called (it rejects several keys with HTTP 400).
API_MODELS = "/v1/models"
API_CHAT_COMPLETIONS = "/v1/chat/completions"
API_TOOLS_INVOKE = "/tools/invoke"

# ---------------------------------------------------------------------------
# Coordinator / sensor data keys
# ---------------------------------------------------------------------------
DATA_STATUS = "status"
DATA_MODEL = "model"
DATA_CONNECTED = "connected"
DATA_LAST_ACTIVITY = "last_activity"
DATA_LAST_TOOL_NAME = "last_tool_name"
DATA_LAST_TOOL_STATUS = "last_tool_status"
DATA_LAST_TOOL_DURATION_MS = "last_tool_duration_ms"
DATA_LAST_TOOL_INVOKED_AT = "last_tool_invoked_at"
DATA_LAST_TOOL_ERROR = "last_tool_error"
DATA_LAST_TOOL_RESULT_PREVIEW = "last_tool_result_preview"

DEFAULT_SCAN_INTERVAL = 30  # seconds
