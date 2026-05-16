# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FastAPI backend for unified Korean court auction (대법원 경매) + KAMCO Onbid (캠코 공매) data. Python 3.12, async SQLAlchemy + asyncpg, Supabase PostgreSQL/PostGIS. Deployed on Google Cloud Run, daily ingest driven by Cloud Scheduler.

## Common commands

```powershell
# Local dev (PowerShell)
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py                              # serves on $APP_PORT (default 8000)

# Tests (pytest, uses tests/conftest.py for mock-mode fixtures)
pytest                                       # all
pytest tests/test_normalize.py               # one file
pytest tests/test_normalize.py::test_xyz     # one test
pytest -k "extract_image"                    # by name pattern

# DB migrations (Supabase)
alembic upgrade head
alembic revision --autogenerate -m "..."

# Deploy — CI path (preferred): just push to main; .github/workflows/deploy.yml runs
git push origin main

# Deploy — local path
.\deploy\deploy.ps1                         # build + push image + deploy
.\deploy\setup-scheduler.ps1                # 1회: Cloud Scheduler 등록

# Trigger ingest manually
gcloud scheduler jobs run daily-onbid-ingest --location=asia-northeast3
# or via authenticated admin endpoint (no auth gate currently — local-only)
curl -X POST "$BASE/api/v1/admin/sync/onbid?pages=20&num_of_rows=200"

# Cloud Run logs (prod reads need user authorization in this repo's playbook)
gcloud run services logs read auctionbridge-api --region=asia-northeast3 --limit=200
```

## Architecture (the parts that span files)

### Clean Architecture with `USE_MOCK` toggle
`app/api/deps.py` is the composition root: `get_auction_repository()` returns `MockAuctionRepository` when `USE_MOCK=true`, else `DBAuctionRepository`. Domain (`app/domain/auction/`) defines pure interfaces and Pydantic schemas with **zero external dependencies**; infrastructure (`app/infrastructure/`) holds SQLAlchemy + external API adapters. **When adding endpoints, depend on `AuctionService` / `AuctionRepository`, never on infrastructure types directly** — otherwise the mock path breaks and `USE_MOCK=true` (CI / no-DB dev) stops working.

### Onbid ingest pipeline
`app/services/onbid_ingest_service.py` is the orchestrator. Flow per asset type (realty / movable / vehicle):
1. `OnbidClient` (`app/infrastructure/external/onbid_client.py`) hits data.go.kr B010003 OpenAPI → page of items.
2. Type-specific normalize functions map raw fields (`cltrMngNo`, `pbctCdtnNo`, `apslEvlAmt`, …) into `AuctionUpsertItem`. Status enum derived via `map_status()` from `pbctStatCd`+`pbctStatNm`. Property/vehicle category derived from multi-level Onbid 용도 codes (`usg_lcls/mcls/scls`).
3. `KakaoGeocoder` resolves addresses → `GEOMETRY(Point, 4326)` (concurrency = `GEOCODE_CONCURRENCY`, default 10).
4. `DBAuctionRepository.upsert_many()` writes to `auctions` (parent) + asset-specific child table in one transaction. Uniqueness: `(cltr_mng_no, pbct_cdtn_no)` partial unique index for `source='onbid'`.

The original Onbid API response is preserved in `auctions.raw` JSONB. `source='court'` rows would use `case_number` as the unique key (court crawler is roadmap, not yet wired).

### Cron is **external-only** (no in-process scheduler)
`/api/v1/internal/cron/daily-ingest` is the only entry point for the daily job. It verifies an OIDC ID token (`google.auth.transport.requests`) where:
- `audience` must equal `settings.CRON_AUDIENCE` (= Cloud Run service URL)
- token issuer email must equal `settings.CRON_SERVICE_ACCOUNT_EMAIL` (= `cloud-scheduler-cron@…`) and `email_verified=true`

Both env vars are **auto-injected by the deploy scripts** (`deploy/deploy.ps1` and `.github/workflows/deploy.yml`). **Never put `CRON_SERVICE_ACCOUNT_EMAIL=` or `CRON_AUDIENCE=` (with empty values) in `.env.production`** — that defeats the auto-injection (existence check) and the cron endpoint will return `503 cron auth not configured`.

