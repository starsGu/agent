"""Discover local plugins and expose their MCP configuration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)
PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins"
MAX_SKILL_FILE_SIZE_BYTES = 1024 * 1024


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _resolve_plugin_path(version_dir: Path, configured_path: str) -> Path:
    relative_path = Path(configured_path)
    if relative_path.is_absolute():
        raise ValueError("mcpServers must be relative to the plugin version directory")

    resolved_path = (version_dir / relative_path).resolve()
    if not resolved_path.is_relative_to(version_dir.resolve()):
        raise ValueError("mcpServers must stay inside the plugin version directory")
    return resolved_path


def discover_plugins(
    plugin_root: Path | str = PLUGIN_ROOT,
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    """Load every valid ``plugins/<name>/<version>`` plugin in stable order."""
    root = Path(plugin_root)
    discovered: list[dict[str, Any]] = []
    enabled: dict[str, bool] = {}

    if not root.is_dir():
        logger.info("Plugin directory does not exist: %s", root)
        return discovered, enabled

    for plugin_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for version_dir in sorted(path for path in plugin_dir.iterdir() if path.is_dir()):
            manifest_path = version_dir / ".plugin" / "plugin.json"
            if not manifest_path.is_file():
                logger.warning("Skipping plugin without manifest: %s", version_dir)
                continue

            try:
                manifest = _load_json_object(manifest_path)
                name = manifest["name"]
                version = manifest["version"]
                mcp_path_value = manifest["mcpServers"]
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("name must be a non-empty string")
                if not isinstance(version, str) or not version.strip():
                    raise ValueError("version must be a non-empty string")
                if not isinstance(mcp_path_value, str) or not mcp_path_value.strip():
                    raise ValueError("mcpServers must be a non-empty relative path")

                mcp_path = _resolve_plugin_path(version_dir, mcp_path_value)
                mcp_document = _load_json_object(mcp_path)
                mcp_servers = mcp_document.get("mcpServers")
                if not isinstance(mcp_servers, dict):
                    raise ValueError(f"{mcp_path} must contain an mcpServers object")
                if not all(
                    isinstance(server_name, str)
                    and server_name
                    and isinstance(config, dict)
                    for server_name, config in mcp_servers.items()
                ):
                    raise ValueError("mcpServers must map server names to objects")
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Skipping invalid plugin manifest %s: %s", manifest_path, exc)
                continue

            normalized_name = name.strip()
            discovered.append(
                {
                    "name": normalized_name,
                    "version": version.strip(),
                    "mcpServers": dict(mcp_servers),
                }
            )
            enabled.setdefault(normalized_name, True)

    return discovered, enabled


def _load_skill_frontmatter(path: Path) -> tuple[str, str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"unable to read {path}") from exc

    if len(data) > MAX_SKILL_FILE_SIZE_BYTES:
        raise ValueError(
            f"{path} exceeds the {MAX_SKILL_FILE_SIZE_BYTES}-byte limit"
        )

    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path} must be UTF-8 text") from exc

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} must start with YAML frontmatter")

    try:
        closing_index = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise ValueError(f"{path} has unterminated YAML frontmatter") from exc

    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} has invalid YAML frontmatter") from exc

    if not isinstance(metadata, dict):
        raise ValueError(f"{path} frontmatter must be a YAML object")

    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{path} frontmatter name must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(
            f"{path} frontmatter description must be a non-empty string"
        )
    return name.strip(), description.strip()


def discover_skills(
    discovered_plugins: list[dict[str, Any]],
    plugin_root: Path | str = PLUGIN_ROOT,
) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]]]:
    """Discover valid SKILL.md files owned by already-valid plugins."""

    root = Path(plugin_root)
    discovered: list[dict[str, str]] = []
    records: dict[str, dict[str, Any]] = {}
    valid_plugins = {
        (plugin_config["name"], plugin_config["version"])
        for plugin_config in discovered_plugins
    }

    if not root.is_dir():
        return discovered, records

    for plugin_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for version_dir in sorted(path for path in plugin_dir.iterdir() if path.is_dir()):
            manifest_path = version_dir / ".plugin" / "plugin.json"
            try:
                manifest = _load_json_object(manifest_path)
                plugin_name = manifest["name"].strip()
                plugin_version = manifest["version"].strip()
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue

            if (plugin_name, plugin_version) not in valid_plugins:
                continue

            skills_root = version_dir / "skills"
            if not skills_root.is_dir():
                continue

            resolved_skills_root = skills_root.resolve()
            for skill_path in sorted(skills_root.rglob("SKILL.md")):
                try:
                    resolved_path = skill_path.resolve(strict=True)
                    if not resolved_path.is_relative_to(resolved_skills_root):
                        raise ValueError(
                            f"{skill_path} resolves outside the plugin skills directory"
                        )
                    name, description = _load_skill_frontmatter(resolved_path)
                except (OSError, ValueError) as exc:
                    logger.warning("Skipping invalid skill %s: %s", skill_path, exc)
                    continue

                if name in records:
                    logger.warning(
                        "Ignoring duplicate skill '%s' from plugin '%s'; "
                        "already provided by plugin '%s'",
                        name,
                        plugin_name,
                        records[name]["plugin_name"],
                    )
                    continue

                discovered.append({"name": name, "description": description})
                records[name] = {
                    "name": name,
                    "description": description,
                    "plugin_name": plugin_name,
                    "path": resolved_path,
                    "skill_root_dir": resolved_path.parent,
                }

    return discovered, records


def get_skill_record(name: str) -> dict[str, Any] | None:
    """Return a copy of a registered skill's private runtime metadata."""

    record = _skill_records.get(name)
    return dict(record) if record is not None else None


def get_enabled_skills() -> list[dict[str, str]]:
    """Return public metadata for skills whose owning plugin is enabled."""

    enabled_skills = []
    for skill_metadata in skills:
        record = _skill_records.get(skill_metadata["name"])
        if record is None:
            continue
        if use_plugins.get(record["plugin_name"], False):
            enabled_skills.append(dict(skill_metadata))
    return enabled_skills


plugins, use_plugins = discover_plugins()
skills, _skill_records = discover_skills(plugins)


# @app.get("/system-prompt", response_model=SystemPromptResponse)
# async def getSystemPrompt():
#     return SystemPromptResponse(system_prompt=system_prompt_store.get())
#
#
# @app.post("/system-prompt", response_model=SystemPromptResponse)
# async def updateSystemPrompt(request: SystemPromptRequest):
#     return SystemPromptResponse(
#         system_prompt=system_prompt_store.update(request.system_prompt),
#     )

''' ai不能修改以下设计方案

全局变量 plugins :[{'name':, 'version': ,'mcpServers':}, ]
全局变量 use_plugins: {'name': 'Ture'}
全局变量 skills :[{'name':, 'description':, }, ]

遍历plugins / 里的每个 < name > _plugin，读取其下 < version > /.plugin / plugin.json 里的 < name > < version > < mcpServers > 添加到 plugins, use_plugins 里添加对应的 ‘True’
遍历plugins / 里的每个 < name > _plugin，读取其下 < version > / skills / ... 里的所有 SKILL.md 的 < name > < description >  添加到 skills

fastapi 需要提供接口
GET getPlugins（） 返回全局 plugins 和 use_plugin
POST  enablePlugins('name') use_plugin['name']=Ture, 调用 mcpClient.get_all_mcp() 并且 mcpClient.pending_mcp += 'name'
POST disablePlugins('name') use_plugin['name']=False, 调用 mcpClient.get_all_mcp() 并且 如果有就清除mcpClient.pending_mcp['name']
'''
