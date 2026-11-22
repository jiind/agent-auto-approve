from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import codex_approval_hook as approval_hook


PERMISSION_ALLOW = {
    "hookSpecificOutput": {
        "hookEventName": "PermissionRequest",
        "decision": {"behavior": "allow"},
    }
}
EXISTING_HOOK = {"hooks": [{"type": "command", "command": "existing-hook"}]}
SOURCE = Path(approval_hook.__file__).resolve()


def hook_argv(handler):
    if "args" in handler:
        return [handler["command"], *handler["args"]]
    if sys.platform == "win32" and "commandWindows" in handler:
        return handler["commandWindows"].split()
    return shlex.split(handler["command"])


class ApprovalHookTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "requires Windows PowerShell")
    def test_windows_hook_command_preserves_stdin(self):
        payload = '{"name":"노트"}'.encode("utf-8")
        command = approval_hook.windows_install_command(
            [sys.executable, "-I", "-X", "utf8", "-c",
             "import sys; print(sys.stdin.buffer.read().hex()); print(sys.argv[1])",
             "argument with spaces"],
        )
        result = subprocess.run(
            command.split(), input=payload, capture_output=True, check=True, timeout=15,
        )
        self.assertEqual(
            result.stdout.decode("ascii").splitlines(),
            [payload.hex(), "argument with spaces"],
            result.stderr.decode("utf-8", errors="replace"),
        )

    def test_global_registration_and_removal(self):
        for agent, settings in (
            ("--codex", "custom-codex/hooks.json"),
            ("--claude", "custom-claude/settings.json"),
            ("--agy", ".gemini/config/hooks.json"),
        ):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary).resolve()
                env = dict(
                    os.environ, HOME=str(home), USERPROFILE=str(home),
                    CODEX_HOME=str(home / "custom-codex"),
                    CLAUDE_CONFIG_DIR=str(home / "custom-claude"),
                )
                config = home / settings
                config.parent.mkdir(parents=True)
                original = {"unrelated_setting": True}
                config.write_text(json.dumps(original), encoding="utf-8")
                script = config.parent / "hooks" / SOURCE.name

                def cli(*args):
                    return subprocess.run(
                        [sys.executable, str(SOURCE), *args, agent],
                        cwd=home, env=env, check=True, capture_output=True, text=True,
                    ).stdout

                cli("install", "--workspace-only")
                self.assertIn(f"global\tworkspace-only\t{config}", cli("hooks"))
                self.assertTrue(script.is_file())
                cli("uninstall")
                self.assertFalse(script.exists())
                self.assertIn("No approval hook installations found.", cli("hooks"))
                remaining = json.loads(config.read_text(encoding="utf-8"))
                self.assertEqual(remaining.get("unrelated_setting"), True)

    def test_codex_project_registration_and_workspace_scope(self):
        def request(workspace, target):
            return {
                "hook_event_name": "PermissionRequest",
                "cwd": str(workspace),
                "tool_name": "request_permissions",
                "tool_input": {"permissions": {"file_system": {"write": [str(target)]}}},
            }

        self.check_project_hook(
            "--codex", ".codex/hooks.json", "hooks", "PermissionRequest",
            {"hooks": {"PermissionRequest": [EXISTING_HOOK]}},
            request, PERMISSION_ALLOW, None,
        )

    def test_hooks_current_checks_project_root_and_global_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            project = root / "project"
            nested = project / "nested"
            nested.mkdir(parents=True)
            global_dir = root / "custom-codex"
            env = dict(os.environ, CODEX_HOME=str(global_dir))

            def cli(*args, answer=""):
                return subprocess.run(
                    [sys.executable, str(SOURCE), *args], cwd=project, env=env,
                    input=answer, check=True, capture_output=True, text=True,
                ).stdout

            global_config = global_dir / "hooks.json"
            project_config = project / ".codex" / "hooks.json"
            nested_config = nested / ".codex" / "hooks.json"
            self.assertIn(f"Registered Codex global hook (all requests) in {global_config}", cli("install"))
            self.assertIn(
                f"Registered Codex project hook (workspace-only) in {project_config}",
                cli("install", ".", "--workspace-only", answer="y\n"),
            )
            cli("install", "nested", "--workspace-only", answer="y\n")

            global_row = f"global\tall requests\t{global_config}"
            project_row = f"project\tworkspace-only\t{project_config}"
            nested_row = f"project\tworkspace-only\t{nested_config}"
            self.assertEqual(cli("hooks", "--current").splitlines(), [global_row, project_row])
            self.assertEqual(cli("hooks", "--current", "nested").splitlines(), [global_row, nested_row])
            self.assertEqual(cli("hooks", ".").splitlines(), [project_row, nested_row])

    def test_codex_install_requests_reload_without_editing_user_config(self):
        for response in ({"result": {}}, {"error": {"message": "Reload unavailable"}}):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as temporary:
                settings = Path(temporary).resolve()
                connection = mock.Mock()
                connection.recv.side_effect = [
                    json.dumps({"id": 1, "result": {}}),
                    json.dumps({"method": "config/changed"}),
                    json.dumps({"id": 2, **response}),
                ]
                output = io.StringIO()
                arguments = [str(SOURCE), "install", "--workspace-only"]
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(approval_hook.Agent, "home", return_value=settings))
                    stack.enter_context(mock.patch.object(sys, "argv", arguments))
                    stack.enter_context(redirect_stdout(output))
                    stack.enter_context(mock.patch.object(approval_hook.socket, "AF_UNIX", 1, create=True))
                    stack.enter_context(mock.patch.object(Path, "is_socket", return_value=True))
                    connect = stack.enter_context(mock.patch("websockets.sync.client.unix_connect"))
                    connect.return_value.__enter__.return_value = connection
                    self.assertEqual(approval_hook.cli(), 0)
                messages = [json.loads(call.args[0]) for call in connection.send.call_args_list]
                self.assertEqual([message["method"] for message in messages],
                                 ["initialize", "initialized", "config/batchWrite"])
                self.assertEqual(messages[-1]["params"], {"edits": [], "reloadUserConfig": True})
                self.assertTrue((settings / "hooks.json").is_file())
                self.assertEqual("Requested a hook configuration reload" in output.getvalue(), "result" in response)

    def test_uninstall_disables_cached_legacy_hook(self):
        cases = (
            (approval_hook.CODEX, [], {"hook_event_name": "PermissionRequest"}, None),
            (approval_hook.CLAUDE, ["--claude-hook"], {"hook_event_name": "PermissionRequest"}, None),
            (approval_hook.AGY, ["--agy-hook"], {"toolCall": {"name": "read_file", "args": {}}},
             {"decision": "allow"}),
        )
        for agent, flags, request, fallback in cases:
            for upgrade in (False, True):
                with self.subTest(agent=agent.name, upgrade=upgrade):
                    self.check_legacy_hook_removal(agent, flags, request, fallback, upgrade)

    def check_legacy_hook_removal(self, agent, flags, request, fallback, upgrade):
        with tempfile.TemporaryDirectory(prefix="approval test ") as temporary:
            workspace = Path(temporary).resolve()
            settings = workspace / agent.directory
            config_path = settings / agent.project_settings
            script = config_path.parent / "hooks" / SOURCE.name
            script.parent.mkdir(parents=True)
            script.write_bytes(SOURCE.read_bytes())
            arguments = approval_hook.python_arguments(script, flags)
            handler = {
                "type": "command",
                "command": shlex.join(arguments),
                "statusMessage": agent.hook_status,
            }
            if agent is approval_hook.CLAUDE:
                handler.update(command=arguments[0], args=arguments[1:])
            elif agent is approval_hook.AGY and sys.platform == "win32":
                handler["command"] = approval_hook.windows_install_command(arguments, executable="powershell.exe")
            key, event = approval_hook.approval_group_keys(agent)
            approval_hook.write_hook_config(
                config_path, {key: {event: [{"hooks": [handler]}]}},
            )
            if upgrade:
                approval_hook.install_hook(workspace, agent=agent)
                approval_hook.install_hook(workspace, workspace_only=True, agent=agent)

            self.assertEqual(approval_hook.uninstall_hook(workspace, agent=agent), 0)
            self.assertIsNone(approval_hook.installation_at(settings, "project", agent))
            cached = subprocess.run(arguments, input=json.dumps(request), capture_output=True, text=True, check=True)
            self.assertEqual(cached.stderr, "")
            self.assertEqual(json.loads(cached.stdout) if cached.stdout else None, fallback)

            approval_hook.install_hook(workspace, agent=agent)
            self.assertTrue(script.read_bytes().startswith(SOURCE.read_bytes()))

    def test_claude_removal_preserves_script_referenced_by_encoded_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            settings = workspace / ".claude"
            settings.mkdir()
            agent = approval_hook.CLAUDE
            with mock.patch.object(approval_hook.Agent, "home", return_value=settings):
                with mock.patch.object(sys, "platform", "win32"):
                    approval_hook.install_hook(agent=agent)
                    approval_hook.install_hook(workspace, agent=agent)
                    self.assertEqual(approval_hook.uninstall_hook(agent=agent), 0)
                    self.assertTrue(approval_hook.installation_at(settings, "project", agent)[2])
                    self.assertEqual(approval_hook.uninstall_hook(workspace, agent=agent), 0)
            self.assertFalse((settings / "hooks" / SOURCE.name).exists())

    def test_hook_yields_when_installation_python_is_missing(self):
        for agent in approval_hook.AGENTS.values():
            with self.subTest(agent=agent.name), tempfile.TemporaryDirectory(prefix="approval test ") as temporary:
                workspace = Path(temporary).resolve()
                settings = workspace / agent.directory
                settings.mkdir()
                with mock.patch.object(sys, "executable", str(workspace / "missing-python.exe")):
                    approval_hook.install_hook(workspace, agent=agent)
                config = approval_hook.hook_config(settings / agent.project_settings)
                key, event = approval_hook.approval_group_keys(agent)
                handler = config[key][event][0]["hooks"][0]
                cached = subprocess.run(hook_argv(handler), input="{}", capture_output=True, text=True, check=True)
                fallback = {"decision": "allow"} if agent is approval_hook.AGY else None
                self.assertEqual(cached.stderr, "")
                self.assertEqual(json.loads(cached.stdout) if cached.stdout else None, fallback)

    def test_claude_project_registration_and_workspace_scope(self):
        def request(workspace, target):
            return {
                "hook_event_name": "PermissionRequest",
                "cwd": str(workspace),
                "tool_name": "Read",
                "tool_input": {"file_path": str(target)},
            }

        self.check_project_hook(
            "--claude", ".claude/settings.local.json", "hooks", "PermissionRequest",
            {"hooks": {"PermissionRequest": [EXISTING_HOOK]}},
            request, PERMISSION_ALLOW, None,
        )

    def test_antigravity_project_registration_and_workspace_scope(self):
        def request(workspace, target):
            return {"toolCall": {"name": "read_file", "args": {"Path": str(target)}}}

        self.check_project_hook(
            "--agy", ".agents/hooks.json", "codex-auto-approve", "PreToolUse",
            {"existing-hook": {"PreToolUse": [{"matcher": "*", **EXISTING_HOOK}]}},
            request, {"decision": "auto_approve"}, {"decision": "allow"},
        )

    def check_project_hook(self, agent, settings, event_key, group_key, original,
                           make_request, approved, fallback):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "project"
            config = workspace / settings
            config.parent.mkdir(parents=True)
            script = config.parent / "hooks" / "codex_approval_hook.py"
            config.write_text(json.dumps(original), encoding="utf-8")
            home = root / "home"
            home.mkdir()
            env = dict(
                os.environ, HOME=str(home), USERPROFILE=str(home),
                CODEX_HOME=str(home / ".codex"), CLAUDE_CONFIG_DIR=str(home / ".claude"),
            )

            def cli(*args):
                return subprocess.run(
                    [sys.executable, str(SOURCE), *args],
                    cwd=workspace, env=env, check=True, capture_output=True, text=True,
                ).stdout

            cli("install", agent, ".", "--workspace-only")
            cli("install", agent, ".", "--workspace-only")
            installed = json.loads(config.read_text(encoding="utf-8"))
            groups = installed[event_key][group_key]
            original_groups = original.get(event_key, {}).get(group_key, [])
            self.assertEqual(groups[:-1], original_groups)
            self.assertEqual(len(groups), len(original_groups) + 1)
            for name in original.keys() - {event_key}:
                self.assertEqual(installed[name], original[name])
            self.assertIn("workspace-only", cli("hooks", agent, "."))
            self.assertIn(f"project\tworkspace-only\t{config}", cli("hooks", agent, "--current"))
            handler = groups[-1]["hooks"][0]
            hook_command = hook_argv(handler)

            def run_hook(target):
                return subprocess.run(
                    hook_command,
                    cwd=workspace, env=env, input=json.dumps(make_request(workspace, target), ensure_ascii=False),
                    check=True, capture_output=True, encoding="utf-8",
                )

            for target, expected in (
                (workspace / "노트.txt", approved),
                (root / "outside.txt", fallback),
                (Path("relative.txt"), fallback),
            ):
                with self.subTest(target=target):
                    result = run_hook(target)
                    response = json.loads(result.stdout) if result.stdout else None
                    self.assertEqual(response, expected, result.stderr)

            cli("uninstall", agent, ".")
            self.assertEqual(json.loads(config.read_text(encoding="utf-8")), original)
            self.assertFalse(script.exists())
            cached = run_hook(workspace / "노트.txt")
            self.assertEqual(cached.stderr, "")
            self.assertEqual(json.loads(cached.stdout) if cached.stdout else None, fallback)