### Two deploy paths share one image and one service
| | Local (`deploy/deploy.ps1`) | CI (`.github/workflows/deploy.yml`) |
|---|---|---|
| Env source | `.env.production` | `ENV_PRODUCTION` GitHub Secret |
| Auth | gcloud OAuth | Workload Identity Federation (no SA keys) |
| Image tag | timestamp | git SHA[:12] |

Both build via `gcloud builds submit` (regional + user-owned bucket) and deploy `auctionbridge-api` in `asia-northeast3` with runtime SA `cloud-run-runtime@…`. Last deploy wins.

## Critical conventions and gotchas

- **Supabase Transaction Pooler (port 6543) requires `statement_cache_size=0`.** `app/core/database.py` detects pooler hosts via `_is_supabase_pooler()` and disables both prepared-statement caches. Without this, `DuplicatePreparedStatementError` blows up under load.
- **`asyncpg` is pinned to `==0.31.0`** in `requirements.txt`. Older versions have a SCRAM auth quirk against Supabase pooler that surfaces as `InvalidPasswordError: ... user "postgres"` only on Cloud Run (passes locally) — looks like wrong credentials but is a version bug. Don't loosen the pin.
- **`.dockerignore` excludes `.env*`.** Without it, the local `.env` gets baked into the image (Dockerfile uses `COPY . .`). The runtime config priority is env-var > `.env` file, so it doesn't break things, but secrets must not ship in the image.
- **Pydantic-settings reads `.env` only**, not `.env.production`. The `.production` file exists for local deploy + CI secret content; it is never read by the running app — the app only sees env vars set on Cloud Run.
- **Schema lives in `db/schema.sql`** for the initial setup; ongoing changes go through `alembic/versions/`. Baseline migration `0001_baseline_baseline_v2_schema.py` matches `db/schema.sql`. PostGIS, pg_trgm, uuid-ossp are installed in the `extensions` schema (Supabase security guidance).
- **`auctions.location` is `GEOMETRY(Point, 4326)`** with a GiST index. BBox queries use `ST_MakeEnvelope` / `&&`. If you change asset_type filtering, mirror the partial index pattern.
- **CORS**: `CORS_ORIGINS` is a comma-separated list; `CORS_ORIGIN_REGEX` is the optional regex for Vercel-style preview URLs. `allow_credentials=True` is set, so `*` won't work.
- **When deleting test/dummy data**, cascade via `auctions` only — `auction_realty_details` / `auction_vehicle_details` / `auction_movable_details` / `auction_bid_results` / `auction_rights_analysis` all have `ON DELETE CASCADE` against `auctions(id)`.

## Deploy / ops references

`deploy/README.md` and `.github/workflows/README.md` cover deploy specifics. `docs/deployment.md` is the consolidated runbook (GCP inventory, troubleshooting matrix, rotation guidance). Read those before changing anything in `deploy/`, `.github/workflows/`, or `Dockerfile`.

## API references

- **`docs/onbid-api-guide.html`** — 차세대 온비드 OpenAPI(B010003) 19개 가이드를 9개 카테고리(목록·상세·입찰·결과·공고·정부재산·코드/주소·통계·금융위)로 요약한 단일 HTML. 각 API의 요청/응답 파라미터, v2 보정된 Full URL, "현재 코드/스케줄러에서의 사용 현황 매트릭스" 포함. **외부 Onbid API를 새로 호출하거나 응답 필드를 이해해야 할 때 먼저 본다.**
- **`docs/server-api-guide.html`** — 이 서버가 노출하는 12개 endpoint(공개/Admin/Internal) 가이드. `main.app.openapi()` 자동 추출 기반이라 코드 변경 시 빌더 재실행으로 동기화. **프론트엔드 통합이나 endpoint 시그니처를 확인할 때 먼저 본다.**
- **`app/docs/*.docx`** — 위 onbid-api-guide의 원본 docx 19개. 직접 읽기 어려우니(Read 도구 미지원, `python-docx`로만 추출 가능) HTML 가이드를 우선 참조. docx에만 있는 세부(예: 코드표 전문, XML 응답 구조)가 필요할 때만 임시 추출.
