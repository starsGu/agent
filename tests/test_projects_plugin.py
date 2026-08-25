from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from tool import read_file, run_skill_script, skill
from tool.plugin import discover_plugins, discover_skills


PLUGIN_ROOT = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "projects-plugin"
    / "1.0.0"
)
CREATE_PROJECT_SCRIPT = (
    PLUGIN_ROOT
    / "skills"
    / "create-project-skill"
    / "scripts"
    / "create_project.py"
)


def _run_script(root_dir: Path, project_name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CREATE_PROJECT_SCRIPT),
            "--root-dir",
            str(root_dir),
            "--project-name",
            project_name,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_create_project_script_creates_and_reports_verified_project(tmp_path):
    root_dir = tmp_path / "nested" / "projects"

    result = _run_script(root_dir, "demo-project")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    project_dir = root_dir / "demo-project"
    readme_path = project_dir / "README.md"
    assert payload == {
        "ok": True,
        "project_name": "demo-project",
        "project_dir": str(project_dir.resolve()),
        "created_files": [str(readme_path.resolve())],
    }
    assert readme_path.read_text(encoding="utf-8") == (
        "this is a project named 'demo-project'\n"
    )


def test_create_project_script_refuses_to_overwrite_existing_project(tmp_path):
    root_dir = tmp_path / "projects"
    existing_project = root_dir / "existing"
    existing_project.mkdir(parents=True)
    marker = existing_project / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    result = _run_script(root_dir, "existing")

    assert result.returncode == 6
    payload = json.loads(result.stderr)
    assert payload["ok"] is False
    assert payload["error_code"] == "project_already_exists"
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (existing_project / "README.md").exists()


def test_create_project_script_rejects_unsafe_project_name(tmp_path):
    root_dir = tmp_path / "projects"

    result = _run_script(root_dir, "unsafe & name")

    assert result.returncode == 3
    payload = json.loads(result.stderr)
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid_project_name"
    assert not root_dir.exists()


def test_create_project_skill_workflow_uses_agent_tools_end_to_end(tmp_path):
    root_dir = tmp_path / "workflow-projects"
    project_name = "workflow-demo"
    command_result = asyncio.run(
        run_skill_script.ainvoke(
            {
                "skill_name": "create-project-skill",
                "script_path": "scripts/create_project.py",
                "arguments": [
                    "--root-dir",
                    str(root_dir),
                    "--project-name",
                    project_name,
                ],
                "timeout_seconds": 60,
            }
        )
    )

    assert command_result["ok"] is True
    assert command_result["exit_code"] == 0
    payload = json.loads(command_result["stdout"])
    project_dir = Path(payload["project_dir"])

    read_result = read_file.invoke(
        {
            "root_dir": str(project_dir),
            "file_path": "README.md",
            "encoding": "utf-8",
        }
    )

    assert read_result["ok"] is True
    assert read_result["content"] == (
        "this is a project named 'workflow-demo'\n"
    )


def test_projects_plugin_is_discovered_by_project_runtime():
    plugins, enabled = discover_plugins(PLUGIN_ROOT.parents[1])
    projects_plugin = next(
        plugin for plugin in plugins if plugin["name"] == "projects-plugin"
    )

    assert projects_plugin == {
        "name": "projects-plugin",
        "version": "1.0.0",
        "mcpServers": {},
    }
    assert enabled["projects-plugin"] is True

    discovered_skills, records = discover_skills(
        plugins,
        PLUGIN_ROOT.parents[1],
    )
    assert discovered_skills == [
        {
            "name": "create-project-skill",
            "description": (
                "在用户指定的绝对目录 root_dir 下创建名为 project_name 的基础项目目录，"
                "生成并验证 README.md。当用户要求创建、新建或初始化空项目时使用；"
                "不用于初始化特定语言或框架，也不覆盖已有项目。"
            ),
        }
    ]
    assert records["create-project-skill"]["skill_root_dir"] == (
        CREATE_PROJECT_SCRIPT.parents[1].resolve()
    )


def test_registered_create_project_skill_returns_complete_workflow():
    result = skill.invoke({"name": "create-project-skill"})

    assert result["ok"] is True
    assert result["plugin_name"] == "projects-plugin"
    assert Path(result["skill_root_dir"]) == CREATE_PROJECT_SCRIPT.parents[1].resolve()
    assert "## Workflow" in result["content"]
    assert 'python "scripts\\create_project.py"' in result["content"]
    assert "execute_cmd" not in result["content"]
    assert "read_file" in result["content"]