class LaunchTests(unittest.TestCase):
    def test_codex_launch_uses_session_script_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory(prefix="approval test ") as temporary:
            root = Path(temporary).resolve()
            old_script = root / ".codex" / SOURCE.name
            old_script.parent.mkdir()
            old_script.write_bytes(b"existing user file")
            env = {"HOME": str(root), "USERPROFILE": str(root)}
            workspace_hex = os.fsencode(Path.cwd().resolve()).hex()

            def run_codex(args, *, env):
                self.assertEqual(args[:3], ["codex-test", "--no-daemon", "-c"])
                self.assertEqual(len(args), 4)
                script, = root.glob(f"codex-approval-*/{SOURCE.name}")
                self.assertEqual(script.read_bytes(), SOURCE.read_bytes())
                self.assertEqual(old_script.read_bytes(), b"existing user file")
                config = args[3]
                self.assertTrue(config.startswith("hooks.PermissionRequest="))
                command = json.loads(config.partition("command=")[2].rsplit(",timeout=", 1)[0])
                self.assertTrue(command.endswith(f"--workspace-root-hex {workspace_hex}"))
                if sys.platform == "win32":
                    self.assertIn(os.fsencode(script).hex(), command)
                else:
                    self.assertEqual(Path(shlex.split(command)[4]).resolve(), script)
                return 7

            with mock.patch.dict(os.environ, env), mock.patch.object(tempfile, "tempdir", str(root)):
                with mock.patch.object(approval_hook, "find_codex", return_value=["codex-test"]):
                    with mock.patch.object(approval_hook.subprocess, "call", side_effect=run_codex) as call:
                        self.assertEqual(approval_hook.launch_codex(workspace_only=True), 7)
                        call.assert_called_once()
            self.assertEqual(old_script.read_bytes(), b"existing user file")
            self.assertEqual(list(root.glob("codex-approval-*")), [])

    def test_claude_launch_cleans_up_session_settings(self):
        with tempfile.TemporaryDirectory(prefix="approval test ") as temporary:
            root = Path(temporary).resolve()
            executable = root / ("claude.exe" if sys.platform == "win32" else "claude")
            executable.touch()
            executable.chmod(0o700)
            workspace_hex = os.fsencode(Path.cwd().resolve()).hex()

            def run_claude(args):
                self.assertEqual(args[:2], [str(executable), "--settings"])
                self.assertEqual(len(args), 3)
                settings = Path(args[2])
                self.assertEqual(settings.parent.parent, root)
                config = json.loads(settings.read_text(encoding="utf-8"))
                handler = config["hooks"]["PermissionRequest"][0]["hooks"][0]
                self.assertEqual(handler["args"][-3:], ["--claude-hook", "--workspace-root-hex", workspace_hex])
                return 7

            with mock.patch.dict(os.environ, {"PATH": str(root)}):
                with mock.patch.object(tempfile, "tempdir", str(root)):
                    with mock.patch.object(approval_hook.subprocess, "call", side_effect=run_claude) as call:
                        self.assertEqual(approval_hook.launch_claude(workspace_only=True), 7)
                        call.assert_called_once()
            self.assertEqual(list(root.glob("claude-approval-*")), [])


