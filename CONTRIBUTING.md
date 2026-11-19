# 기여하기

자동 승인 범위나 권한 처리에 관한 보안 문제는 [보안 제보 안내](SECURITY.md)를 따릅니다.

버그를 보고할 때는 운영체제와 Python 버전, 사용 중인 에이전트와 그 버전, 실행한 명령, 예상한 결과와 실제 결과를 적어 주세요. 로그를 공유하기 전에 토큰, 개인 경로, 비공개 프로젝트 정보를 지워 주세요.

코드를 변경한 뒤 저장소 루트에서 패키지를 설치하고 CLI를 확인합니다.

```sh
uv tool install .
agent-auto-approve --help
```

`install`이나 `uninstall` 동작을 확인할 때는 임시 사용자 홈과 임시 프로젝트를 사용합니다. PR에는 변경 이유와 검증 방법을 적어 주세요.

## 릴리즈

`setup.cfg`의 `version`을 업데이트하고 변경사항을 `main`에 반영한 뒤, 같은 버전의 `vMAJOR.MINOR.PATCH` 태그를 달아 푸시합니다. 예를 들어 패키지 버전이 `0.1.0`이면 다음 태그를 사용합니다.

```sh
git tag -a v0.1.0 -m 'Release v0.1.0'
git push origin v0.1.0
```

태그가 가리키는 커밋의 CI가 통과하면 GitHub Release에 wheel(`.whl`)과 소스 배포본(`.tar.gz`)이 첨부됩니다.

PyPI 자동 게시를 사용하려면 PyPI에 [Trusted Publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)를 등록합니다. 프로젝트 이름은 `agent-auto-approve`, GitHub 소유자는 `jiind`, 저장소는 `agent-auto-approve`, 워크플로는 `release.yml`, 환경은 `pypi`입니다. 첫 태그를 푸시하기 전에 GitHub 저장소에 `pypi` 환경을 만들고 Actions 변수 `PUBLISH_TO_PYPI`를 `true`로 설정합니다.
