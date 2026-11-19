# Agent Auto Approve

**English** · [한국어](https://github.com/jiind/agent-auto-approve/blob/main/README.ko.md)

`agent-auto-approve` is a Python CLI for managing tool approval hooks for Codex CLI, Claude Code, and Antigravity CLI. You can register hooks for a project or for your user account. With Codex and Claude Code, you can also apply a hook to a single new session.

## Installation

The CLI requires Python 3.8 or later. Both installation methods use `uv`. [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

### From PyPI

Install using the package name. [PyPI package](https://pypi.org/project/agent-auto-approve/)

```sh
uv tool install agent-auto-approve
```

### From GitHub Releases

Download the wheel (`.whl`) from the release's **Assets**. Run the command below in your download directory and substitute the filename if you downloaded a different version. [GitHub Releases](https://github.com/jiind/agent-auto-approve/releases/latest)

```sh
uv tool install ./agent_auto_approve-0.1.1-py3-none-any.whl
```

Check that the CLI runs after installation.

```sh
agent-auto-approve --help
```

## Quick start

By default, `install` and `launch` apply no workspace path restriction to approval requests passed to the hook. Add `--workspace-only` as shown below to limit automatic approval to your workspace.

Go to the root of the project you want to set up. For a project with a `.codex` directory, register a hook scoped to the workspace and check the registration.

```sh
agent-auto-approve install . --workspace-only
agent-auto-approve hooks .
```

To try the hook in a single new Codex session, run this command from the project directory.

```sh
agent-auto-approve launch --workspace-only
```

`launch` looks for the selected agent's CLI on your PATH. On Windows, launching Claude Code requires the native `claude.exe`. Claude Code hooks require version 2.1.139 or later for `args` support. [Claude Code changelog](https://code.claude.com/docs/en/changelog)

Use `--claude` for Claude Code. From a project root containing `.claude`, register a hook scoped to the workspace and check the registration.

```sh
agent-auto-approve install --claude . --workspace-only
agent-auto-approve hooks --claude .
```

To apply the hook to a single new Claude Code session, run `agent-auto-approve launch --claude --workspace-only`.

Use `--agy` for Antigravity CLI. From a project root containing `.agents`, register the hook, check the registration, and then run `agy`. [Antigravity CLI reference](https://antigravity.google/docs/cli/reference/)

```sh
agent-auto-approve install --agy . --workspace-only
agent-auto-approve hooks --agy .
agy
```

## Commands

| Command | Behavior |
| --- | --- |
| `agent-auto-approve install [DIR] [--workspace-only]` | Registers a project hook when you supply `DIR` and a global hook for your user account when you omit it. The project must contain the selected agent's `.codex`, `.claude`, or `.agents` directory. |
| `agent-auto-approve launch [--claude] [--workspace-only]` | Detects the operating system and starts a new session with the hook. Codex uses a temporary hook script and Claude Code uses a temporary settings file. The temporary file is removed when the session ends. |
| `agent-auto-approve find [DIR] [--agy] [--claude] [--codex]` | Prints absolute paths to `.agents`, `.claude`, and `.codex` directories, one per line. Combine agent flags to select specific directory types. With no flags, it searches for all supported types. |
| `agent-auto-approve hooks [DIR]` | Shows the scope, approval mode, and absolute settings file path for registered hooks. |
| `agent-auto-approve uninstall [DIR] [--all]` | Removes the project hook when you supply `DIR` and the global hook when you omit it. `--all` searches recursively under `DIR` or under your home directory if you omit `DIR`. |

`install`, `hooks`, and `uninstall` accept one of `--agy`, `--claude`, and `--codex`. `launch` accepts `--claude` or `--codex`. These commands default to Codex.

| Agent | Global settings file | Project settings file |
| --- | --- | --- |
| Codex | `CODEX_HOME/hooks.json`, defaults to `~/.codex/hooks.json` | `DIR/.codex/hooks.json` |
| Claude Code | `CLAUDE_CONFIG_DIR/settings.json`, defaults to `~/.claude/settings.json` | `DIR/.claude/settings.local.json` |
| Antigravity CLI | `~/.gemini/config/hooks.json` | `DIR/.agents/hooks.json` |

The Antigravity CLI, app, and IDE read the same hook settings files. [Antigravity hook settings](https://antigravity.google/docs/hooks)

`find` and `hooks` search the specified directory and its descendants. When you omit `DIR`, the search starts in your home directory. In that case, `hooks` also checks the selected agent's global configuration directory if it is set outside your home directory. The commands skip inaccessible directories.

In a terminal, the progress line shows `directory...` and changes to `directory... found` when it finds a match. In terminals that support color, only `found` appears in green. The command clears the progress line before printing the results.

Run `agent-auto-approve --help` to list commands. Add `--help` to a command, as in `agent-auto-approve find --help`, to see its arguments and options. You can also use `-h`.

## Automatic approval scope

By default, the hook automatically approves tool approval requests it receives. Claude Code and Antigravity questions that require a user response use their usual prompt flow. With `--workspace-only`, the hook approves a request only when it can verify that the target path and, where applicable, the command's working directory are within the boundary below.

| Setup command | Workspace boundary |
| --- | --- |
| `agent-auto-approve install --workspace-only` | Codex uses the session's working directory. Claude Code uses the project root where the session started. Antigravity uses the working directories supplied in the hook's `workspacePaths`. |
| `agent-auto-approve install DIR --workspace-only` | The specified project root `DIR` |
| `agent-auto-approve launch --workspace-only` | The directory where you ran `launch` |

Path checks support simple POSIX `touch` and `mkdir` commands, explicit Codex filesystem permission requests, and basic Claude Code and Antigravity file tools that receive absolute paths. For Antigravity, the hook checks explicit paths for file reads, creation, edits, and directory listings. If an Antigravity command request omits the working directory (`Cwd`), the hook can check the target only when it is an absolute path. Requests involving paths outside the workspace or paths the hook cannot verify go through the agent's usual approval flow. For example, if the boundary is `~/work/test`, `touch ~/note.txt` goes through the usual approval flow because it would create a file in your home directory.

Claude Code's explicit deny rules, managed hook settings, and workspace trust policies still apply. Network sandbox prompts are handled separately. A global hook and a project hook can both apply to the same session. Check the mode of each applicable registration if you need approval limited to the workspace. [Claude Code hook reference](https://code.claude.com/docs/en/hooks#permissionrequest)

If a global hook from this tool is registered for the same agent, a project `install DIR` or `launch` shows the global settings path and approval mode and asks whether to continue. Enter `y` to continue. Enter `n` or press Enter without a response to cancel.

## Uninstall

To remove a project hook, run `agent-auto-approve uninstall .` from the project root. To remove a global hook, run `agent-auto-approve uninstall`. This also works when the global settings are outside your home directory. Add `--claude` for Claude Code or `--agy` for Antigravity. The tool removes only hooks it registered.

After removing the registered hooks, uninstall the CLI.

```sh
uv tool uninstall agent-auto-approve
```

## Building the package

To install from source, clone the repository and run `uv tool install .` from the root directory containing `pyproject.toml`.

Run `uv build` from the repository root to create a wheel and a source distribution in `dist/`.

## Contributing and reporting security issues

- [Contributing guide](https://github.com/jiind/agent-auto-approve/blob/main/CONTRIBUTING.md)
- [Reporting security issues](https://github.com/jiind/agent-auto-approve/blob/main/SECURITY.md)
