# Agent Auto Approve 작업 지침

이 저장소의 사용자용 설치 방법과 명령은 [README.md](README.md)에 있습니다. 패키지와 실행 명령의 이름은 `agent-auto-approve`이며, CLI와 훅은 [codex_approval_hook.py](codex_approval_hook.py)에 구현되어 있습니다.

## 사용자가 설정을 요청했을 때

1. `agent-auto-approve --help`로 CLI가 설치되어 있는지 확인합니다. 설치가 필요하면 `pyproject.toml`이 있는 이 저장소의 루트에서 `uv tool install .`을 실행합니다. 저장소 루트와 훅을 등록할 프로젝트 루트는 서로 다를 수 있습니다.
2. 프로젝트에 등록하려면 대상 루트의 `.codex`, `.claude` 또는 `.agents`를 확인합니다. 위치를 모르면 `agent-auto-approve find DIR`에 `--codex`, `--claude` 또는 `--agy`를 붙여 탐색합니다. `install`의 `DIR`에는 찾은 설정 디렉터리의 상위 프로젝트 루트를 전달합니다.
3. 아래 표에서 요청한 등록 범위의 명령을 사용합니다. 기본 대상은 Codex입니다. Claude Code는 `--claude`, Antigravity는 `--agy`로 선택합니다. `launch`의 대상은 Codex와 Claude Code입니다. 작업 범위 안에서만 자동 승인하도록 요청받았다면 등록 명령이나 `launch`에 `--workspace-only`를 추가합니다.
4. 영구 등록 후 `hooks`의 결과에서 요청한 설정 파일 경로와 승인 모드를 확인합니다. 출력되는 모드는 `workspace-only` 또는 `all requests`입니다.

| 요청 범위 | 실행 명령 | 등록 확인 |
| --- | --- | --- |
| 특정 프로젝트 | `agent-auto-approve install DIR` | `agent-auto-approve hooks DIR`에서 대상 설정 파일의 경로 확인 |
| 전역 | `agent-auto-approve install` | `agent-auto-approve hooks`에서 `global` 행 확인 |
| 새 세션 하나 | 대상 디렉터리에서 `agent-auto-approve launch` | 실행된 세션에서 확인 |

전역 등록 경로만 확인하려면 `hooks DIR`에 대상 에이전트의 전역 설정 디렉터리를 전달합니다. Codex는 `CODEX_HOME` 또는 기본값 `~/.codex`, Claude Code는 `CLAUDE_CONFIG_DIR` 또는 기본값 `~/.claude`, Antigravity는 `~/.gemini/config`를 사용합니다. `launch --workspace-only`의 작업 범위는 실행 디렉터리입니다.

사용자가 설정 제거를 요청하면 프로젝트는 `uninstall DIR`, 전역은 `uninstall`을 사용합니다. `uninstall --all`은 홈 아래의 등록을 재귀적으로 제거하는 옵션입니다. CLI 자체의 제거를 요청했다면 훅 등록을 먼저 제거한 뒤 `uv tool uninstall agent-auto-approve`를 실행합니다.

## 소스 변경 검증

저장소 루트에서 `python3 codex_approval_hook.py --help` 또는 `python3 codex_approval_hook.py <명령> --help`로 명령 구문을 확인할 수 있습니다. 등록과 제거를 검증할 때는 임시 사용자 홈과 임시 프로젝트를 사용합니다.
