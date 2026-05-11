# tools/

`docs/` 안의 HTML 가이드를 자동 빌드하는 스크립트와 git pre-commit hook이 들어있다.

## 빌더 스크립트

| 스크립트 | 출력 | 입력 |
|---|---|---|
| `build_onbid_guide.py` | `docs/onbid-api-guide.html` | `app/docs/*.docx` (python-docx로 추출) |
| `build_server_guide.py` | `docs/server-api-guide.html` | `main.app.openapi()` (FastAPI 자동 스펙) |

수동 실행:
```powershell
.\.venv\Scripts\python.exe tools\build_onbid_guide.py
.\.venv\Scripts\python.exe tools\build_server_guide.py
```

## Pre-commit hook

`tools/git-hooks/pre-commit`이 staged 파일을 검사해 필요한 빌더만 자동 실행하고 결과 HTML을 stage에 추가한다.

트리거 매핑:
- **onbid 가이드 재빌드** — `app/docs/*.docx` 또는 `tools/build_onbid_guide.py` 변경 시
- **server 가이드 재빌드** — `app/api/**/*.py`, `app/domain/**/*.py`, `main.py`, 또는 `tools/build_server_guide.py` 변경 시

### 1회 활성화

repo clone 후 한 번만:
```powershell
git config core.hooksPath tools/git-hooks
```

(Windows에서는 git for windows가 sh 스크립트를 자체 bash에서 실행하므로 추가 설정 없이 동작한다. POSIX 환경에서는 hook 파일에 실행 비트가 필요하면 `chmod +x tools/git-hooks/pre-commit`.)

### 임시 우회

WIP 커밋 등 빌드를 돌리고 싶지 않을 때:
```bash
git commit --no-verify
```

### 의존성

빌더는 프로젝트 `.venv`의 python을 사용한다 (`requirements.txt`에 이미 `python-docx`, `fastapi` 포함). hook은 `.venv/Scripts/python.exe`(Windows) → `.venv/bin/python`(POSIX) → 시스템 `python` 순으로 찾는다.

빌더가 실패하면 hook도 실패해 commit이 차단된다 (정상). 실패 원인을 고친 뒤 다시 commit하면 된다.
