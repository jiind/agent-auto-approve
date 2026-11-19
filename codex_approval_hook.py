"""Manage approval hooks for Codex, Claude Code, and Antigravity CLI."""

import argparse
import base64
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from itertools import chain
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unicodedata
from urllib.parse import urlsplit
from urllib.request import url2pathname


HOOK_FILENAME = "codex_approval_hook.py"
AGY_HOOK_NAME = "codex-auto-approve"
POWERSHELL_FLAGS = "-NoLogo -NoProfile -NonInteractive -EncodedCommand"
AGY_FILE_PATHS = {
    "read_file": "Path",
    "write_file": "Path",
    "edit_file": "Path",
    "view_file": "AbsolutePath",
    "write_to_file": "TargetFile",
    "replace_file_content": "TargetFile",
    "multi_replace_file_content": "TargetFile",
    "list_dir": "DirectoryPath",
}
LITERAL_FILE_COMMAND = re.compile(
    r"(?:/usr/bin/|/bin/)?(?:touch|mkdir)(?:[ \t]+[\w./~+-]+)+[ \t]*"
)


@dataclass(frozen=True)
class Agent:
    name: str
    directory: str
    home_env: str
    global_settings: str
    project_settings: str
    hook_status: str
    global_directory: str = ""

    def home(self):
        custom_home = os.environ.get(self.home_env) if self.home_env else None
        if custom_home:
            return Path(custom_home).expanduser().resolve()
        return Path.home() / (self.global_directory or self.directory)

    def settings_path(self, scope, directory):
        return directory / (self.global_settings if scope == "global" else self.project_settings)


CODEX = Agent("Codex", ".codex", "CODEX_HOME", "hooks.json", "hooks.json", "Codex approval hook")
CLAUDE = Agent(
    "Claude Code", ".claude", "CLAUDE_CONFIG_DIR", "settings.json", "settings.local.json",
    "Claude Code approval hook",
)
AGY = Agent("Antigravity CLI", ".agents", "", "hooks.json", "hooks.json", "", ".gemini/config")
AGENTS = {"codex": CODEX, "claude": CLAUDE, "agy": AGY}


def within_workspace(path, workspace):
    try:
        path.resolve().relative_to(workspace)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def file_permission_paths(permissions):
    if not isinstance(permissions, dict) or set(permissions) - {"file_system", "network"}:
        return []
    files = permissions.get("file_system")
    if permissions.get("network") not in (None, {"enabled": False}):
        return []
    if not isinstance(files, dict):
        return []

    if set(files) == {"entries"} and isinstance(files["entries"], list):
        paths = []
        for entry in files["entries"]:
            if not isinstance(entry, dict) or entry.get("access") not in ("read", "write"):
                return []
            path = entry.get("path")
            if not isinstance(path, dict) or path.get("type") != "path":
                return []
            paths.append(path.get("path"))
        return paths

    if set(files) - {"read", "write"}:
        return []
    reads = files.get("read")
    writes = files.get("write")
    reads = [] if reads is None else reads
    writes = [] if writes is None else writes
    if not isinstance(reads, list) or not isinstance(writes, list):
        return []
    return reads + writes


def local_permission_path(value):
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("file://"):
        uri = urlsplit(value)
        if uri.netloc or uri.query or uri.fragment:
            return None
        value = url2pathname(uri.path)
    path = Path(value)
    return path if path.is_absolute() else None


def request_within_workspace(request, workspace, *, claude=False):
    raw_cwd = request.get("cwd")
    tool_input = request.get("tool_input")
    if not isinstance(raw_cwd, str) or not isinstance(tool_input, dict):
        return False
    cwd = Path(raw_cwd)
    if not cwd.is_absolute() or not within_workspace(cwd, workspace):
        return False

    tool_name = request.get("tool_name")
    if claude and tool_name in ("Read", "Edit", "Write"):
        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str):
            return False
        path = Path(file_path)
        return path.is_absolute() and within_workspace(path, workspace)

    if not claude and tool_name == "request_permissions":
        targets = file_permission_paths(tool_input.get("permissions"))
        paths = [local_permission_path(target) for target in targets]
        return bool(paths) and all(path is not None and within_workspace(path, workspace) for path in paths)

    if tool_name != "Bash" or sys.platform == "win32":
        return False
    if set(tool_input) - {"command", "description"}:
        return False
    description = tool_input.get("description")
    if description is not None and (
        not isinstance(description, str) or description.startswith("network-access ")
    ):
        return False

    return literal_file_command_within_workspace(tool_input.get("command"), workspace, cwd=cwd)


