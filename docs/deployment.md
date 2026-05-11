# 배포 인프라 — 통합 문서

AuctionBridge-Server의 GCP 운영 환경(Cloud Run + Cloud Scheduler) 및
GitHub Actions 자동 배포 파이프라인 전체 구성도와 운영 가이드.

세부 절차는 각 영역별 README와 함께 보세요:
- 로컬 배포: [`deploy/README.md`](../deploy/README.md)
- GitHub Actions(CI 배포): [`.github/workflows/README.md`](../.github/workflows/README.md)

---

## 1. 최종 완성 상태

| 영역 | 상태 |
|---|---|
| Cloud Run 배포 | ✅ `https://auctionbridge-api-ak2wcqba2q-du.a.run.app` |
| Cloud Scheduler cron | ✅ 매일 KST 04:00 자동 실행 |
| 코드 리팩터링 (APScheduler → OIDC cron) | ✅ in-process 스케줄러 제거, 외부 cron 트리거 방식으로 전환 |
| 로컬 배포 스크립트 (`deploy/deploy.ps1`) | ✅ |
| GitHub Actions 자동 배포 (WIF) | ✅ SA 키 없이 OIDC 인증 |
| Git push → 빌드/배포/헬스체크 자동화 | ✅ |

---

## 2. 운영 흐름 (End-to-End)

```
로컬에서 코드 수정
      ↓
git commit + push origin main
      ↓
GitHub Actions가 자동으로:
  1. WIF 인증 (서비스 계정 JSON 키 없음)
  2. Cloud Build 이미지 빌드 / push
  3. Cloud Run 배포
  4. /health 스모크 테스트 (5회 재시도)
      ↓
Cloud Scheduler가 매일 04:00 KST에:
  POST {SERVICE_URL}/api/v1/internal/cron/daily-ingest
  (OIDC ID 토큰을 Bearer 헤더로 첨부)
      ↓
Cron 엔드포인트가 OIDC 토큰을 검증하고
  → run_daily_onbid_ingest() 실행
  → Onbid 데이터 ingest + bid-result/이미지 enrich
```

---

## 3. GCP 리소스 인벤토리

| 리소스 종류 | 이름 | 비고 |
|---|---|---|
| Project | `auctionbridge-srv` | 결제 계정 연결 완료 |
| Region | `asia-northeast3` (Seoul) | |
| Artifact Registry | `auctionbridge` | Docker 이미지 저장소 |
| Cloud Run service | `auctionbridge-api` | 공개(`--allow-unauthenticated`), `512Mi/1CPU`, `min=0/max=3`, `timeout=540s` |
| Cloud Scheduler job | `daily-onbid-ingest` | `0 4 * * *` (Asia/Seoul), OIDC 인증 |
| Cloud Run runtime SA | `cloud-run-runtime@…` | 컨테이너 런타임용 |
| Cloud Scheduler SA | `cloud-scheduler-cron@…` | OIDC 토큰 발급 → cron invoker |
| GitHub Deployer SA | `github-deployer@…` | WIF로 임퍼소네이션 (SA 키 발급 X) |
| Workload Identity Pool | `github-pool` | issuer = `token.actions.githubusercontent.com` |
| WIF Provider | `github-provider` | attribute condition: `repository_owner == 'dennis-seo'` |
| WIF principalSet | `dennis-seo/auction_bridge_server` | 이 repo만 SA 임퍼소네이션 가능 |

### 필수 API
Cloud Run, Cloud Build, Cloud Scheduler, Artifact Registry, IAM Credentials, IAM Service Account.

---

## 4. 코드 리팩터링 — APScheduler → OIDC cron

### 변경 의도
컨테이너가 항상 떠 있는 환경(`min-instances ≥ 1`)이 아니면 in-process 스케줄러는
재시작·콜드스타트 사이에 작업이 누락될 수 있음. Cloud Run + Cloud Scheduler 조합에서는
**외부 cron이 HTTP로 트리거**하는 것이 표준이라 이 형태로 옮겼습니다.

### 변경 파일
- `app/services/scheduler.py` — APScheduler 제거, `run_daily_onbid_ingest()` 작업 함수만 export
- `app/api/v1/endpoints/cron.py` — 신규. OIDC ID 토큰 검증 → 작업 실행
- `app/api/v1/router.py` — `/internal/cron/*` 라우터 등록
- `main.py` — 앱 시작 시점의 스케줄러 부팅 로직 제거

### 인증 모델
`/api/v1/internal/cron/daily-ingest` (POST)는 다음 둘이 모두 일치할 때만 실행:
1. `audience` == `CRON_AUDIENCE` (Cloud Run 서비스 URL)
2. 토큰 발급 SA email == `CRON_SERVICE_ACCOUNT_EMAIL` (=`cloud-scheduler-cron@…`)
   + `email_verified` 가 true

