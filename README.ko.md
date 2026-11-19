# Agent Auto Approve

[English](README.md) · **한국어**

`agent-auto-approve`는 Codex CLI, Claude Code, Antigravity CLI의 도구 승인 훅을 관리하는 Python CLI입니다. 프로젝트별 또는 전역으로 등록할 수 있습니다. Codex와 Claude Code는 새 세션 하나에 적용할 수도 있습니다.

## 설치

CLI는 Python 3.8 이상에서 실행됩니다. 아래 두 설치 방법은 모두 `uv`를 사용합니다. [`uv` 설치 방법](https://docs.astral.sh/uv/getting-started/installation/)

### PyPI에서 설치

패키지 이름으로 설치합니다. [PyPI 패키지](https://pypi.org/project/agent-auto-approve/)

```sh
uv tool install agent-auto-approve
```

### GitHub Releases에서 설치

릴리스의 **Assets**에서 wheel 파일(`.whl`)을 다운로드합니다. 다운로드한 폴더에서 아래 명령을 실행하고, 다른 버전을 받았다면 파일명을 바꿉니다. [GitHub Releases](https://github.com/jiind/agent-auto-approve/releases/latest)

```sh
uv tool install ./agent_auto_approve-0.1.2-py3-none-any.whl
```

설치가 끝나면 명령이 실행되는지 확인합니다.

```sh
agent-auto-approve --help
```

## 빠른 시작

`install`과 `launch`에서 `--workspace-only`를 생략하면 훅에 전달되는 승인 요청에 작업 경로 제한이 적용되지 않습니다. 작업 디렉터리 안에서만 자동 승인하려면 아래 예시처럼 이 옵션을 붙입니다.

설정할 프로젝트의 루트로 이동합니다. `.codex` 디렉터리가 있는 프로젝트에서 다음 명령으로 작업 범위 제한을 켜고 훅을 등록한 뒤 확인할 수 있습니다.

```sh
agent-auto-approve install . --workspace-only
agent-auto-approve hooks .
```

Codex 훅을 등록한 뒤 공유 로컬 앱 서버에 연결할 수 있으면 `install`이 설정을 다시 읽도록 요청합니다. 그 서버에 연결된 대화에서는 재시작 없이 새 훅을 불러올 수 있습니다. 별도로 실행 중인 세션에서는 새 Codex 대화를 열면 등록이 적용됩니다. 처음 등록하거나 변경한 훅은 CLI의 `/hooks` 또는 데스크톱 앱의 설정 → 훅에서 검토합니다. [Codex 훅 검토 문서](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)

새 Codex 세션 하나에서 써보려면 해당 프로젝트에서 다음 명령을 실행합니다.

```sh
agent-auto-approve launch --workspace-only
```

`launch`는 대상 에이전트의 CLI를 PATH에서 찾습니다. Windows에서 Claude Code 세션을 시작하려면 네이티브 `claude.exe`가 필요합니다. Claude Code 훅은 [`args`를 지원하는 2.1.139 이상](https://code.claude.com/docs/en/changelog)을 사용합니다.

Claude Code는 `--claude`로 선택합니다. `.claude`가 있는 프로젝트 루트에서 아래 명령을 실행하면 작업 범위를 제한한 훅을 등록하고 확인할 수 있습니다.

```sh
agent-auto-approve install --claude . --workspace-only
agent-auto-approve hooks --claude .
```

Claude Code는 설정 파일 변경을 감시하므로 열린 세션에서도 재시작 없이 훅 변경을 읽습니다. 새 세션 하나에만 적용하려면 `agent-auto-approve launch --claude --workspace-only`를 실행합니다. [Claude Code 설정 갱신](https://code.claude.com/docs/en/settings#when-edits-take-effect)

Antigravity CLI는 `--agy`로 선택합니다. `.agents`가 있는 프로젝트 루트에서 훅을 등록하고 확인한 뒤 `agy`를 실행합니다. 세션이 불러온 훅은 `/hooks`에서 확인할 수 있습니다. [Antigravity 훅 문서](https://antigravity.google/docs/hooks)

```sh
agent-auto-approve install --agy . --workspace-only
agent-auto-approve hooks --agy .
agy
```

## 명령

| 명령 | 동작 |
| --- | --- |
| `agent-auto-approve install [DIR] [--workspace-only]` | `DIR`을 지정하면 프로젝트에, 생략하면 사용자 전역에 훅을 등록합니다. 프로젝트에 대상 에이전트의 `.codex`, `.claude` 또는 `.agents`가 있어야 합니다. |
| `agent-auto-approve launch [--claude] [--workspace-only]` | 운영체제를 감지하고 훅을 적용한 새 세션을 시작합니다. Codex는 임시 훅 스크립트를, Claude Code는 임시 설정 파일을 사용하며 세션이 끝나면 해당 파일을 제거합니다. |
| `agent-auto-approve find [DIR] [--agy] [--claude] [--codex]` | `.agents`, `.claude`, `.codex` 디렉터리의 절대 경로를 한 줄에 하나씩 출력합니다. 옵션을 조합하면 선택한 디렉터리를, 생략하면 지원하는 디렉터리를 모두 찾습니다. |
| `agent-auto-approve hooks [DIR]` | 등록된 훅의 범위, 승인 모드, 설정 파일의 절대 경로를 출력합니다. |
| `agent-auto-approve uninstall [DIR] [--all]` | `DIR`을 지정하면 프로젝트의 훅을, 생략하면 전역 훅을 제거합니다. `--all`은 지정한 `DIR` 아래를 재귀 탐색하며, 이때 `DIR`을 생략하면 홈 아래를 탐색합니다. |

`install`, `hooks`, `uninstall`에는 `--agy`, `--claude`, `--codex` 중 하나를 지정할 수 있습니다. `launch`에는 `--claude` 또는 `--codex`를 지정할 수 있습니다. 이 명령들의 기본 대상은 Codex입니다.

| 대상 | 전역 등록 파일 | 프로젝트 등록 파일 |
| --- | --- | --- |
| Codex | `CODEX_HOME/hooks.json`, 기본 `~/.codex/hooks.json` | `DIR/.codex/hooks.json` |
| Claude Code | `CLAUDE_CONFIG_DIR/settings.json`, 기본 `~/.claude/settings.json` | `DIR/.claude/settings.local.json` |
| Antigravity CLI | `~/.gemini/config/hooks.json` | `DIR/.agents/hooks.json` |

Antigravity는 이 훅 설정 파일을 CLI, 앱, IDE에서 공통으로 읽습니다. [Antigravity 훅 설정 위치](https://antigravity.google/docs/hooks)

`find`와 `hooks`는 지정한 디렉터리와 그 하위를 탐색합니다. `DIR`을 생략하면 사용자 홈에서 시작합니다. 인자 없는 `hooks`는 홈 밖에 지정한 대상 에이전트의 전역 설정 디렉터리도 확인합니다. 접근할 수 없는 디렉터리는 건너뜁니다.

터미널에서는 진행 줄을 `디렉터리명...`으로 갱신하다가 대상을 찾으면 `디렉터리명... found`로 표시합니다. 색상을 지원하는 터미널에서는 `found`만 초록색입니다. 탐색이 끝나면 그 줄을 지우고 결과를 출력합니다.

`agent-auto-approve --help`로 명령 목록을 확인하고, `agent-auto-approve find --help`처럼 명령 뒤에 `--help`를 붙여 해당 명령의 인자와 옵션을 확인할 수 있습니다. `-h`도 사용할 수 있습니다.

## 자동 승인 범위

기본 모드는 훅에 전달된 도구 승인 요청을 자동 승인합니다. 사용자의 답변이 필요한 Claude Code와 Antigravity의 질문은 기존 흐름을 따릅니다. `--workspace-only`를 붙이면 대상 경로와 해당하는 경우 명령 실행 위치가 아래 기준 안에 있다고 확인된 경우에만 자동 승인합니다.

| 설정 방법 | 기준 디렉터리 |
| --- | --- |
| `agent-auto-approve install --workspace-only` | Codex는 세션의 작업 디렉터리, Claude Code는 세션이 시작된 프로젝트 루트, Antigravity는 훅의 `workspacePaths`에 전달된 작업 디렉터리를 사용합니다. |
| `agent-auto-approve install DIR --workspace-only` | 지정한 프로젝트 루트 `DIR` |
| `agent-auto-approve launch --workspace-only` | `launch`를 실행한 디렉터리 |

경로 판별은 단순한 POSIX `touch`·`mkdir` 명령, Codex의 명시적인 파일시스템 권한 요청, Claude Code와 Antigravity의 절대 경로를 지정한 기본 파일 도구를 지원합니다. Antigravity는 파일 읽기·생성·편집과 디렉터리 목록의 명시적 경로를 확인합니다. Antigravity 명령 요청에 실행 디렉터리(`Cwd`)가 없으면 명령의 대상 경로가 절대 경로일 때만 확인합니다. 작업 범위 밖의 경로나 확인하기 어려운 요청은 각 에이전트의 기존 승인 절차로 넘어갑니다. 예를 들어 `~/work/test`가 기준일 때 `touch ~/note.txt`는 홈 디렉터리에 파일을 생성하므로 기존 승인 절차를 따릅니다.

Claude Code의 명시적인 거부 규칙, 관리형 훅 설정, 작업 공간 신뢰 정책은 계속 적용됩니다. 네트워크 샌드박스 승인 창은 별도 경로로 처리됩니다. 전역 훅과 프로젝트 훅을 함께 설치하면 두 등록이 함께 적용될 수 있으므로, 작업 범위 제한이 필요하면 적용되는 등록의 모드를 확인합니다. [Claude Code 훅 문서](https://code.claude.com/docs/en/hooks#permissionrequest)

같은 에이전트에 이 도구의 전역 훅이 등록돼 있으면 프로젝트 `install DIR` 또는 `launch` 전에 전역 설정 경로와 승인 모드를 경고하고 계속할지 묻습니다. `y`를 입력하면 진행하고, `n`이나 빈 입력이면 중단합니다.

## 제거

프로젝트 루트에서 `agent-auto-approve uninstall .`을 실행하면 해당 프로젝트의 등록을 제거합니다. 전역 등록은 `agent-auto-approve uninstall`로 제거할 수 있으며, 홈 밖에 설정한 전역 등록도 이 명령에 해당합니다. Claude Code는 `--claude`, Antigravity는 `--agy`를 붙입니다. 이 도구가 제거하는 범위는 자신이 등록한 훅입니다.

제거된 훅을 이미 불러온 세션도 일반 승인 흐름을 계속 사용할 수 있습니다. Codex의 공유 로컬 앱 서버는 제거도 즉시 반영할 수 있습니다. 이전 버전에서 등록한 훅을 `uninstall`하면 열린 세션을 위해 호환용 스크립트를 남깁니다. 해당 세션이 기억한 훅 명령에는 CLI의 Python 경로가 들어 있으므로 CLI까지 제거할 때는 세션을 먼저 종료합니다.

등록된 훅을 제거한 뒤 다음 명령으로 CLI를 제거할 수 있습니다.

```sh
uv tool uninstall agent-auto-approve
```

## 패키지 빌드

소스에서 설치하려면 저장소를 복제하고 `pyproject.toml`이 있는 루트에서 `uv tool install .`을 실행합니다.

저장소 루트에서 `uv build`를 실행하면 `dist/`에 wheel과 소스 배포 파일이 생성됩니다.

## 기여 및 보안 제보

- [기여 안내](CONTRIBUTING.ko.md)
- [보안 문제 제보](SECURITY.ko.md)
