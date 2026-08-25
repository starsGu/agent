"""Local filesystem and Windows command tools exposed to the agent."""

from __future__ import annotations

import asyncio
import codecs
import json
import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from langchain.tools import tool

from . import plugin


MAX_FILE_SIZE_BYTES = 1024 * 1024
MAX_COMMAND_OUTPUT_BYTES = 256 * 1024
MAX_NODE_CODE_BYTES = 256 * 1024
MAX_PYTHON_CODE_BYTES = 256 * 1024
MIN_COMMAND_TIMEOUT_SECONDS = 1
MAX_COMMAND_TIMEOUT_SECONDS = 600
PROGRAM_ALLOWLIST_PATH = Path(__file__).with_name("program_allowlist.json")


def _build_skill_tool_description() -> str:
    enabled_skills = plugin.get_enabled_skills()
    skill_list = "\n".join(
        f"- {item['name']}: {item['description']}"
        for item in enabled_skills
    ) or "- No enabled skills are currently available."
    return (
        "Load the complete SKILL.md instructions for a task-specific skill. "
        "Call this tool when the user's request matches one of the enabled Skill "
        "descriptions below, then follow the returned workflow and use its "
        "skill_root_dir to locate bundled scripts or resources. This tool only "
        "loads instructions; it does not execute them. Enabled Skills:\n"
        f"{skill_list}"
    )


class _ToolInputError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _error_result(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": code,
        "message": message,
    }


def _resolve_root(root_dir: str) -> Path:
    if not isinstance(root_dir, str) or not root_dir.strip():
        raise _ToolInputError("invalid_root_dir", "root_dir must not be blank")

    requested_root = Path(root_dir)
    if not requested_root.is_absolute():
        raise _ToolInputError(
            "root_dir_not_absolute",
            "root_dir must be an absolute path",
        )

    try:
        resolved_root = requested_root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise _ToolInputError(
            "root_dir_not_found",
            f"root_dir does not exist: {requested_root}",
        ) from exc
    except OSError as exc:
        raise _ToolInputError(
            "root_dir_unavailable",
            f"root_dir cannot be resolved: {requested_root}",
        ) from exc

    if not resolved_root.is_dir():
        raise _ToolInputError(
            "root_dir_not_directory",
            f"root_dir is not a directory: {resolved_root}",
        )
    return resolved_root


def _resolve_file(root: Path, file_path: str) -> Path:
    if not isinstance(file_path, str) or not file_path.strip():
        raise _ToolInputError("invalid_file_path", "file_path must not be blank")

    requested_file = Path(file_path)
    candidate = requested_file if requested_file.is_absolute() else root / requested_file
    try:
        resolved_file = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise _ToolInputError(
            "file_not_found",
            f"file does not exist: {candidate}",
        ) from exc
    except OSError as exc:
        raise _ToolInputError(
            "file_unavailable",
            f"file cannot be resolved: {candidate}",
        ) from exc

    try:
        resolved_file.relative_to(root)
    except ValueError as exc:
        raise _ToolInputError(
            "path_outside_root",
            f"file must stay inside root_dir: {resolved_file}",
        ) from exc

    if not resolved_file.is_file():
        raise _ToolInputError(
            "path_not_file",
            f"file_path is not a regular file: {resolved_file}",
        )
    return resolved_file


def _resolve_working_directory(working_directory: str) -> Path:
    if not isinstance(working_directory, str) or not working_directory.strip():
        raise _ToolInputError(
            "invalid_working_directory",
            "working_directory must not be blank",
        )
    if "\0" in working_directory:
        raise _ToolInputError(
            "invalid_working_directory",
            "working_directory must not contain null bytes",
        )

    requested_directory = Path(working_directory)
    if not requested_directory.is_absolute():
        raise _ToolInputError(
            "working_directory_not_absolute",
            "working_directory must be an absolute path",
        )

    try:
        resolved_directory = requested_directory.resolve(strict=True)
    except FileNotFoundError as exc:
        raise _ToolInputError(
            "working_directory_not_found",
            f"working_directory does not exist: {requested_directory}",
        ) from exc
    except OSError as exc:
        raise _ToolInputError(
            "working_directory_unavailable",
            f"working_directory cannot be resolved: {requested_directory}",
        ) from exc

    if not resolved_directory.is_dir():
        raise _ToolInputError(
            "working_directory_not_directory",
            f"working_directory is not a directory: {resolved_directory}",
        )
    return resolved_directory


