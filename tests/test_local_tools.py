from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from tool import plugin as plugin_registry
import tool.local_tools as local_tools_module
from tool.local_tools import (
    MAX_COMMAND_OUTPUT_BYTES,
    MAX_FILE_SIZE_BYTES,
    MAX_NODE_CODE_BYTES,
    MAX_PYTHON_CODE_BYTES,
    read_file,
    read_skill_resource,
    run_node,
    run_program,
    run_python,
    run_skill_script,
)


def _invoke_read(root_dir: Path | str, file_path: Path | str, **kwargs):
    return read_file.invoke(
        {
            "root_dir": str(root_dir),
            "file_path": str(file_path),
            **kwargs,
        }
    )


@pytest.fixture
def registered_skill(tmp_path, monkeypatch):
    skill_root = tmp_path / "sample-skill"
    (skill_root / "scripts").mkdir(parents=True)
    monkeypatch.setattr(
        plugin_registry,
        "_skill_records",
        {
            "sample-skill": {
                "name": "sample-skill",
                "description": "test scripts",
                "plugin_name": "sample-plugin",
                "path": skill_root / "SKILL.md",
                "skill_root_dir": skill_root,
            }
        },
    )
    monkeypatch.setattr(
        plugin_registry,
        "use_plugins",
        {"sample-plugin": True},
    )
    return skill_root


def _write_script(skill_root: Path, name: str, content: str) -> Path:
    path = skill_root / "scripts" / name
    path.write_text(content, encoding="utf-8")
    return path


def _run_skill(script_path: str, **kwargs):
    arguments = {
        "skill_name": "sample-skill",
        "script_path": script_path,
        **kwargs,
    }
    return asyncio.run(run_skill_script.ainvoke(arguments))


def _run_python(code: str, working_directory: Path | str, **kwargs):
    return asyncio.run(
        run_python.ainvoke(
            {
                "code": code,
                "working_directory": str(working_directory),
                **kwargs,
            }
        )
    )


def _run_node(code: str, working_directory: Path | str, **kwargs):
    return asyncio.run(
        run_node.ainvoke(
            {
                "code": code,
                "working_directory": str(working_directory),
                **kwargs,
            }
        )
    )


def _run_program(
    program: str,
    working_directory: Path | str,
    arguments: list[str] | None = None,
    **kwargs,
):
    return asyncio.run(
        run_program.ainvoke(
            {
                "program": program,
                "arguments": arguments,
                "working_directory": str(working_directory),
                **kwargs,
            }
        )
    )


def _set_program_allowlist(tmp_path, monkeypatch, document):
    allowlist_path = tmp_path / "program_allowlist.json"
    allowlist_path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(
        local_tools_module,
        "PROGRAM_ALLOWLIST_PATH",
        allowlist_path,
    )
    return allowlist_path


def test_skill_execution_tool_descriptions_explain_parameter_sources():
    assert "latest user message" in run_python.description
    assert "SKILL.md example" in run_python.description
    assert "latest user message" in run_node.description
    assert "SKILL.md JavaScript example" in run_node.description
    assert "node -e <code>" in run_node.description
    assert "first command name" in run_program.description
    assert "separate list item" in run_program.description
    assert "successful skill tool call" in read_skill_resource.description
    assert "relative path" in read_skill_resource.description
    assert "existing scripts/... file" in run_skill_script.description
    assert "run_python" in run_skill_script.description
    assert "run_node" in run_skill_script.description


def test_read_file_supports_relative_and_absolute_paths(tmp_path):
    source = tmp_path / "资料.txt"
    content = "你好，Agent"
    source.write_text(content, encoding="utf-8")

    relative_result = _invoke_read(tmp_path, source.name)
    absolute_result = _invoke_read(tmp_path, source)

    for result in (relative_result, absolute_result):
        assert result["ok"] is True
        assert Path(result["root_dir"]) == tmp_path.resolve()
        assert Path(result["path"]) == source.resolve()
        assert result["encoding"] == "utf-8"
        assert result["size_bytes"] == len(content.encode("utf-8"))
        assert result["content"] == content