검증 실패 시 401/403. `include_in_schema=False` 로 `/docs` 에는 노출되지 않음.

---

## 5. 배포 — 두 가지 경로

같은 Cloud Run 서비스(`auctionbridge-api`)에 배포되며, **마지막 배포가 활성**입니다.

| 항목 | 로컬 (`deploy/deploy.ps1`) | CI (GitHub Actions) |
|---|---|---|
| 환경변수 소스 | `.env.production` 파일 | `ENV_PRODUCTION` GitHub Secret |
| 인증 | `gcloud auth login` (OAuth) | Workload Identity Federation (OIDC) |
| 트리거 | 수동 실행 | `main` 브랜치 push 자동 (+ `workflow_dispatch`) |
| 이미지 태그 | `yyyyMMddHHmm` | `${GITHUB_SHA::12}` |
| 결과 확인 | 로컬 콘솔 출력 | Actions 탭 로그 |

### 공통 배포 단계
1. `.env.production` → `deploy/env.runtime.yaml` 변환 (값 따옴표·escape 처리)
2. `CRON_SERVICE_ACCOUNT_EMAIL` / `CRON_AUDIENCE` 자동 주입 (없을 때만)
3. Cloud Build로 이미지 빌드 + push
4. `gcloud run deploy --env-vars-file env.runtime.yaml` 로 배포
5. 배포 직후 서비스 URL을 다시 환경변수 `CRON_AUDIENCE`로 갱신
6. (CI 한정) `/health` 스모크 테스트 5회 재시도

### Cloud Scheduler 등록 (1회)
```powershell
.\deploy\setup-scheduler.ps1
```
이미 등록된 job이 있으면 멱등하게 삭제 후 재생성합니다.

---

## 6. 자주 쓰는 명령어

### 수동 cron 실행 (테스트)
```powershell
gcloud scheduler jobs run daily-onbid-ingest --location=asia-northeast3
```

### Cloud Run 로그 확인
```powershell
gcloud run services logs read auctionbridge-api --region=asia-northeast3 --limit=100
```

### 환경변수 한 개만 빠르게 갱신
```powershell
gcloud run services update auctionbridge-api `
    --region=asia-northeast3 `
    --update-env-vars="KEY=value"
```

### 서비스 URL 확인
```powershell
gcloud run services describe auctionbridge-api `
    --region=asia-northeast3 --format="value(status.url)"
```

### WIF 바인딩 검증
```powershell
gcloud iam service-accounts get-iam-policy github-deployer@auctionbridge-srv.iam.gserviceaccount.com
```

---

## 7. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| GitHub Actions: `Permission denied` / `iam.workloadIdentityUser required` | WIF principalSet 바인딩이 다른 repo를 가리킴. `get-iam-policy` 로 확인 후 재바인딩. |
| GitHub Actions: `ENV_PRODUCTION secret is empty` | Secret 이름 오타 또는 미등록. 정확히 `ENV_PRODUCTION` 으로. |
| 빌드는 되는데 배포가 실패 | 환경변수 부족. Actions 로그의 "Generated keys" 출력 확인. |
| `/health` 스모크 실패 | 컨테이너 시작 에러. `gcloud run services logs read` 로 스택트레이스 확인. |
| cron 호출이 401/403 | `CRON_AUDIENCE` 가 서비스 URL과 다르거나 `CRON_SERVICE_ACCOUNT_EMAIL` 불일치. 배포 마지막 단계가 audience를 갱신했는지 확인. |
| cron 호출이 503 `cron auth not configured` | `CRON_AUDIENCE` 또는 `CRON_SERVICE_ACCOUNT_EMAIL` 환경변수가 비어 있음. |

---

## 8. 보안 메모

- `.env.production` 은 `.gitignore` 에 등록되어 커밋되지 않음.
- GitHub Actions에는 SA JSON 키 대신 **WIF**로만 인증 → 키 유출 위험 제거.
- 배포된 환경변수는 Cloud Run 콘솔에서 프로젝트 Editor/Viewer 권한자에게 노출됨.
  더 강한 격리가 필요해지면 Secret Manager로 마이그레이션 가능.
- cron 엔드포인트는 OIDC audience + email 이중 검증 → 외부에서 임의 호출 불가.

---

## 9. 무료 한도 (참고)

| 서비스 | 무료 한도 |
|---|---|
| Cloud Run | 월 2M req / 360K vCPU-초 / 180K GiB-초 (계정당) |
| Cloud Scheduler | 월 3 jobs 무료 (이 프로젝트 1개 사용) |
| Artifact Registry | 0.5GB |
| Cloud Build | 일 120 빌드분 |