def _validate_timeout(timeout_seconds: int) -> None:
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or not MIN_COMMAND_TIMEOUT_SECONDS
        <= timeout_seconds
        <= MAX_COMMAND_TIMEOUT_SECONDS
    ):
        raise _ToolInputError(
            "invalid_timeout",
            (
                "timeout_seconds must be an integer between "
                f"{MIN_COMMAND_TIMEOUT_SECONDS} and "
                f"{MAX_COMMAND_TIMEOUT_SECONDS}"
            ),
        )


def _validate_arguments(arguments: list[str] | None) -> list[str]:
    normalized_arguments = [] if arguments is None else arguments
    if not isinstance(normalized_arguments, list) or not all(
        isinstance(argument, str) and "\0" not in argument
        for argument in normalized_arguments
    ):
        raise _ToolInputError(
            "invalid_arguments",
            "arguments must be a list of strings without null bytes",
        )
    return normalized_arguments


def _is_bare_program_name(program: str) -> bool:
    forbidden = set("/\\:|&;<>()`$^%!")
    return bool(program) and not any(
        character.isspace() or character in forbidden
        for character in program
    )


def _program_key(program: str) -> str:
    return os.path.normcase(program)


def _load_program_allowlist() -> set[str]:
    try:
        with PROGRAM_ALLOWLIST_PATH.open(encoding="utf-8") as file:
            document = json.load(file)
    except FileNotFoundError as exc:
        raise _ToolInputError(
            "program_allowlist_not_found",
            f"program allowlist does not exist: {PROGRAM_ALLOWLIST_PATH}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise _ToolInputError(
            "program_allowlist_invalid_json",
            f"program allowlist is not valid JSON: {PROGRAM_ALLOWLIST_PATH}",
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise _ToolInputError(
            "program_allowlist_unavailable",
            f"program allowlist cannot be read: {PROGRAM_ALLOWLIST_PATH}",
        ) from exc

    if not isinstance(document, dict) or not isinstance(
        document.get("programs"), list
    ):
        raise _ToolInputError(
            "program_allowlist_invalid",
            "program allowlist must be an object containing a programs list",
        )

    allowed_programs: set[str] = set()
    for program in document["programs"]:
        if not isinstance(program, str) or not _is_bare_program_name(program):
            raise _ToolInputError(
                "program_allowlist_invalid",
                "every allowlisted program must be a non-blank bare command name",
            )
        key = _program_key(program)
        if key in allowed_programs:
            raise _ToolInputError(
                "program_allowlist_duplicate",
                f"duplicate program in allowlist: {program}",
            )
        allowed_programs.add(key)
    return allowed_programs


@tool(
    "read_file",
    description=(
        "Read a text file from a caller-supplied root directory. root_dir must be "
        "an existing absolute directory. file_path may be relative or absolute, "
        "but its resolved path must remain inside root_dir. Returns structured "
        "content or an error and never modifies the file."
    ),
)
def read_file(
    root_dir: str,
    file_path: str,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """Read at most one MiB from a text file contained by ``root_dir``."""

    try:
        root = _resolve_root(root_dir)
        resolved_file = _resolve_file(root, file_path)
        try:
            normalized_encoding = codecs.lookup(encoding).name
        except (LookupError, TypeError) as exc:
            raise _ToolInputError(
                "unknown_encoding",
                f"unknown text encoding: {encoding}",
            ) from exc

        try:
            with resolved_file.open("rb") as file:
                data = file.read(MAX_FILE_SIZE_BYTES + 1)
        except OSError:
            return _error_result(
                "file_read_failed",
                f"unable to read file: {resolved_file}",
            )

        if len(data) > MAX_FILE_SIZE_BYTES:
            return _error_result(
                "file_too_large",
                f"file exceeds the {MAX_FILE_SIZE_BYTES}-byte limit: {resolved_file}",
            )

        try:
            content = data.decode(normalized_encoding)
        except UnicodeDecodeError as exc:
            return _error_result(
                "decode_failed",
                (
                    f"file is not valid {normalized_encoding} text at byte "
                    f"{exc.start}: {resolved_file}"
                ),
            )
    except _ToolInputError as exc:
        return _error_result(exc.code, str(exc))

    return {
        "ok": True,
        "root_dir": str(root),
        "path": str(resolved_file),
        "encoding": normalized_encoding,
        "size_bytes": len(data),
        "content": content,
    }


def _truncate_output(data: bytes) -> tuple[bytes, bool]:
    if len(data) <= MAX_COMMAND_OUTPUT_BYTES:
        return data, False
    return data[:MAX_COMMAND_OUTPUT_BYTES], True


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Best-effort termination of a script process and its children."""

    taskkill_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            creationflags=taskkill_flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass

    if process.poll() is None:
        process.kill()


def _execute_process_sync(
    root: Path,
    command: list[str],
    timeout_seconds: int,
    result_metadata: dict[str, Any],
    start_error_code: str = "process_start_failed",
    start_error_subject: str = "process",
) -> dict[str, Any]:
    started_at = perf_counter()
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        process = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
    except OSError as exc:
        return _error_result(
            start_error_code,
            f"unable to start {start_error_subject}: {exc}",
        )

    timed_out = False
    try:
        stdout_bytes, stderr_bytes = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)
        stdout_bytes, stderr_bytes = process.communicate()

    stdout_bytes, stdout_truncated = _truncate_output(stdout_bytes)
    stderr_bytes, stderr_truncated = _truncate_output(stderr_bytes)
    output_encoding = locale.getpreferredencoding(False) or "utf-8"
    stdout = stdout_bytes.decode(output_encoding, errors="replace")
    stderr = stderr_bytes.decode(output_encoding, errors="replace")
    duration_ms = round((perf_counter() - started_at) * 1000)
    exit_code = process.returncode

    return {
        "ok": not timed_out and exit_code == 0,
        **result_metadata,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "duration_ms": duration_ms,
    }


@tool(
    "run_python",
    description=(
        "Execute temporary Python code derived from inline Python examples in a "
        "loaded Skill. Use this when SKILL.md provides Python code that must be "
        "adapted to the current task and does not point to an existing script in "
        "the Skill's scripts directory. If SKILL.md points to a bundled script, "
        "use run_skill_script instead; use run_node for inline JavaScript. "
        "`code`: construct this from the loaded "
        "SKILL.md example, replacing its placeholders, input paths, output paths, "
        "and task values with values from the user request or previous tool "
        "results. `working_directory`: copy the exact absolute path shown as "
        "'当前工作目录' in the latest user message; do not use skill_root_dir. "
        "Relative file paths inside code are resolved from this directory. "
        "`timeout_seconds`: use the timeout required by SKILL.md; omit it to use "
        "60 seconds when the Skill specifies no timeout. The code runs with the "
        "same Python interpreter and operating-system permissions as the llama "
        "backend."
    ),
)
async def run_python(
    code: str,
    working_directory: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Execute inline Python using the interpreter running the llama backend."""

    try:
        if not isinstance(code, str) or not code.strip():
            raise _ToolInputError("invalid_code", "code must not be blank")
        if "\0" in code:
            raise _ToolInputError(
                "invalid_code",
                "code must not contain null bytes",
            )
        code_size = len(code.encode("utf-8"))
        if code_size > MAX_PYTHON_CODE_BYTES:
            raise _ToolInputError(
                "code_too_large",
                f"code exceeds the {MAX_PYTHON_CODE_BYTES}-byte limit",
            )
        root = _resolve_working_directory(working_directory)
        _validate_timeout(timeout_seconds)
    except _ToolInputError as exc:
        return _error_result(exc.code, str(exc))

    return await asyncio.to_thread(
        _execute_process_sync,
        root,
        [sys.executable, "-c", code],
        timeout_seconds,
        {
            "runtime": "python",
            "python_executable": sys.executable,
            "working_directory": str(root),
        },
    )


@tool(
    "run_node",
    description=(
        "Execute temporary JavaScript code derived from an inline JavaScript "
        "example in a loaded Skill. Use this when SKILL.md provides JavaScript "
        "that must be adapted to the current task, such as a pptxgenjs deck "
        "generator, and does not point to an existing script in the Skill's "
        "scripts directory. Use run_skill_script for bundled .py/.ps1/.cmd/.bat "
        "files and run_program for an external command-line program. `code`: "
        "construct this from the loaded SKILL.md JavaScript example, replacing "
        "its placeholders, input paths, output paths, and task values with values "
        "from the user request or previous tool results. `working_directory`: "
        "copy the exact absolute path shown as '当前工作目录' in the latest user "
        "message; do not use skill_root_dir. Relative file paths and Node module "
        "resolution start from this directory. `timeout_seconds`: use the timeout "
        "required by SKILL.md; omit it to use 60 seconds when none is specified. "
        "The code runs as `node -e <code>` with shell disabled and the same "
        "operating-system permissions as the llama backend."
    ),
)
async def run_node(
    code: str,
    working_directory: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Execute inline JavaScript with the Node.js runtime on PATH."""

    try:
        if not isinstance(code, str) or not code.strip():
            raise _ToolInputError("invalid_code", "code must not be blank")
        if "\0" in code:
            raise _ToolInputError(
                "invalid_code",
                "code must not contain null bytes",
            )
        code_size = len(code.encode("utf-8"))
        if code_size > MAX_NODE_CODE_BYTES:
            raise _ToolInputError(
                "code_too_large",
                f"code exceeds the {MAX_NODE_CODE_BYTES}-byte limit",
            )
        root = _resolve_working_directory(working_directory)
        _validate_timeout(timeout_seconds)
        try:
            node_executable = shutil.which("node")
        except OSError as exc:
            raise _ToolInputError(
                "node_runtime_unavailable",
                "unable to resolve the Node.js runtime",
            ) from exc
        if node_executable is None:
            raise _ToolInputError(
                "node_runtime_not_found",
                "Node.js is not available on PATH",
            )
    except _ToolInputError as exc:
        return _error_result(exc.code, str(exc))

    return await asyncio.to_thread(
        _execute_process_sync,
        root,
        [node_executable, "-e", code],
        timeout_seconds,
        {
            "runtime": "node",
            "node_executable": node_executable,
            "working_directory": str(root),
        },
        "node_start_failed",
        "Node.js runtime",
    )


@tool(
    "run_program",
    description=(
        "Run a non-Python command-line program explicitly required by a loaded "
        "Skill, such as pdftotext, qpdf, or tesseract. Use this for external "
        "programs; use run_python for inline Python, run_node for inline "
        "JavaScript, and run_skill_script for files bundled under the Skill's "
        "scripts directory. `program`: take only the "
        "first command name from the SKILL.md command, for example 'pdftotext'. "
        "Do not pass a full command line, executable path, shell builtin, pipe, "
        "redirection, or shell expression. The name must be present in "
        "tool/program_allowlist.json. `arguments`: take every token after the "
        "program name, replace placeholders with values from the user request or "
        "previous tool results, and pass each argument as a separate list item "
        "without surrounding shell quotes. `working_directory`: copy the exact "
        "absolute path shown as '当前工作目录' in the latest user message. Relative "
        "input and output paths are resolved from this directory. "
        "`timeout_seconds`: use the timeout required by SKILL.md; omit it to use "
        "60 seconds when none is specified."
    ),
)
async def run_program(
    program: str,
    arguments: list[str] | None,
    working_directory: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Run one allowlisted executable without invoking a command shell."""

    try:
        if not isinstance(program, str) or not _is_bare_program_name(program):
            raise _ToolInputError(
                "invalid_program",
                "program must be a non-blank bare command name",
            )
        normalized_arguments = _validate_arguments(arguments)
        root = _resolve_working_directory(working_directory)
        _validate_timeout(timeout_seconds)
        allowed_programs = _load_program_allowlist()
        if _program_key(program) not in allowed_programs:
            raise _ToolInputError(
                "program_not_allowed",
                f"program is not present in the allowlist: {program}",
            )
        try:
            resolved_program = shutil.which(program)
        except OSError as exc:
            raise _ToolInputError(
                "program_unavailable",
                f"unable to resolve program: {program}",
            ) from exc
        if resolved_program is None:
            raise _ToolInputError(
                "program_not_found",
                f"allowlisted program is not available on PATH: {program}",
            )
    except _ToolInputError as exc:
        return _error_result(exc.code, str(exc))

    return await asyncio.to_thread(
        _execute_process_sync,
        root,
        [resolved_program, *normalized_arguments],
        timeout_seconds,
        {
            "runtime": "program",
            "program": program,
            "executable": resolved_program,
            "working_directory": str(root),
        },
    )


@tool(
    "read_skill_resource",
    description=(
        "Read a text resource referenced by an enabled Skill, such as FORMS.md, "
        "REFERENCE.md, or a text template. Use this only after loading the Skill "
        "with the skill tool and only when SKILL.md instructs you to read another "
        "file. `skill_name`: use the exact name passed to and returned by the "
        "successful skill tool call. `resource_path`: use the relative path "
        "explicitly referenced by SKILL.md, resolved from that Skill's root "
        "directory. Do not use skill_root_dir, an absolute path, or a path "
        "containing parent traversal. `encoding`: use the encoding explicitly "
        "required by SKILL.md; omit it to use UTF-8. This tool reads text only and "
        "cannot access files outside the registered Skill directory."
    ),
)
def read_skill_resource(
    skill_name: str,
    resource_path: str,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """Read a registered Skill's supplemental text resource."""

    try:
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise _ToolInputError(
                "invalid_skill_name",
                "skill_name must not be blank",
            )
        normalized_name = skill_name.strip()
        record = plugin.get_skill_record(normalized_name)
        if record is None:
            raise _ToolInputError(
                "skill_not_found",
                f"unknown skill: {normalized_name}",
            )
        plugin_name = record["plugin_name"]
        if not plugin.use_plugins.get(plugin_name, False):
            raise _ToolInputError(
                "plugin_disabled",
                f"plugin is disabled for skill '{normalized_name}': {plugin_name}",
            )
        if not isinstance(resource_path, str) or not resource_path.strip():
            raise _ToolInputError(
                "invalid_resource_path",
                "resource_path must not be blank",
            )
        if "\0" in resource_path:
            raise _ToolInputError(
                "invalid_resource_path",
                "resource_path must not contain null bytes",
            )

        requested_resource = Path(resource_path)
        if requested_resource.is_absolute():
            raise _ToolInputError(
                "resource_path_not_relative",
                "resource_path must be relative to the Skill root",
            )
        if ".." in requested_resource.parts:
            raise _ToolInputError(
                "resource_path_parent_traversal",
                "resource_path must not contain parent traversal",
            )

        skill_root = Path(record["skill_root_dir"]).resolve(strict=True)
        candidate = skill_root / requested_resource
        try:
            resolved_resource = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise _ToolInputError(
                "resource_not_found",
                f"Skill resource does not exist: {resource_path}",
            ) from exc
        except OSError as exc:
            raise _ToolInputError(
                "resource_unavailable",
                f"Skill resource cannot be resolved: {resource_path}",
            ) from exc
        if not resolved_resource.is_relative_to(skill_root):
            raise _ToolInputError(
                "resource_outside_skill",
                f"resource must stay inside the Skill root: {resolved_resource}",
            )
        if not resolved_resource.is_file():
            raise _ToolInputError(
                "resource_not_file",
                f"resource_path is not a regular file: {resolved_resource}",
            )
    except _ToolInputError as exc:
        return _error_result(exc.code, str(exc))
    except (FileNotFoundError, OSError):
        return _error_result(
            "skill_unavailable",
            f"Skill root cannot be resolved: {skill_name}",
        )

    read_result = read_file.invoke(
        {
            "root_dir": str(skill_root),
            "file_path": str(resolved_resource),
            "encoding": encoding,
        }
    )
    if not read_result["ok"]:
        return read_result
    return {
        **read_result,
        "skill_name": normalized_name,
        "plugin_name": plugin_name,
        "resource_path": resource_path,
    }


@tool(
    "run_skill_script",
    description=(
        "Run an existing Python, PowerShell, CMD, or batch script bundled inside "
        "an enabled Skill's scripts directory. Use this only when the loaded "
        "SKILL.md explicitly points to an existing scripts/... file. Use "
        "run_python for inline or task-generated Python code, run_node for inline "
        "or task-generated JavaScript code, and run_program for external "
        "command-line programs. `skill_name`: use the exact name passed "
        "to and returned by the successful skill tool call. `script_path`: copy "
        "the Skill-relative scripts/... path named by SKILL.md; do not construct "
        "an external or working-directory path. `arguments`: replace the script "
        "command's placeholders with values from the user request or previous tool "
        "results and pass each argument as a separate string without shell quotes. "
        "`timeout_seconds`: use the timeout required by SKILL.md; omit it to use "
        "60 seconds when none is specified. The script runs with the Skill root "
        "as its current working directory."
    ),
)
async def run_skill_script(
    skill_name: str,
    script_path: str,
    arguments: list[str] | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Run a registered Skill's bundled script without blocking the event loop."""

    try:
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise _ToolInputError(
                "invalid_skill_name",
                "skill_name must not be blank",
            )
        normalized_name = skill_name.strip()
        record = plugin.get_skill_record(normalized_name)
        if record is None:
            raise _ToolInputError(
                "skill_not_found",
                f"unknown skill: {normalized_name}",
            )
        plugin_name = record["plugin_name"]
        if not plugin.use_plugins.get(plugin_name, False):
            raise _ToolInputError(
                "plugin_disabled",
                f"plugin is disabled for skill '{normalized_name}': {plugin_name}",
            )
        if not isinstance(script_path, str) or not script_path.strip():
            raise _ToolInputError(
                "invalid_script_path",
                "script_path must not be blank",
            )
        arguments = _validate_arguments(arguments)
        _validate_timeout(timeout_seconds)

        skill_root = Path(record["skill_root_dir"]).resolve(strict=True)
        scripts_root = (skill_root / "scripts").resolve(strict=True)
        if not scripts_root.is_relative_to(skill_root):
            raise _ToolInputError(
                "scripts_outside_skill",
                f"scripts directory must stay inside the Skill root: {scripts_root}",
            )
        requested_script = Path(script_path)
        candidate = (
            requested_script
            if requested_script.is_absolute()
            else skill_root / requested_script
        )
        resolved_script = candidate.resolve(strict=True)
        if not resolved_script.is_relative_to(scripts_root):
            raise _ToolInputError(
                "script_outside_skill",
                f"script must stay inside the Skill scripts directory: {resolved_script}",
            )
        if not resolved_script.is_file():
            raise _ToolInputError(
                "script_not_file",
                f"script_path is not a regular file: {resolved_script}",
            )
    except _ToolInputError as exc:
        return _error_result(exc.code, str(exc))
    except FileNotFoundError:
        return _error_result(
            "script_not_found",
            f"Skill scripts directory or script does not exist: {script_path}",
        )
    except OSError:
        return _error_result(
            "script_unavailable",
            f"Skill script cannot be resolved: {script_path}",
        )

    suffix = resolved_script.suffix.lower()
    if suffix == ".py":
        runtime = "python"
        command = [sys.executable, str(resolved_script), *arguments]
    elif suffix == ".ps1":
        runtime = "powershell"
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            return _error_result(
                "runtime_not_found",
                "PowerShell is not available",
            )
        command = [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(resolved_script),
            *arguments,
        ]
    elif suffix in {".cmd", ".bat"}:
        if os.name != "nt":
            return _error_result(
                "unsupported_platform",
                "CMD and batch scripts are only available on Windows",
            )
        runtime = "cmd"
        command_processor = os.environ.get("COMSPEC", "cmd.exe")
        command = [
            command_processor,
            "/d",
            "/s",
            "/c",
            subprocess.list2cmdline([str(resolved_script), *arguments]),
        ]
    else:
        return _error_result(
            "unsupported_script_type",
            "supported Skill script types are .py, .ps1, .cmd, and .bat",
        )

    return await asyncio.to_thread(
        _execute_process_sync,
        skill_root,
        command,
        timeout_seconds,
        {
            "skill_name": normalized_name,
            "plugin_name": plugin_name,
            "skill_root_dir": str(skill_root),
            "script_path": str(resolved_script),
            "runtime": runtime,
        },
        "script_start_failed",
        "skill script",
    )


@tool(
    "skill",
    description=_build_skill_tool_description(),
)
def skill(name: str) -> dict[str, Any]:
    """Load one registered, enabled SKILL.md file without executing it."""

    if not isinstance(name, str) or not name.strip():
        return _error_result("invalid_skill_name", "skill name must not be blank")

    normalized_name = name.strip()
    record = plugin.get_skill_record(normalized_name)
    if record is None:
        return _error_result(
            "skill_not_found",
            f"unknown skill: {normalized_name}",
        )

    plugin_name = record["plugin_name"]
    if not plugin.use_plugins.get(plugin_name, False):
        return _error_result(
            "plugin_disabled",
            f"plugin is disabled for skill '{normalized_name}': {plugin_name}",
        )

    read_result = read_file.invoke(
        {
            "root_dir": str(record["skill_root_dir"]),
            "file_path": str(record["path"]),
            "encoding": "utf-8",
        }
    )
    if not read_result["ok"]:
        return read_result

    return {
        "ok": True,
        "name": normalized_name,
        "plugin_name": plugin_name,
        "path": read_result["path"],
        "skill_root_dir": read_result["root_dir"],
        "content": read_result["content"],
    }


def get_dynamic_skill_tool():
    """Return a per-model-call Skill schema with the live enabled-Skill catalog."""

    return skill.model_copy(
        update={"description": _build_skill_tool_description()}
    )


__all__ = [
    "get_dynamic_skill_tool",
    "read_file",
    "read_skill_resource",
    "run_node",
    "run_program",
    "run_python",
    "run_skill_script",
    "skill",
]

''' ai不能修改以下注释


静态 @tool(skill)
描述就是， 该工具返回 完整的skill.md用于完成各种任务， 每个 skill.md 的简短描述如下列表 ...
    简短描述列表skill list在 plugin.py 的全局变量实现 skills 中的且 use_plugins['name']=True的，
    skill list需要动态生成，实现在 agent middleware wrap_model_call 里的 get_dynamic_skill_tool，
    
    调用返回{
      "ok": true,
      "name": "create-project-skill",
      "plugin_name": "projects-plugin",
      "path": "D:\\...\\create-project-skill\\SKILL.md",
      "skill_root_dir": "D:\\...\\create-project-skill",
      "content": "完整 SKILL.md"
    }

静态@run_skill_script(run_skill_script)
    输入是 skill_name, scripts_name(相对), arguments
    根据 skill_name 查找详细信息"create-project-skill": {
        "name": "create-project-skill",
        "description": "在指定目录创建项目……",
        "plugin_name": "projects-plugin",
        "path": Path(".../create-project-skill/SKILL.md"),
        "skill_root_dir": Path(".../create-project-skill"),
    }
    cwd = skill_root_dir(绝对)
    resolved_script = scripts_name(绝对),, arguments 
    processer 根据文件后缀判断python 等等


'''
