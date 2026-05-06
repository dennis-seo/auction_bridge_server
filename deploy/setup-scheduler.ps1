# Cloud Scheduler에서 매일 KST 04:00에 /api/v1/internal/cron/daily-ingest 호출
# 사용: .\deploy\setup-scheduler.ps1
# 사전조건: deploy.ps1로 Cloud Run 배포가 끝난 상태

$ErrorActionPreference = "Stop"

$PROJECT_ID = "auctionbridge-srv"
$REGION     = "asia-northeast3"
$SERVICE    = "auctionbridge-api"
$JOB_NAME   = "daily-onbid-ingest"
$CRON_SA    = "cloud-scheduler-cron@$PROJECT_ID.iam.gserviceaccount.com"

# 1) 서비스 URL 조회
$SERVICE_URL = gcloud run services describe $SERVICE `
    --region $REGION `
    --project $PROJECT_ID `
    --format="value(status.url)"

if (-not $SERVICE_URL) { throw "Cloud Run 서비스를 찾을 수 없음 — 먼저 deploy.ps1 실행" }

$TARGET_URL = "$SERVICE_URL/api/v1/internal/cron/daily-ingest"
Write-Host "Target URL: $TARGET_URL" -ForegroundColor Cyan

# 2) 기존 job 있으면 삭제 후 재생성 (멱등). gcloud는 stderr를 일반 진단 채널로 쓰므로
#    ErrorActionPreference=Stop 영향을 받지 않도록 명시적으로 native command 분기.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& gcloud scheduler jobs describe $JOB_NAME --location=$REGION --project=$PROJECT_ID 2>$null | Out-Null
$existsCode = $LASTEXITCODE
$ErrorActionPreference = $prevEAP

if ($existsCode -eq 0) {
    Write-Host "기존 job 삭제..." -ForegroundColor Yellow
    & gcloud scheduler jobs delete $JOB_NAME --location=$REGION --project=$PROJECT_ID --quiet | Out-Null
}

# 3) 새 job 생성 — 매일 04:00 KST, OIDC 인증 (audience = 서비스 URL)
gcloud scheduler jobs create http $JOB_NAME `
    --location=$REGION `
    --project=$PROJECT_ID `
    --schedule="0 4 * * *" `
    --time-zone="Asia/Seoul" `
    --uri="$TARGET_URL" `
    --http-method=POST `
    --oidc-service-account-email=$CRON_SA `
    --oidc-token-audience="$SERVICE_URL" `
    --attempt-deadline=540s `
    --max-retry-attempts=3 `
    --description="Daily Onbid ingest at KST 04:00"

Write-Host ""
Write-Host "✅ Cloud Scheduler 등록 완료" -ForegroundColor Green
Write-Host "   매일 KST 04:00 실행"
Write-Host ""
Write-Host "수동 트리거 (테스트):"
Write-Host "  gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$PROJECT_ID"