class GlobalHookConfirmationTests(unittest.TestCase):
    def test_project_install_confirms_existing_global_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "project"
            workspace.mkdir()
            for agent, config_dir, settings in (
                ("--codex", ".codex", "hooks.json"),
                ("--claude", ".claude", "settings.local.json"),
                ("--agy", ".agents", "hooks.json"),
            ):
                with self.subTest(agent=agent):
                    home = root / agent[2:]
                    env = dict(
                        os.environ, HOME=str(home), USERPROFILE=str(home),
                        CODEX_HOME=str(home / "custom-codex"),
                        CLAUDE_CONFIG_DIR=str(home / "custom-claude"),
                    )
                    project_settings = workspace / config_dir / settings
                    if agent != "--codex":
                        project_settings.parent.mkdir()
                    subprocess.run(
                        [sys.executable, str(SOURCE), "install", agent, "--workspace-only"],
                        cwd=workspace, env=env, input="", check=True, capture_output=True, text=True,
                    )

                    for answer, status in (("n\n", 1), ("", 1), ("y\n", 0)):
                        with self.subTest(answer=answer):
                            result = subprocess.run(
                                [sys.executable, str(SOURCE), "install", agent, "."],
                                cwd=workspace, env=env, input=answer, capture_output=True, text=True,
                            )
                            self.assertEqual(result.returncode, status)
                            self.assertIn("global approval hook (workspace-only)", result.stderr)
                            self.assertIn("Continue? [y/n]", result.stderr)
                            self.assertEqual(project_settings.exists(), status == 0)
                            if agent == "--codex":
                                self.assertEqual(project_settings.parent.exists(), status == 0)

    def test_launch_confirms_existing_global_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            env = {"CODEX_HOME": str(root / ".codex"), "CLAUDE_CONFIG_DIR": str(root / ".claude")}
            with mock.patch.dict(os.environ, env):
                for flag, agent, launch in (
                    ("--codex", approval_hook.CODEX, "launch_codex"),
                    ("--claude", approval_hook.CLAUDE, "launch_claude"),
                ):
                    with self.subTest(agent=flag):
                        subprocess.run(
                            [sys.executable, str(SOURCE), "install", flag],
                            input="", check=True, capture_output=True, text=True,
                        )
                        argv = [str(SOURCE), "launch", flag, "--workspace-only"]
                        with mock.patch.object(approval_hook, launch, return_value=7) as run:
                            for answer, status in (("n\n", 1), ("y\n", 7)):
                                with self.subTest(answer=answer):
                                    warning = io.StringIO()
                                    with mock.patch.object(sys, "argv", argv), redirect_stderr(warning):
                                        with mock.patch.object(sys, "stdin", io.StringIO(answer)):
                                            self.assertEqual(approval_hook.cli(), status)
                                    self.assertIn("global approval hook (all requests)", warning.getvalue())
                                    self.assertIn(str(agent.home()), warning.getvalue())
                                    if status == 1:
                                        run.assert_not_called()
                            run.assert_called_once_with(workspace_only=True)