def literal_file_command_within_workspace(command, workspace, *, cwd=None):
    if not isinstance(command, str) or not LITERAL_FILE_COMMAND.fullmatch(command):
        return False
    _, *targets = command.split()
    for target in targets:
        if target.startswith("-") or "~" in target[1:]:
            return False
        if cwd is None and not Path(target).is_absolute():
            return False
        if target == "~":
            path = Path.home()
        elif target.startswith("~/"):
            path = Path.home() / target[2:].lstrip("/")
        elif target.startswith("~"):
            return False
        else:
            path = Path(target) if cwd is None else cwd / target
        if not within_workspace(path, workspace):
            return False
    return True


def approve_request(workspace=None, *, claude=False):
    try:
        request = json.load(sys.stdin)
    except ValueError:
        return

    if not isinstance(request, dict) or request.get("hook_event_name") != "PermissionRequest":
        return
    if claude and request.get("tool_name") in ("AskUserQuestion", "ExitPlanMode"):
        return
    if workspace is not None:
        try:
            if not request_within_workspace(request, workspace, claude=claude):
                return
        except (OSError, RuntimeError, ValueError):
            return

    response = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"},
        }
    }
    print(json.dumps(response))


def agy_request_within_workspace(tool_name, tool_input, workspace):
    if tool_name == "run_command":
        known_fields = {
            "CommandLine", "Cwd", "WaitMsBeforeAsync", "RunPersistent", "RequestedTerminalID",
            "toolSummary", "IsDaemon",
        }
        if sys.platform == "win32" or set(tool_input) - known_fields:
            return False
        if any(tool_input.get(field) for field in ("RunPersistent", "RequestedTerminalID", "IsDaemon")):
            return False
        cwd = None
        if "Cwd" in tool_input:
            raw_cwd = tool_input["Cwd"]
            if not isinstance(raw_cwd, str):
                return False
            cwd = Path(raw_cwd)
            if not cwd.is_absolute() or not within_workspace(cwd, workspace):
                return False
        return literal_file_command_within_workspace(tool_input.get("CommandLine"), workspace, cwd=cwd)

    path_key = AGY_FILE_PATHS.get(tool_name)
    if path_key is None or tool_input.get("IsArtifact") or tool_input.get("ArtifactMetadata"):
        return False
    file_path = tool_input.get(path_key)
    if not isinstance(file_path, str):
        return False
    path = Path(file_path)
    return path.is_absolute() and within_workspace(path, workspace)


def approve_agy_request(arguments):
    decision = "allow"
    try:
        request = json.load(sys.stdin)
        tool_call = request.get("toolCall") if isinstance(request, dict) else None
        if isinstance(tool_call, dict):
            name = tool_call.get("name")
            tool_input = tool_call.get("args")
            if isinstance(name, str) and name and name != "ask_question" and isinstance(tool_input, dict):
                if not arguments or any(
                    agy_request_within_workspace(name, tool_input, root)
                    for root in agy_workspace_paths(arguments, request)
                ):
                    decision = "auto_approve"
    except (OSError, RuntimeError, ValueError):
        pass
    print(json.dumps({"decision": decision}))


def agy_workspace_paths(arguments, request):
    if arguments == ["--workspace-only"]:
        paths = request.get("workspacePaths")
        if isinstance(paths, list):
            for value in paths:
                if isinstance(value, str) and Path(value).is_absolute():
                    yield Path(value).resolve()
    elif len(arguments) == 2 and arguments[0] == "--workspace-root-hex":
        path = Path(os.fsdecode(bytes.fromhex(arguments[1])))
        if path.is_absolute():
            yield path


def find_codex(env, *, windows):
    executable = "codex.exe" if windows else "codex"
    codex = shutil.which(executable, path=env.get("PATH"))
    if codex:
        return [codex]

    if windows:
        shim = shutil.which("codex.cmd", path=env.get("PATH"))
        node = shutil.which("node.exe", path=env.get("PATH"))
        if shim and node:
            entry = Path(shim).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            if entry.is_file():
                return [node, str(entry)]

    raise FileNotFoundError("Codex CLI was not found on PATH.")


def workspace_arguments(workspace):
    # Hex keeps the workspace path literal under both cmd.exe and PowerShell.
    return ["--workspace-root-hex", os.fsencode(workspace).hex()]


