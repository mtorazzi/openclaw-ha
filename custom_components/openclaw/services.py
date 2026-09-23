"""Services for the OpenClaw integration."""

import base64
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from openai._exceptions import OpenAIError
import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    GITHUB_REPO_NAME,
    GITHUB_REPO_OWNER,
    GITHUB_SKILLS_BRANCH,
    GITHUB_SKILLS_PATH,
    SERVICE_DOWNLOAD_SKILL,
    SERVICE_QUERY_IMAGE,
    SERVICE_RELOAD_SKILLS,
)

QUERY_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry"): selector.ConfigEntrySelector(
            {
                "integration": DOMAIN,
            }
        ),
        vol.Required("model", default="openclaw:main"): cv.string,
        vol.Required("prompt"): cv.string,
        vol.Required("images"): vol.All(cv.ensure_list, [{"url": cv.string}]),
        vol.Optional("max_tokens", default=300): cv.positive_int,
    }
)

RELOAD_SKILLS_SCHEMA = vol.Schema({})

DOWNLOAD_SKILL_SCHEMA = vol.Schema(
    {
        vol.Required("skill_name"): cv.string,
    }
)

_LOGGER = logging.getLogger(__package__)


async def async_setup_services(hass: HomeAssistant, config: ConfigType) -> None:
    """Set up services for the OpenClaw integration."""

    async def query_image(call: ServiceCall) -> ServiceResponse:
        """Query an image."""
        try:
            model = call.data["model"]
            images = [
                {"type": "image_url", "image_url": to_image_param(hass, image)}
                for image in call.data["images"]
            ]

            messages = [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": call.data["prompt"]}, *images],
                }
            ]
            _LOGGER.info("Prompt for %s: %s", model, messages)

            entry = hass.config_entries.async_get_entry(call.data["config_entry"])
            if entry is None:
                raise HomeAssistantError("Config entry not found")

            client = entry.runtime_data

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=call.data["max_tokens"],
            )
            response_dict: dict = response.model_dump()
            _LOGGER.info("Response %s", response_dict)
        except OpenAIError as err:
            raise HomeAssistantError(f"Error generating image: {err}") from err

        return response_dict

    async def reload_skills(call: ServiceCall) -> ServiceResponse:
        """Reload skills from the user skill directory."""
        from .skills import SkillManager

        skill_manager = await SkillManager.async_get_instance(hass)
        await skill_manager.async_load_skills()

        return {
            "loaded_skills": len(skill_manager.get_all_skills()),
        }

    async def download_skill(call: ServiceCall) -> ServiceResponse:
        """Download a skill from the GitHub repository."""
        from .skills import SkillManager

        skill_name = call.data["skill_name"]
        session = async_get_clientsession(hass)

        # Fetch skill directory contents from GitHub API
        api_url = (
            f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
            f"/contents/{GITHUB_SKILLS_PATH}/{skill_name}"
            f"?ref={GITHUB_SKILLS_BRANCH}"
        )

        downloaded_files: list[str] = []

        async def _download_directory(url: str, local_dir: Path) -> None:
            """Recursively download a directory from GitHub."""
            async with session.get(url) as resp:
                if resp.status == 404:
                    raise HomeAssistantError(
                        f"Skill `{skill_name}` not found in repository"
                    )
                if resp.status != 200:
                    raise HomeAssistantError(
                        f"Failed to fetch skill from GitHub (HTTP {resp.status})"
                    )
                items = await resp.json()

            if not isinstance(items, list):
                raise HomeAssistantError(
                    f"Unexpected response from GitHub for skill `{skill_name}`"
                )

            for item in items:
                item_path = local_dir / item["name"]
                if item["type"] == "file":
                    # Download file content
                    async with session.get(item["download_url"]) as file_resp:
                        if file_resp.status != 200:
                            raise HomeAssistantError(
                                f"Failed to download `{item['path']}`"
                            )
                        content = await file_resp.read()

                    await hass.async_add_executor_job(
                        _write_file_sync, item_path, content
                    )
                    downloaded_files.append(str(item["path"]))
                elif item["type"] == "dir":
                    # Recurse into subdirectory
                    await _download_directory(item["url"], item_path)

        def _write_file_sync(file_path: Path, content: bytes) -> None:
            """Write file content to disk (run in executor)."""
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)

        # Determine target directory
        skill_manager = await SkillManager.async_get_instance(hass)
        target_dir = skill_manager.user_skills_dir / skill_name

        _LOGGER.info("Downloading skill `%s` to %s", skill_name, target_dir)

        try:
            await _download_directory(api_url, target_dir)
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to download skill `{skill_name}`: {err}"
            ) from err

        # Reload skills after download
        await skill_manager.async_load_skills()

        _LOGGER.info(
            "Successfully downloaded skill `%s` (%d files)",
            skill_name,
            len(downloaded_files),
        )

        return {
            "skill_name": skill_name,
            "downloaded_files": downloaded_files,
            "target_directory": str(target_dir),
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_QUERY_IMAGE,
        query_image,
        schema=QUERY_IMAGE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RELOAD_SKILLS,
        reload_skills,
        schema=RELOAD_SKILLS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_SKILL,
        download_skill,
        schema=DOWNLOAD_SKILL_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


def to_image_param(hass: HomeAssistant, image: dict) -> dict:
    """Convert url to base64 encoded image if local."""
    url = image["url"]

    if urlparse(url).scheme in cv.EXTERNAL_URL_PROTOCOL_SCHEMA_LIST:
        return image

    if not hass.config.is_allowed_path(url):
        raise HomeAssistantError(
            f"Cannot read `{url}`, no access to path; "
            "`allowlist_external_dirs` may need to be adjusted in "
            "`configuration.yaml`"
        )
    if not Path(url).exists():
        raise HomeAssistantError(f"`{url}` does not exist")
    mime_type, _ = mimetypes.guess_type(url)
    if mime_type is None or not mime_type.startswith("image"):
        raise HomeAssistantError(f"`{url}` is not an image")

    image["url"] = f"data:{mime_type};base64,{encode_image(url)}"
    return image


def encode_image(image_path: str) -> str:
    """Convert to base64 encoded image."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")
