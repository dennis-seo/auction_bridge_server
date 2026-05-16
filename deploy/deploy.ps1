# AuctionBridge Cloud Run 배포 스크립트 (.env.production 방식)
# 사용:  .\deploy\deploy.ps1
# 사전조건:
#   - gcloud login + 활성 프로젝트 설정
#   - .env.production 파일에 실제 값 채워둠

$ErrorActionPreference = "Stop"

# === 변수 ===
$PROJECT_ID = "auctionbridge-srv"
$REGION     = "asia-northeast3"           # Seoul
$REPO       = "auctionbridge"
$SERVICE    = "auctionbridge-api"
$IMAGE      = "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$SERVICE"
$TAG        = (Get-Date -Format "yyyyMMddHHmm")

$RUNTIME_SA = "cloud-run-runtime@$PROJECT_ID.iam.gserviceaccount.com"
$CRON_SA    = "cloud-scheduler-cron@$PROJECT_ID.iam.gserviceaccount.com"

$ENV_FILE   = ".env.production"
$YAML_FILE  = "deploy\env.runtime.yaml"

# === [0/4] .env.production → YAML 변환 ===
if (-not (Test-Path $ENV_FILE)) {
    throw "$ENV_FILE 가 없습니다. .env.production.example 복사 후 채우세요."
}

Write-Host "===> [0/4] $ENV_FILE → $YAML_FILE 변환" -ForegroundColor Cyan
$lines = @()
Get-Content $ENV_FILE | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    if ($line -match "^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$") {
        $key = $Matches[1]
        $val = $Matches[2]
        # 양끝 따옴표 제거
        if ($val -match '^"(.*)"$' -or $val -match "^'(.*)'$") {
            $val = $Matches[1]
        }
        # YAML escape: 백슬래시·쌍따옴표 escape
        $val = $val.Replace('\', '\\').Replace('"', '\"')
        $lines += "${key}: `"${val}`""
    }
}

# CRON_AUDIENCE는 첫 배포 후에야 알 수 있으니, 1차 배포 시 placeholder
$hasAudience = $lines | Where-Object { $_ -like "CRON_AUDIENCE:*" }
if (-not $hasAudience) {
    $lines += 'CRON_AUDIENCE: ""'
}
$hasCronEmail = $lines | Where-Object { $_ -like "CRON_SERVICE_ACCOUNT_EMAIL:*" }
if (-not $hasCronEmail) {
    $lines += "CRON_SERVICE_ACCOUNT_EMAIL: `"$CRON_SA`""
}

Set-Content -Path $YAML_FILE -Value $lines -Encoding utf8
Write-Host "  ✅ $YAML_FILE 생성 ($(($lines).Count) 항목)"

# === [1/4] Cloud Build로 이미지 빌드 + push ===
Write-Host "===> [1/4] Cloud Build (이미지 빌드 + push)" -ForegroundColor Cyan
gcloud builds submit `
    --tag "${IMAGE}:${TAG}" `
    --project $PROJECT_ID `
    .
if ($LASTEXITCODE -ne 0) { throw "Cloud Build 실패" }

# === [2/4] Cloud Run 배포 ===
Write-Host "===> [2/4] Cloud Run 배포" -ForegroundColor Cyan
gcloud run deploy $SERVICE `
    --image "${IMAGE}:${TAG}" `
    --region $REGION `
    --project $PROJECT_ID `
    --service-account $RUNTIME_SA `
    --allow-unauthenticated `
    --port 8080 `
    --memory 512Mi `
    --cpu 1 `
    --min-instances 0 `
    --max-instances 3 `
    --timeout 540 `
    --concurrency 80 `
    --env-vars-file $YAML_FILE
if ($LASTEXITCODE -ne 0) { throw "Cloud Run 배포 실패" }

# === [3/4] 서비스 URL 확보 ===
Write-Host "===> [3/4] 서비스 URL 확인" -ForegroundColor Cyan
$SERVICE_URL = gcloud run services describe $SERVICE `
    --region $REGION `
    --project $PROJECT_ID `
    --format="value(status.url)"
Write-Host "  Service URL: $SERVICE_URL" -ForegroundColor Green

# === [4/4] CRON_AUDIENCE 업데이트 (서비스 URL을 audience로) ===
Write-Host "===> [4/4] CRON_AUDIENCE 업데이트" -ForegroundColor Cyan
gcloud run services update $SERVICE `
    --region $REGION `
    --project $PROJECT_ID `
    --update-env-vars="CRON_AUDIENCE=$SERVICE_URL" | Out-Null

Write-Host ""
Write-Host "✅ 배포 완료!" -ForegroundColor Green
Write-Host "   - URL:    $SERVICE_URL"
Write-Host "   - Health: $SERVICE_URL/health"
Write-Host "   - Docs:   $SERVICE_URL/docs"
Write-Host ""
Write-Host "다음: .\deploy\setup-scheduler.ps1"