def python_arguments(script, hook_args):
    return [sys.executable, "-I", "-X", "utf8", str(script), *hook_args]


def hook_command(script, env, *, windows, hook_args):
    if not windows:
        return shlex.join(python_arguments(script, hook_args))

    # Both cmd.exe and PowerShell can invoke an unquoted executable name.
    # Encode the script path so shell interpolation never touches it.
    python = Path(sys.executable)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.exe", python.name, re.IGNORECASE):
        raise ValueError("Use a standard Windows Python executable such as python.exe.")
    env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
    script_path = os.fsencode(script).hex()
    code = (
        "from os import fsdecode; from runpy import run_path; "
        f"run_path(fsdecode(bytes.fromhex('{script_path}')), run_name='__main__')"
    )
    return subprocess.list2cmdline([python.name, "-I", "-X", "utf8", "-c", code, *hook_args])


def write_atomically(path, data):
    path = path.resolve()
    if path.is_file() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as temp_dir:
        staged = Path(temp_dir) / path.name
        staged.write_bytes(data)
        staged.chmod((path.stat().st_mode & 0o777) if path.exists() else 0o600)
        staged.replace(path)


def windows_install_command(arguments, *, executable=None):
    # Invoke the installed interpreter by absolute path and forward the hook's UTF-8 JSON.
    encoded_arguments = base64.b64encode(json.dumps(arguments).encode("ascii")).decode("ascii")
    program = (
        "$utf8 = [System.Text.UTF8Encoding]::new($false)\n"
        "$OutputEncoding = $utf8\n"
        f"$argv = ConvertFrom-Json ($utf8.GetString([Convert]::FromBase64String('{encoded_arguments}')))\n"
        "$python = $argv[0]\n"
        "$hookArgs = $argv[1..($argv.Count - 1)]\n"
        "$reader = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8)\n"
        "$reader.ReadToEnd() | & $python @hookArgs\n"
        "exit $LASTEXITCODE\n"
    )
    encoded = base64.b64encode(program.encode("utf-16le")).decode("ascii")
    if executable is None:
        system_root = os.environ.get("SystemRoot", r"C:\Windows").rstrip("\\")
        executable = system_root + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
        if not re.fullmatch(r"[A-Za-z]:\\[A-Za-z0-9_.\\-]+", executable):
            executable = "powershell.exe"
    return f"{executable} {POWERSHELL_FLAGS} {encoded}"


def agy_hook(script, hook_args):
    arguments = python_arguments(script, ["--agy-hook", *hook_args])
    command = (
        windows_install_command(arguments, executable="powershell.exe")
        if sys.platform == "win32" else shlex.join(arguments)
    )
    return {"type": "command", "command": command, "timeout": 5}


