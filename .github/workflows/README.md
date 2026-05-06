# GitHub Actions — Cloud Run 자동 배포

`main` 브랜치 push마다 Cloud Build로 이미지 빌드 + Cloud Run 배포 + 헬스체크까지 자동 실행.

## 인증 방식 — Workload Identity Federation (WIF)

SA JSON 키를 GitHub Secrets에 두지 않습니다. 대신 GitHub OIDC 토큰을 GCP가 직접 검증.

### GCP 측 셋업 (이미 완료됨)
- Workload Identity Pool: `github-pool`
- OIDC Provider: `github-provider` (issuer = token.actions.githubusercontent.com)
- Attribute condition: `repository_owner == 'dennis-seo'` (다른 owner의 repo로부터의 인증 차단)
- Deployer SA: `github-deployer@auctionbridge-srv.iam.gserviceaccount.com`
- Roles: `run.admin`, `iam.serviceAccountUser`, `cloudbuild.builds.editor`,
  `artifactregistry.writer`, `storage.admin`, `logging.logWriter`
- WIF principalSet 바인딩: `dennis-seo/auction_bridge_server` 만 SA 임퍼소네이션 허용

## 필수 GitHub Secret

워크플로우가 동작하려면 **단 하나의 secret**만 등록하면 됩니다.

### `ENV_PRODUCTION`
로컬 `.env.production` 파일 **전체 내용**을 복사해서 GitHub Secret에 붙여넣기.

설정 경로: GitHub repo → Settings → Secrets and variables → Actions → New repository secret
- Name: `ENV_PRODUCTION`
- Value: `.env.production` 파일 내용 그대로

> 워크플로우가 secret을 받아 `.env.production` 파일을 임시 생성한 뒤,
> deploy.ps1과 동일한 로직으로 `deploy/env.runtime.yaml` 변환 → Cloud Run에 주입.

## 트리거

- **자동**: `main` 브랜치에 push
- **수동**: Actions 탭 → "Deploy to Cloud Run" → Run workflow

## 배포 단계 (워크플로우 내)

1. Checkout
2. WIF로 GCP 인증 (서비스 계정 JSON 키 없이)
3. gcloud setup
4. `ENV_PRODUCTION` secret → `deploy/env.runtime.yaml` 변환
5. Cloud Build로 이미지 빌드/push (태그 = git SHA 앞 12자)
6. Cloud Run 배포
7. CRON_AUDIENCE를 서비스 URL로 갱신
8. `/health` 스모크 테스트 (5회 재시도)

## 로컬 vs CI 비교

| | 로컬 (`deploy.ps1`) | CI (GitHub Actions) |
|---|---|---|
| 환경변수 소스 | `.env.production` 파일 | `ENV_PRODUCTION` secret |
| 인증 | `gcloud auth login` (OAuth) | WIF OIDC |
| 트리거 | 수동 실행 | git push 자동 |
| 결과 | 로컬 콘솔 출력 | Actions 탭 + 슬랙(미설정) |

둘 다 같은 Cloud Run 서비스(`auctionbridge-api`)에 배포 — 마지막 배포가 활성.

## 트러블슈팅

### "Permission denied" / "iam.workloadIdentityUser required"
WIF principalSet 바인딩이 잘못된 repo를 가리키는지 확인:
```powershell
gcloud iam service-accounts get-iam-policy github-deployer@auctionbridge-srv.iam.gserviceaccount.com
```

### "ENV_PRODUCTION secret is empty"
GitHub Secret이 등록되지 않았거나 이름 오타. 정확히 `ENV_PRODUCTION` 으로.

### 빌드는 되는데 배포가 실패
대부분 환경변수 부족. Actions 로그의 "Generated keys" 출력을 확인.

### 헬스체크 실패
컨테이너 시작 에러. `gcloud run services logs read auctionbridge-api --region=asia-northeast3 --limit=100` 으로 로그 확인.
