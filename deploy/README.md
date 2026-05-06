# Cloud Run + Cloud Scheduler 배포 가이드

`.env.production` 파일에 모든 환경변수를 모아두고, 배포 시 Cloud Run에 그대로 주입하는 방식.

## 사전 준비 (이미 완료된 항목)
- ✅ gcloud auth login
- ✅ 프로젝트 `auctionbridge-srv` + 결제 계정 연결
- ✅ 필수 API 활성화 (Cloud Run, Cloud Build, Cloud Scheduler, Artifact Registry)
- ✅ Artifact Registry 저장소 `auctionbridge` (asia-northeast3)
- ✅ 서비스 계정 2개:
  - `cloud-run-runtime` — Cloud Run 런타임용
  - `cloud-scheduler-cron` — Cloud Scheduler invoker용

## 배포 순서

### 1️⃣ `.env.production` 작성 (1회)
```powershell
Copy-Item .env.production.example .env.production
```
편집기로 열어서 실제 값 채우기:
- **DATABASE_URL** — Supabase 콘솔 → Project Settings → Database → Connection String → **Pooler** 모드, 형식 `postgresql+asyncpg://postgres.<ref>:<pwd>@aws-0-<region>.pooler.supabase.com:6543/postgres`
- **JWT_SECRET** — 랜덤 문자열. 생성: `[Convert]::ToBase64String((1..32 | %{Get-Random -Min 0 -Max 256}))`
- **KAKAO_REST_API_KEY**, **KAKAO_CLIENT_SECRET** — 카카오 디벨로퍼스
- **ONBID_SERVICE_KEY** — data.go.kr 마이페이지
- **CORS_ORIGINS** — 실제 프론트 도메인 (콤마 구분)

> `.env.production`은 `.gitignore`에 등록되어 커밋되지 않음.

### 2️⃣ Cloud Run 배포 (코드 수정 시마다)
```powershell
.\deploy\deploy.ps1
```
약 5~8분 소요. 마지막에 서비스 URL 출력.

내부적으로:
- `.env.production` → `deploy/env.runtime.yaml` 변환
- Cloud Build로 이미지 빌드/push
- `gcloud run deploy --env-vars-file env.runtime.yaml` 로 배포
- 첫 배포 후 `CRON_AUDIENCE`를 서비스 URL로 자동 갱신

### 3️⃣ Cloud Scheduler 등록 (1회)
```powershell
.\deploy\setup-scheduler.ps1
```
매일 KST 04:00에 `/api/v1/internal/cron/daily-ingest` 호출.

## 운영

### 수동 cron 실행 (테스트)
```powershell
gcloud scheduler jobs run daily-onbid-ingest --location=asia-northeast3
```

### 로그 확인
```powershell
gcloud run services logs read auctionbridge-api --region=asia-northeast3 --limit=100
```

### 환경변수 갱신 후 재배포
`.env.production` 수정 → `.\deploy\deploy.ps1` 다시 실행

### 환경변수 한 개만 빠르게 변경
```powershell
gcloud run services update auctionbridge-api `
    --region=asia-northeast3 `
    --update-env-vars="KEY=value"
```

## 보안 메모
- `.env.production` 절대 커밋 금지 (`.gitignore` 등록되어 있음)
- 배포된 환경변수는 Cloud Run 콘솔에서 프로젝트 Editor/Viewer 권한자에게 보임
- 더 강한 격리가 필요해지면 Secret Manager로 마이그레이션 가능 (스크립트 별도 작성)

## 무료 한도 (참고)
- Cloud Run: 월 2M req / 360K vCPU-초 / 180K GiB-초 (계정당)
- Cloud Scheduler: 월 3 jobs 무료 (이 프로젝트 1개 사용)
- Artifact Registry: 0.5GB 무료
- Cloud Build: 일 120 빌드분 무료