def agy_command_arguments(command):
    prefix = f"powershell.exe {POWERSHELL_FLAGS} "
    if not command.startswith(prefix):
        return shlex.split(command)
    program = base64.b64decode(command[len(prefix):], validate=True).decode("utf-16le")
    match = re.search(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", program)
    if not match:
        return []
    arguments = json.loads(base64.b64decode(match[1], validate=True))
    return arguments if isinstance(arguments, list) else []


def claude_hook(script, hook_args):
    command, *arguments = python_arguments(script, ["--claude-hook", *hook_args])
    return {
        "type": "command",
        "command": command,
        "args": arguments,
        "timeout": 5,
        "statusMessage": CLAUDE.hook_status,
    }


def hook_config(config_path):
    try:
        return json.loads(config_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}


def write_hook_config(config_path, config):
    data = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_atomically(config_path, data)


@contextmanager
def lock_hook_config(directory):
    lock = directory / ".codex_approval_install.lock"
    lock.open("x").close()
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def installed_hook_arguments(handler, script, agent):
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return None
    if agent is not AGY and handler.get("statusMessage") != agent.hook_status:
        return None
    command = handler.get("command")
    if not isinstance(command, str):
        return None
    if agent is CLAUDE:
        arguments = handler.get("args")
        expected = ["-I", "-X", "utf8", str(script), "--claude-hook"]
        if isinstance(arguments, list) and arguments[:len(expected)] == expected:
            return arguments[len(expected):]
        return None
    try:
        arguments = agy_command_arguments(command) if agent is AGY else shlex.split(command)
    except ValueError:
        return None
    expected = ["-I", "-X", "utf8", str(script)]
    if agent is AGY:
        expected.append("--agy-hook")
    end = 1 + len(expected)
    if arguments[1:end] != expected:
        return None
    return arguments[end:]


def approval_group_keys(agent):
    return (AGY_HOOK_NAME, "PreToolUse") if agent is AGY else ("hooks", "PermissionRequest")


def approval_groups(config, filename, agent):
    if not isinstance(config, dict):
        raise ValueError(f"{filename} must contain a JSON object.")
    event_key, group_key = approval_group_keys(agent)
    events = config.setdefault(event_key, {})
    if not isinstance(events, dict):
        raise ValueError(f"{filename}: {event_key} must be a JSON object.")
    groups = events.setdefault(group_key, [])
    if not isinstance(groups, list):
        raise ValueError(f"{filename}: {group_key} must be a list.")
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            raise ValueError(f"{filename}: each {group_key} group needs a hooks list.")
    return events, groups


def register_hook(config, handler, script, agent, filename):
    existing_name = agent is AGY and isinstance(config, dict) and AGY_HOOK_NAME in config
    _, groups = approval_groups(config, filename, agent)
    for group in groups:
        for index, existing in enumerate(group["hooks"]):
            if installed_hook_arguments(existing, script, agent) is not None:
                group["hooks"][index] = handler
                return True

    if existing_name:
        raise FileExistsError(f"{filename} already has a hook named {AGY_HOOK_NAME}.")
    group = {"hooks": [handler]}
    if agent is AGY:
        group["matcher"] = "*"
    groups.append(group)
    return False


def unregister_hook(config, script, agent, filename):
    events, groups = approval_groups(config, filename, agent)
    event_key, group_key = approval_group_keys(agent)
    remaining_groups = []
    removed = False
    for group in groups:
        handlers = group["hooks"]
        remaining = [
            handler for handler in handlers if installed_hook_arguments(handler, script, agent) is None
        ]
        if len(remaining) == len(handlers):
            remaining_groups.append(group)
        else:
            removed = True
            if remaining:
                remaining_groups.append({**group, "hooks": remaining})
    if removed:
        if remaining_groups:
            events[group_key] = remaining_groups
        else:
            del events[group_key]
            if agent is AGY and set(events) <= {"enabled"}:
                del config[event_key]
    return removed


def installation_at(directory, scope, agent):
    config_path = agent.settings_path(scope, directory)
    if not config_path.is_file():
        return None
    script = directory / "hooks" / HOOK_FILENAME
    config = hook_config(config_path)
    event_key, group_key = approval_group_keys(agent)
    events = config.get(event_key) if isinstance(config, dict) else None
    groups = events.get(group_key) if isinstance(events, dict) else None
    if not isinstance(groups, list):
        return None
    for group in groups:
        handlers = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(handlers, list):
            continue
        for handler in handlers:
            arguments = installed_hook_arguments(handler, script, agent)
            if arguments is not None:
                workspace_only = "--workspace-only" in arguments or "--workspace-root-hex" in arguments
                return config_path, workspace_only, script.is_file()
    return None


def confirm_with_global_hook(agent):
    registration = installation_at(agent.home(), "global", agent)
    if registration is None:
        return True

    config_path, workspace_only, _ = registration
    mode = "workspace-only" if workspace_only else "all requests"
    print(
        f"Warning: {agent.name} already has a global approval hook ({mode}) in {config_path}. "
        "Both hooks may apply.",
        file=sys.stderr,
    )
    print("Continue? [y/n] ", end="", file=sys.stderr, flush=True)
    answer = sys.stdin.readline().strip().lower()
    if answer == "y":
        return True
    print("Cancelled.", file=sys.stderr)
    return False


@contextmanager
def terminal_color(stream):
    if not stream.isatty() or os.environ.get("TERM") == "dumb":
        yield False
        return
    if sys.platform != "win32":
        yield True
        return

    from ctypes import byref, windll, wintypes
    from msvcrt import get_osfhandle

    console = windll.kernel32
    handle = wintypes.HANDLE(get_osfhandle(stream.fileno()))
    mode = wintypes.DWORD()
    if not console.GetConsoleMode(handle, byref(mode)):
        yield False
        return

    # ENABLE_PROCESSED_OUTPUT and ENABLE_VIRTUAL_TERMINAL_PROCESSING.
    color_mode = mode.value | 0x0001 | 0x0004
    if color_mode == mode.value:
        yield True
    elif console.SetConsoleMode(handle, color_mode):
        try:
            yield True
        finally:
            console.SetConsoleMode(handle, mode.value)
    else:
        yield False


class SearchProgress:
    def __init__(self, stream, *, color):
        self.stream = stream
        self.color = color
        try:
            columns = os.get_terminal_size(stream.fileno()).columns
        except OSError:
            columns = shutil.get_terminal_size().columns
        self.max_width = (columns or 80) - 1
        self.width = 0
        self.next_update = 0

    def update(self, directory, *, found=False):
        now = time.monotonic()
        if not found and now < self.next_update:
            return
        self.next_update = now + 0.1

        suffix = "... found" if found else "..."
        available = self.max_width - len(suffix)
        if available <= 0:
            return
        visible_name = []
        name_width = 0
        for character in directory.name or str(directory):
            character = character if character.isprintable() else "?"
            width = 2 if unicodedata.east_asian_width(character) in ("F", "W", "A") else 1
            if name_width + width > available:
                break
            visible_name.append(character)
            name_width += width

        width = name_width + len(suffix)
        padding = " " * max(self.width - width, 0)
        if found and self.color:
            suffix = "... \x1b[32mfound\x1b[39m"
        self.stream.write(f"\r{''.join(visible_name)}{suffix}{padding}")
        self.stream.flush()
        self.width = width

    def clear(self):
        if self.width:
            self.stream.write("\r" + " " * self.width + "\r")
            self.stream.flush()
            self.width = 0


@contextmanager
def search_output(root):
    with terminal_color(sys.stderr) as color:
        progress = SearchProgress(sys.stderr, color=color) if sys.stderr.isatty() else None
        deferred_results = [] if progress is not None and sys.stdout.isatty() else None

        def write_result(directory, result):
            if progress is not None:
                progress.update(directory, found=True)
            if deferred_results is None:
                print(result, flush=True)
            else:
                deferred_results.append(result)

        try:
            if progress is not None:
                progress.update(root)
            yield progress, write_result
        finally:
            if progress is not None:
                progress.clear()
            if deferred_results:
                print("\n".join(deferred_results), flush=True)


def walk_directories(root, *, progress=None, report_skipped=True):
    skipped = 0

    def count_error(_error):
        nonlocal skipped
        skipped += 1

    for current, directories, files in os.walk(root, onerror=count_error, followlinks=False):
        directory = Path(current)
        if progress is not None:
            progress.update(directory)
        if sys.platform == "win32":
            # Windows junctions can redirect a walk even with followlinks disabled.
            local_directories = []
            for name in directories:
                try:
                    tag = (directory / name).lstat().st_reparse_tag
                except OSError as error:
                    count_error(error)
                    continue
                if tag != stat.IO_REPARSE_TAG_MOUNT_POINT:
                    local_directories.append(name)
            directories[:] = local_directories
        directories.sort()
        yield directory, files

    if skipped and report_skipped:
        if progress is not None:
            progress.clear()
        print(f"Could not scan {skipped} directories under {root}", file=sys.stderr)


def discover_installations(root, agent, *, include_global=False, progress=None, report_skipped=True):
    home = agent.home()
    global_location = [("global", home)] if include_global or within_workspace(home, root) else []
    projects = (
        ("project", directory.with_name(agent.directory))
        for directory, files in walk_directories(root, progress=progress, report_skipped=report_skipped)
        if directory.name.casefold() == agent.directory
        and any(name.casefold() == agent.project_settings for name in files)
    )
    found = set()
    for scope, directory in chain(global_location, projects):
        try:
            installation = installation_at(directory, scope, agent)
            if installation is None:
                continue
            config_path, workspace_only, script_exists = installation
            resolved = config_path.resolve()
        except (OSError, ValueError) as error:
            if progress is not None:
                progress.clear()
            print(f"Could not inspect {directory}: {error}", file=sys.stderr)
            continue
        if resolved in found:
            continue
        found.add(resolved)
        yield scope, directory, (config_path, workspace_only, script_exists)


def resolve_search_root(search_root):
    root = (Path.home() if search_root is None else search_root.expanduser()).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Search path is not a directory: {root}")
    return root


def find_agent_directories(search_root, directory_names):
    root = resolve_search_root(search_root)
    names = set(directory_names or (agent.directory for agent in AGENTS.values()))
    with search_output(root) as (progress, write_result):
        for directory, _ in walk_directories(root, progress=progress, report_skipped=False):
            if directory.name in names:
                write_result(directory, str(directory))


def list_installations(search_root=None, *, agent=CODEX):
    root = resolve_search_root(search_root)
    found = False
    with search_output(root) as (progress, write_result):
        for scope, directory, (config_path, workspace_only, script_exists) in discover_installations(
            root, agent, include_global=search_root is None, progress=progress, report_skipped=False,
        ):
            found = True
            mode = "workspace-only" if workspace_only else "all requests"
            status = "" if script_exists else " (hook script missing)"
            write_result(directory, f"{scope}\t{mode}\t{config_path}{status}")

    if not found:
        print("No approval hook installations found.")


def registration_location(project, agent):
    if project is None:
        return "global", agent.home()
    workspace = project.expanduser().resolve()
    directory = workspace / agent.directory
    if not directory.is_dir():
        raise FileNotFoundError(f"No {agent.directory} directory found in {workspace}")
    return "project", directory


def install_hook(project=None, *, workspace_only=False, agent=CODEX):
    scope, directory = registration_location(project, agent)
    if project is None:
        hook_args = ["--workspace-only"] if workspace_only else []
        if workspace_only and agent is CLAUDE:
            hook_args.append("${CLAUDE_PROJECT_DIR}")
        directory.mkdir(parents=True, exist_ok=True)
    else:
        hook_args = workspace_arguments(directory.parent) if workspace_only else []

    script = directory / "hooks" / HOOK_FILENAME
    config_path = agent.settings_path(scope, directory)
    if agent is CLAUDE:
        handler = claude_hook(script, hook_args)
    elif agent is AGY:
        handler = agy_hook(script, hook_args)
    else:
        arguments = python_arguments(script, hook_args)
        handler = {
            "type": "command",
            "command": shlex.join(arguments),
            "timeout": 5,
            "statusMessage": agent.hook_status,
        }
        if sys.platform == "win32":
            handler["commandWindows"] = windows_install_command(arguments)

    with lock_hook_config(directory):
        original = hook_config(config_path)
        updated = deepcopy(original)
        installed = register_hook(updated, handler, script, agent, config_path.name)
        source = Path(__file__).read_bytes()
        if script.exists() and not installed and script.read_bytes() != source:
            raise FileExistsError(f"An existing hook script would be overwritten: {script}")
        write_atomically(script, source)
        if updated != original:
            write_hook_config(config_path, updated)
    print(f"Registered the {scope} hook in {config_path}")


def remove_unused_hook_script(script, config, config_path, agent):
    if not script.is_file() or script.resolve() != script or HOOK_FILENAME in json.dumps(config):
        return
    filenames = (agent.global_settings, agent.project_settings) if agent is CLAUDE else ("config.toml",)
    for filename in filenames:
        other_config = config_path.with_name(filename)
        if other_config != config_path and other_config.is_file():
            if HOOK_FILENAME in other_config.read_text(encoding="utf-8-sig"):
                return
    script.unlink(missing_ok=True)


def uninstall_registration(scope, directory, agent):
    config_path = agent.settings_path(scope, directory)
    script = directory / "hooks" / HOOK_FILENAME
    if config_path.is_file():
        with lock_hook_config(directory):
            config = hook_config(config_path)
            if unregister_hook(config, script, agent, config_path.name):
                write_hook_config(config_path, config)
                print(f"Unregistered the {scope} hook from {config_path}")
                remove_unused_hook_script(script, config, config_path, agent)
                return
    print(f"No {scope} approval hook registered in {config_path}")


def uninstall_hook(target=None, *, all_installations=False, agent=CODEX):
    if target is None and not all_installations:
        uninstall_registration("global", agent.home(), agent)
        return 0

    target = (Path.home() if target is None else target.expanduser()).resolve()
    if not all_installations:
        home = agent.home()
        if target == home.resolve():
            uninstall_registration("global", home, agent)
        else:
            scope, directory = registration_location(target, agent)
            if agent is CODEX and directory.resolve() == home.resolve():
                scope = "global"
            uninstall_registration(scope, directory, agent)
        return 0

    if not target.is_dir():
        raise NotADirectoryError(f"Search path is not a directory: {target}")
    installations = list(discover_installations(target, agent))
    if not installations:
        print(f"No approval hook installations found under {target}")
        return 0

    failed = False
    for scope, directory, (config_path, _, _) in installations:
        try:
            if not within_workspace(config_path, target):
                raise ValueError(f"Hook configuration resolves outside {target}")
            uninstall_registration(scope, directory, agent)
        except (OSError, ValueError) as error:
            print(f"Could not uninstall from {config_path}: {error}", file=sys.stderr)
            failed = True
    return int(failed)


def launch_codex(*, workspace_only=False):
    hook_args = workspace_arguments(Path.cwd().resolve()) if workspace_only else []
    windows = sys.platform == "win32"
    env = dict(os.environ)
    if windows:
        env["NoDefaultCurrentDirectoryInExePath"] = "1"

    codex = find_codex(env, windows=windows)
    with TemporaryDirectory(prefix="codex-approval-") as temporary:
        script = Path(temporary) / HOOK_FILENAME
        command = hook_command(script, env, windows=windows, hook_args=hook_args)
        write_atomically(script, Path(__file__).read_bytes())

        config = (
            'hooks.PermissionRequest=[{hooks=[{type="command",'
            f"command={json.dumps(command, ensure_ascii=False)},timeout=5"
            '}]}]'
        )
        return subprocess.call([*codex, "--no-daemon", "-c", config], env=env)


def launch_claude(*, workspace_only=False):
    if sys.platform == "win32":
        # Launch the native executable directly so the settings path is never parsed by cmd.exe.
        candidates = (Path(entry.strip('"')) / "claude.exe" for entry in os.get_exec_path())
        executable = next((str(path) for path in candidates if path.is_absolute() and path.is_file()), None)
    else:
        executable = shutil.which("claude")
    if executable is None:
        name = "claude.exe" if sys.platform == "win32" else "claude"
        raise FileNotFoundError(f"Claude Code executable ({name}) was not found on PATH.")

    hook_args = workspace_arguments(Path.cwd().resolve()) if workspace_only else []
    handler = claude_hook(Path(__file__).resolve(), hook_args)
    config = {"hooks": {"PermissionRequest": [{"hooks": [handler]}]}}
    with TemporaryDirectory(prefix="claude-approval-") as temporary:
        settings_path = Path(temporary) / "settings.json"
        write_hook_config(settings_path, config)
        return subprocess.call([executable, "--settings", str(settings_path)])


def command_arguments(arguments):
    # Keep existing command-line invocations working as hidden aliases.
    if not arguments or not arguments[0].startswith("-"):
        return arguments
    commands = {"--install": "install", "--launch": "launch"}
    for index, argument in enumerate(arguments):
        flag, equals, value = argument.partition("=")
        if flag == "--":
            break
        command = commands.get(flag)
        if command is None or (equals and flag != "--install"):
            continue
        options = arguments[:index] + arguments[index + 1:]
        if equals:
            options += ["--", value]
        return [command, *options]
    return arguments


def add_directory_argument(parser, help_text, *, optional=False):
    arguments = parser.add_argument_group("arguments")
    arguments.add_argument(
        "directory", metavar="DIR", nargs="?" if optional else None, type=Path, help=help_text,
    )
    options = parser.add_argument_group("options")
    options.add_argument("-h", "--help", action="help", help="show this help message and exit")
    return options


def add_agent_options(options, *, launch=False):
    targets = options.add_mutually_exclusive_group()
    for name, agent in AGENTS.items():
        if launch and agent is AGY:
            continue
        help_text = f"target {agent.name}"
        if agent is CODEX:
            help_text += " (default)"
        targets.add_argument(f"--{name}", action="store_const", const=agent, dest="agent", help=help_text)


class CommandParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, f"{self.prog}: error: {message}\n")


class AlphabeticalHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_arguments(self, actions):
        super().add_arguments(sorted(actions, key=self.option_name))

    @staticmethod
    def option_name(action):
        flags = action.option_strings
        if not flags:
            return ""
        long_flag = next((flag for flag in flags if flag.startswith("--")), flags[0])
        return long_flag.lstrip("-").casefold()


def main():
    arguments = sys.argv[1:]
    if arguments[:1] == ["--agy-hook"]:
        approve_agy_request(arguments[1:])
        return 0
    claude_hook_call = arguments[:1] == ["--claude-hook"]
    if claude_hook_call:
        arguments = arguments[1:]
    if not arguments and (claude_hook_call or not sys.stdin.isatty()):
        approve_request(claude=claude_hook_call)
        return 0
    if not claude_hook_call and arguments == ["--workspace-only"]:
        approve_request(Path.cwd().resolve())
        return 0
    if claude_hook_call and len(arguments) == 2 and arguments[0] == "--workspace-only":
        workspace = Path(arguments[1])
        if workspace.is_absolute():
            approve_request(workspace.resolve(), claude=True)
        return 0
    if len(arguments) == 2 and arguments[0] == "--workspace-root-hex":
        try:
            workspace = Path(os.fsdecode(bytes.fromhex(arguments[1])))
        except ValueError:
            return 0
        if workspace.is_absolute():
            approve_request(workspace, claude=claude_hook_call)
        return 0
    if claude_hook_call:
        return 2

    parser_options = {"formatter_class": AlphabeticalHelpFormatter}
    if sys.version_info >= (3, 14):
        parser_options["color"] = False
    find_flags = " ".join(f"[--{agent}]" for agent in sorted(AGENTS))
    target_flags = "[" + " | ".join(f"--{agent}" for agent in sorted(AGENTS)) + "]"
    command_help = {
        "install": (f"[DIR] {target_flags} [--workspace-only]", "register the hook globally or in a project"),
        "uninstall": (f"[DIR] {target_flags} [--all]", "unregister the hook globally or in a project"),
        "launch": ("[--claude | --codex] [--workspace-only]", "start a session with the hook"),
        "find": (f"[DIR] {find_flags}", "find agent configuration directories"),
        "hooks": (f"[DIR] {target_flags}", "show registered approval hooks"),
    }
    ordered_commands = sorted(command_help.items())
    width = max(map(len, command_help))
    parser = CommandParser(
        description=__doc__,
        usage="%(prog)s COMMAND ...",
        epilog="commands:\n" + "\n".join(
            f"  {name:<{width}}  {summary}" for name, (_, summary) in ordered_commands
        ),
        **parser_options,
    )
    subparsers = parser.add_subparsers(dest="command", prog=parser.prog, help=argparse.SUPPRESS)
    commands = {
        name: subparsers.add_parser(
            name,
            usage=f"%(prog)s {usage}",
            add_help=name not in ("install", "uninstall", "find", "hooks"),
            **parser_options,
        )
        for name, (usage, _) in ordered_commands
    }
    install_options = add_directory_argument(
        commands["install"], "project containing .codex, .claude, or .agents. Omit DIR to install globally",
        optional=True,
    )
    uninstall = commands["uninstall"]
    uninstall.description = "Remove the global hook by default."
    uninstall_options = add_directory_argument(
        uninstall, "project directory or search root with --all", optional=True,
    )
    uninstall_options.add_argument(
        "--all", action="store_true",
        help="uninstall all matching hooks under DIR recursively. If DIR is omitted, search the user home",
    )
    hooks = commands["hooks"]
    hooks.description = "Show the scope, approval mode, and configuration path for registered hooks."
    hooks_options = add_directory_argument(
        hooks, "directory to search recursively. Omit DIR to search the user home", optional=True,
    )
    find = commands["find"]
    find.description = "Print absolute paths. With no agent flags, search for all supported agents."
    find_options = add_directory_argument(
        find, "directory to search recursively. Omit DIR to search the user home", optional=True,
    )
    for name, agent in AGENTS.items():
        find_options.add_argument(
            f"--{name}", action="append_const", const=agent.directory, dest="agent_directories",
            help=f"include {agent.directory} directories",
        )
    for options in (install_options, uninstall_options, hooks_options):
        add_agent_options(options)
    add_agent_options(commands["launch"], launch=True)
    for options in (install_options, commands["launch"]):
        options.add_argument(
            "--workspace-only", action="store_true",
            help="auto-approve only requests with verifiable targets within the workspace",
        )

    args = parser.parse_args(command_arguments(arguments))
    agent = getattr(args, "agent", None) or CODEX
    if args.command == "launch" or (args.command == "install" and args.directory is not None):
        if not confirm_with_global_hook(agent):
            return 1

    if args.command == "install":
        install_hook(args.directory, workspace_only=args.workspace_only, agent=agent)
    elif args.command == "uninstall":
        return uninstall_hook(args.directory, all_installations=args.all, agent=agent)
    elif args.command == "launch":
        launch = launch_claude if agent is CLAUDE else launch_codex
        return launch(workspace_only=args.workspace_only)
    elif args.command == "hooks":
        list_installations(args.directory, agent=agent)
    elif args.command == "find":
        find_agent_directories(args.directory, args.agent_directories)
    else:
        parser.print_help()
    return 0


def cli():
    try:
        return main()
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(cli())