def test_read_file_supports_explicit_encoding(tmp_path):
    source = tmp_path / "gbk.txt"
    source.write_bytes("中文".encode("gbk"))

    result = _invoke_read(tmp_path, source.name, encoding="gbk")

    assert result["ok"] is True
    assert result["content"] == "中文"
    assert result["encoding"] == "gbk"


@pytest.mark.parametrize(
    ("file_name", "expected_error"),
    [
        ("missing.txt", "file_not_found"),
        ("folder", "path_not_file"),
    ],
)
def test_read_file_reports_missing_and_non_file_paths(
    tmp_path,
    file_name,
    expected_error,
):
    (tmp_path / "folder").mkdir()

    result = _invoke_read(tmp_path, file_name)

    assert result["ok"] is False
    assert result["error_code"] == expected_error


def test_read_file_rejects_relative_root(tmp_path):
    result = _invoke_read("relative-root", "file.txt")

    assert result["ok"] is False
    assert result["error_code"] == "root_dir_not_absolute"


def test_read_file_rejects_parent_traversal(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = _invoke_read(root, "../outside.txt")

    assert result["ok"] is False
    assert result["error_code"] == "path_outside_root"


def test_read_file_rejects_symlink_escape(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    result = _invoke_read(root, link.name)

    assert result["ok"] is False
    assert result["error_code"] == "path_outside_root"


def test_read_file_rejects_oversized_and_invalid_text(tmp_path):
    oversized = tmp_path / "oversized.txt"
    oversized.write_bytes(b"x" * (MAX_FILE_SIZE_BYTES + 1))
    invalid_utf8 = tmp_path / "invalid.txt"
    invalid_utf8.write_bytes(b"\xff")

    oversized_result = _invoke_read(tmp_path, oversized.name)
    invalid_result = _invoke_read(tmp_path, invalid_utf8.name)

    assert oversized_result["ok"] is False
    assert oversized_result["error_code"] == "file_too_large"
    assert invalid_result["ok"] is False
    assert invalid_result["error_code"] == "decode_failed"


def test_run_python_uses_backend_interpreter_and_requested_cwd(tmp_path):
    result = _run_python(
        "import os, sys\nprint(os.getcwd())\nprint(sys.executable)",
        tmp_path,
    )

    output_lines = result["stdout"].splitlines()
    assert result["ok"] is True
    assert result["runtime"] == "python"
    assert Path(result["working_directory"]) == tmp_path.resolve()
    assert Path(output_lines[0]).resolve() == tmp_path.resolve()
    assert Path(output_lines[1]).resolve() == Path(sys.executable).resolve()


def test_run_python_reports_failure_and_syntax_errors(tmp_path):
    failure = _run_python(
        "import sys\nprint('failure', file=sys.stderr)\nraise SystemExit(7)",
        tmp_path,
    )
    syntax_error = _run_python("if:", tmp_path)

    assert failure["ok"] is False
    assert failure["exit_code"] == 7
    assert "failure" in failure["stderr"]
    assert syntax_error["ok"] is False
    assert syntax_error["exit_code"] != 0
    assert "SyntaxError" in syntax_error["stderr"]


def test_run_python_validates_code_directory_and_timeout(tmp_path):
    blank = _run_python(" ", tmp_path)
    oversized = _run_python("x" * (MAX_PYTHON_CODE_BYTES + 1), tmp_path)
    relative_directory = _run_python("print('x')", "relative-directory")
    invalid_timeout = _run_python("print('x')", tmp_path, timeout_seconds=601)

    assert blank["error_code"] == "invalid_code"
    assert oversized["error_code"] == "code_too_large"
    assert relative_directory["error_code"] == "working_directory_not_absolute"
    assert invalid_timeout["error_code"] == "invalid_timeout"


def test_run_python_times_out_and_truncates_output(tmp_path):
    timed_out = _run_python(
        "import time\nprint('started', flush=True)\ntime.sleep(5)",
        tmp_path,
        timeout_seconds=1,
    )
    truncated = _run_python(
        f"import sys\nsys.stdout.write('x' * {MAX_COMMAND_OUTPUT_BYTES + 1024})",
        tmp_path,
    )

    assert timed_out["ok"] is False
    assert timed_out["timed_out"] is True
    assert "started" in timed_out["stdout"]
    assert truncated["ok"] is True
    assert truncated["stdout_truncated"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_run_node_uses_path_runtime_and_requested_cwd(tmp_path):
    result = _run_node(
        "console.log(process.cwd()); console.log(process.execPath);",
        tmp_path,
    )

    output_lines = result["stdout"].splitlines()
    assert result["ok"] is True
    assert result["runtime"] == "node"
    assert Path(result["working_directory"]) == tmp_path.resolve()
    assert Path(output_lines[0]).resolve() == tmp_path.resolve()
    assert Path(output_lines[1]).resolve() == Path(shutil.which("node")).resolve()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_run_node_reports_failure_syntax_timeout_and_truncation(tmp_path):
    failure = _run_node(
        "console.error('failure'); process.exit(7);",
        tmp_path,
    )
    syntax_error = _run_node("if (", tmp_path)
    timed_out = _run_node(
        "console.log('started'); setTimeout(() => {}, 5000);",
        tmp_path,
        timeout_seconds=1,
    )
    truncated = _run_node(
        f"process.stdout.write('x'.repeat({MAX_COMMAND_OUTPUT_BYTES + 1024}));",
        tmp_path,
    )

    assert failure["ok"] is False
    assert failure["exit_code"] == 7
    assert "failure" in failure["stderr"]
    assert syntax_error["ok"] is False
    assert syntax_error["exit_code"] != 0
    assert timed_out["ok"] is False
    assert timed_out["timed_out"] is True
    assert "started" in timed_out["stdout"]
    assert truncated["ok"] is True
    assert truncated["stdout_truncated"] is True


def test_run_node_validates_code_directory_timeout_and_runtime(
    tmp_path,
    monkeypatch,
):
    blank = _run_node(" ", tmp_path)
    oversized = _run_node("x" * (MAX_NODE_CODE_BYTES + 1), tmp_path)
    relative_directory = _run_node("console.log('x')", "relative-directory")
    invalid_timeout = _run_node(
        "console.log('x')",
        tmp_path,
        timeout_seconds=601,
    )
    monkeypatch.setattr(local_tools_module.shutil, "which", lambda _: None)
    missing_runtime = _run_node("console.log('x')", tmp_path)

    assert blank["error_code"] == "invalid_code"
    assert oversized["error_code"] == "code_too_large"
    assert relative_directory["error_code"] == "working_directory_not_absolute"
    assert invalid_timeout["error_code"] == "invalid_timeout"
    assert missing_runtime["error_code"] == "node_runtime_not_found"


def test_run_program_executes_allowlisted_program_and_reloads_file(
    tmp_path,
    monkeypatch,
):
    allowlist_path = _set_program_allowlist(
        tmp_path,
        monkeypatch,
        {"programs": []},
    )
    monkeypatch.setattr(
        local_tools_module.shutil,
        "which",
        lambda program: sys.executable if program == "test-python" else None,
    )

    denied = _run_program("test-python", tmp_path, ["-c", "print('first')"])
    allowlist_path.write_text(
        json.dumps({"programs": ["test-python"]}),
        encoding="utf-8",
    )
    allowed = _run_program(
        "test-python",
        tmp_path,
        ["-c", "import os; print(os.getcwd())"],
    )

    assert denied["error_code"] == "program_not_allowed"
    assert allowed["ok"] is True
    assert allowed["program"] == "test-python"
    assert Path(allowed["stdout"].strip()).resolve() == tmp_path.resolve()


@pytest.mark.parametrize(
    ("document", "expected_error"),
    [
        ({}, "program_allowlist_invalid"),
        ({"programs": "pdftotext"}, "program_allowlist_invalid"),
        ({"programs": [1]}, "program_allowlist_invalid"),
        ({"programs": ["qpdf", "qpdf"]}, "program_allowlist_duplicate"),
    ],
)
def test_run_program_rejects_invalid_allowlist(
    tmp_path,
    monkeypatch,
    document,
    expected_error,
):
    _set_program_allowlist(tmp_path, monkeypatch, document)

    result = _run_program("qpdf", tmp_path, [])

    assert result["error_code"] == expected_error


def test_run_program_reports_missing_and_malformed_allowlist(
    tmp_path,
    monkeypatch,
):
    missing_path = tmp_path / "missing.json"
    monkeypatch.setattr(
        local_tools_module,
        "PROGRAM_ALLOWLIST_PATH",
        missing_path,
    )
    missing = _run_program("qpdf", tmp_path, [])

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{", encoding="utf-8")
    monkeypatch.setattr(
        local_tools_module,
        "PROGRAM_ALLOWLIST_PATH",
        malformed_path,
    )
    malformed = _run_program("qpdf", tmp_path, [])

    assert missing["error_code"] == "program_allowlist_not_found"
    assert malformed["error_code"] == "program_allowlist_invalid_json"


def test_run_program_validates_program_arguments_and_availability(
    tmp_path,
    monkeypatch,
):
    _set_program_allowlist(
        tmp_path,
        monkeypatch,
        {"programs": ["missing-program"]},
    )
    monkeypatch.setattr(local_tools_module.shutil, "which", lambda program: None)

    path_program = _run_program("folder/program", tmp_path, [])
    invalid_arguments = _run_program("missing-program", tmp_path, ["bad\0arg"])
    missing = _run_program("missing-program", tmp_path, [])

    assert path_program["error_code"] == "invalid_program"
    assert invalid_arguments["error_code"] == "invalid_arguments"
    assert missing["error_code"] == "program_not_found"


def test_run_program_times_out(tmp_path, monkeypatch):
    _set_program_allowlist(
        tmp_path,
        monkeypatch,
        {"programs": ["test-python"]},
    )
    monkeypatch.setattr(
        local_tools_module.shutil,
        "which",
        lambda program: sys.executable,
    )

    result = _run_program(
        "test-python",
        tmp_path,
        ["-c", "import time; print('started', flush=True); time.sleep(5)"],
        timeout_seconds=1,
    )

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert "started" in result["stdout"]


def test_read_skill_resource_reads_registered_text_resource(
    registered_skill,
):
    resource = registered_skill / "FORMS.md"
    resource.write_text("表单说明", encoding="utf-8")

    result = read_skill_resource.invoke(
        {"skill_name": "sample-skill", "resource_path": "FORMS.md"}
    )

    assert result["ok"] is True
    assert result["skill_name"] == "sample-skill"
    assert result["plugin_name"] == "sample-plugin"
    assert Path(result["path"]) == resource.resolve()
    assert result["content"] == "表单说明"


def test_read_skill_resource_rejects_unknown_disabled_and_unsafe_paths(
    registered_skill,
):
    unknown = read_skill_resource.invoke(
        {"skill_name": "missing", "resource_path": "FORMS.md"}
    )
    absolute = read_skill_resource.invoke(
        {
            "skill_name": "sample-skill",
            "resource_path": str((registered_skill / "FORMS.md").resolve()),
        }
    )
    traversal = read_skill_resource.invoke(
        {"skill_name": "sample-skill", "resource_path": "../FORMS.md"}
    )
    plugin_registry.use_plugins["sample-plugin"] = False
    disabled = read_skill_resource.invoke(
        {"skill_name": "sample-skill", "resource_path": "FORMS.md"}
    )

    assert unknown["error_code"] == "skill_not_found"
    assert absolute["error_code"] == "resource_path_not_relative"
    assert traversal["error_code"] == "resource_path_parent_traversal"
    assert disabled["error_code"] == "plugin_disabled"


def test_read_skill_resource_rejects_missing_large_and_invalid_text(
    registered_skill,
):
    large = registered_skill / "large.txt"
    large.write_bytes(b"x" * (MAX_FILE_SIZE_BYTES + 1))
    invalid = registered_skill / "invalid.txt"
    invalid.write_bytes(b"\xff")

    missing_result = read_skill_resource.invoke(
        {"skill_name": "sample-skill", "resource_path": "missing.txt"}
    )
    large_result = read_skill_resource.invoke(
        {"skill_name": "sample-skill", "resource_path": "large.txt"}
    )
    invalid_result = read_skill_resource.invoke(
        {"skill_name": "sample-skill", "resource_path": "invalid.txt"}
    )

    assert missing_result["error_code"] == "resource_not_found"
    assert large_result["error_code"] == "file_too_large"
    assert invalid_result["error_code"] == "decode_failed"


def test_read_skill_resource_rejects_symlink_escape(
    registered_skill,
):
    outside = registered_skill.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = registered_skill / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    result = read_skill_resource.invoke(
        {"skill_name": "sample-skill", "resource_path": "linked.txt"}
    )

    assert result["error_code"] == "resource_outside_skill"


def test_run_skill_script_executes_python_with_arguments_and_skill_cwd(
    registered_skill,
):
    script = _write_script(
        registered_skill,
        "report.py",
        "import os, sys\n"
        "print(os.getcwd())\n"
        "print(sys.argv[1])\n"
        "print('failure', file=sys.stderr)\n"
        "raise SystemExit(7)\n",
    )

    result = _run_skill("scripts/report.py", arguments=["hello world"])

    assert result["ok"] is False
    assert result["exit_code"] == 7
    assert Path(result["stdout"].splitlines()[0]).resolve() == registered_skill.resolve()
    assert "hello world" in result["stdout"]
    assert "failure" in result["stderr"]
    assert result["skill_name"] == "sample-skill"
    assert result["plugin_name"] == "sample-plugin"
    assert result["runtime"] == "python"
    assert Path(result["script_path"]) == script.resolve()


def test_run_skill_script_validates_registration_path_type_and_timeout(
    registered_skill,
):
    outside = registered_skill.parent / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")
    unsupported = _write_script(registered_skill, "notes.txt", "not executable")

    unknown = asyncio.run(
        run_skill_script.ainvoke(
            {"skill_name": "missing", "script_path": "scripts/test.py"}
        )
    )
    escaped = _run_skill(str(outside))
    unsupported_result = _run_skill(str(unsupported))
    invalid_timeout = _run_skill("scripts/missing.py", timeout_seconds=601)

    assert unknown["error_code"] == "skill_not_found"
    assert escaped["error_code"] == "script_outside_skill"
    assert unsupported_result["error_code"] == "unsupported_script_type"
    assert invalid_timeout["error_code"] == "invalid_timeout"


def test_run_skill_script_rejects_disabled_plugin(registered_skill):
    plugin_registry.use_plugins["sample-plugin"] = False

    result = _run_skill("scripts/missing.py")

    assert result["error_code"] == "plugin_disabled"


def test_run_skill_script_times_out_and_returns_partial_output(registered_skill):
    _write_script(
        registered_skill,
        "slow.py",
        "import time\nprint('started', flush=True)\ntime.sleep(5)\n",
    )

    result = _run_skill("scripts/slow.py", timeout_seconds=1)

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert "started" in result["stdout"]
    assert result["duration_ms"] >= 900


def test_run_skill_script_truncates_stdout_and_stderr(registered_skill):
    output_size = MAX_COMMAND_OUTPUT_BYTES + 1024
    _write_script(
        registered_skill,
        "large.py",
        "import sys\n"
        f"sys.stdout.write('o' * {output_size})\n"
        f"sys.stderr.write('e' * {output_size})\n",
    )

    result = _run_skill("scripts/large.py")

    assert result["ok"] is True
    assert len(result["stdout"].encode(errors="replace")) <= MAX_COMMAND_OUTPUT_BYTES
    assert len(result["stderr"].encode(errors="replace")) <= MAX_COMMAND_OUTPUT_BYTES
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True


@pytest.mark.skipif(os.name != "nt", reason="CMD scripts require Windows")
def test_run_skill_script_executes_cmd_script(registered_skill):
    _write_script(registered_skill, "echo.cmd", "@echo off\necho %~1\n")

    result = _run_skill("scripts/echo.cmd", arguments=["hello world"])

    assert result["ok"] is True
    assert result["runtime"] == "cmd"
    assert "hello world" in result["stdout"]


def test_run_skill_script_executes_powershell_script(registered_skill):
    _write_script(registered_skill, "echo.ps1", "Write-Output $args[0]\n")

    result = _run_skill("scripts/echo.ps1", arguments=["hello world"])
    if result.get("error_code") == "runtime_not_found":
        pytest.skip("PowerShell is unavailable")

    assert result["ok"] is True
    assert result["runtime"] == "powershell"
    assert "hello world" in result["stdout"]
