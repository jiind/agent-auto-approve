# Agent Auto Approve 작업 지침

이 저장소의 사용자용 설치 방법과 명령은 [README.md](README.md)에 있다. 패키지와 실행 명령의 이름은 `agent-auto-approve`이며, CLI와 훅은 [codex_approval_hook.py](codex_approval_hook.py)에 구현되어 있다.

## 요청 처리

사용자가 등록, 확인 또는 제거를 요청하면 대상 에이전트와 범위를 확인하고 해당 절차를 끝낸다. 대상 위치는 먼저 읽기 전용으로 확인한다. 요청의 핵심인 대상이나 범위가 불분명하면 확인 가능한 설정과 경로를 먼저 조사한 뒤 필요한 결정을 묻는다. 실제 적용된 파일, 모드, 검증 결과를 간결하게 알린다.

관련 스킬의 일반 권고보다 사용자 지시를 우선한다. 스킬의 지침으로 작업을 중단하거나 경로를 바꿔야 하면 해당 `SKILL.md`와 적용 문구를 알린다. 이 저장소의 일반 작업은 직접 처리하고, 위임이 승인된 경우 독립된 검토나 재현 작업에 구체적인 완료 조건을 준다.

## 등록과 확인

1. `agent-auto-approve --help`로 CLI가 설치되어 있는지 확인한다. 설치가 필요하면 `pyproject.toml`이 있는 이 저장소의 루트에서 `uv tool install .`을 실행한다. 저장소 루트와 훅을 등록할 프로젝트 루트는 서로 다를 수 있다.
2. 프로젝트에 등록하려면 `install`의 `DIR`에 기존 프로젝트 루트를 전달한다. Codex는 루트에 `.codex`가 없으면 생성한다. Claude Code는 루트에 `.claude`가, Antigravity는 `.agents`가 필요하다. 기존 설정 디렉터리의 위치를 모르면 `agent-auto-approve find DIR`에 `--codex`, `--claude` 또는 `--agy`를 붙여 탐색한다.
3. 아래 표에서 요청한 등록 범위의 명령을 사용한다. 기본 대상은 Codex다. Claude Code는 `--claude`, Antigravity는 `--agy`로 선택한다. `launch`의 대상은 Codex와 Claude Code다. 작업 범위 안에서만 자동 승인하도록 요청받았다면 등록 명령이나 `launch`에 `--workspace-only`를 추가한다.
4. 등록 후 아래 표대로 `hooks`를 실행해 설정 파일 경로와 승인 모드(`workspace-only` 또는 `all requests`)를 확인한다.

| 요청 범위 | 실행 명령 | 등록 확인 |
| --- | --- | --- |
| 특정 프로젝트 | `agent-auto-approve install DIR` | `agent-auto-approve hooks DIR`에서 대상 설정 파일의 경로 확인 |
| 전역 | `agent-auto-approve install` | `agent-auto-approve hooks`에서 `global` 행 확인 |
| 새 세션 하나 | 대상 디렉터리에서 `agent-auto-approve launch` | 실행된 세션에서 확인 |

전역 등록 경로만 확인하려면 `hooks DIR`에 대상 에이전트의 전역 설정 디렉터리를 전달한다. Codex는 `CODEX_HOME` 또는 기본값 `~/.codex`, Claude Code는 `CLAUDE_CONFIG_DIR` 또는 기본값 `~/.claude`, Antigravity는 `~/.gemini/config`를 사용한다. `launch --workspace-only`의 작업 범위는 실행 디렉터리다.

## 제거

설정을 제거하려면 프로젝트는 `uninstall DIR`, 전역은 `uninstall`을 사용한다. `uninstall --all`은 홈 아래의 등록을 재귀적으로 제거하는 옵션이다. CLI 자체의 제거를 요청했다면 훅 등록을 먼저 제거한 뒤 `uv tool uninstall agent-auto-approve`를 실행한다.

## 소스 변경 검증

CLI 변경은 저장소 루트에서 `python3 codex_approval_hook.py --help` 또는 `python3 codex_approval_hook.py <명령> --help`로 관련 구문을 확인한다. 등록·제거 동작을 변경하면 임시 사용자 홈과 임시 프로젝트에서 해당 흐름을 검증한다. 문서만 수정했다면 명령과 경로를 현재 구현에 대조한다.
