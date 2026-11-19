from contextlib import redirect_stderr
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


class ApprovalHookTests(unittest.TestCase):
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
            handler = groups[-1]["hooks"][0]
            if "args" in handler:
                hook_command = [handler["command"], *handler["args"]]
            elif sys.platform == "win32" and "commandWindows" in handler:
                hook_command = handler["commandWindows"].split()
            else:
                hook_command = shlex.split(handler["command"])

            for target, expected in (
                (workspace / "노트.txt", approved),
                (root / "outside.txt", fallback),
                (Path("relative.txt"), fallback),
            ):
                with self.subTest(target=target):
                    result = subprocess.run(
                        hook_command,
                        cwd=workspace, env=env, input=json.dumps(make_request(workspace, target), ensure_ascii=False),
                        check=True, capture_output=True, encoding="utf-8",
                    )
                    response = json.loads(result.stdout) if result.stdout else None
                    self.assertEqual(response, expected, result.stderr)

            cli("uninstall", agent, ".")
            self.assertEqual(json.loads(config.read_text(encoding="utf-8")), original)
            self.assertFalse(script.exists())


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
                    project_settings.parent.mkdir(parents=True)
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
