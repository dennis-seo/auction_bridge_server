# AuctionBridge-Server

대한민국 법원 경매 + 캠코 온비드(공매) 통합 백엔드 API.

- **Stack**: FastAPI · Python 3.11+ · PostgreSQL/PostGIS (Supabase) · SQLAlchemy(async) · Playwright
- **Auth**: 카카오 OAuth 2.0 → 자체 JWT 세션
- **Architecture**: Clean Architecture (api ↔ domain ↔ infrastructure)

---

## Quick Start

```powershell
# 1. 가상환경
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. 의존성
pip install -r requirements.txt

# 3. (선택) 크롤러 사용 시
playwright install chromium

# 4. 환경변수
Copy-Item .env.example .env
# .env 편집 — 최소 USE_MOCK=true 로 두면 DB 없이도 동작합니다.

# 5. 실행
python main.py
# 또는
uvicorn main:app --reload
```

- API 문서: http://localhost:8000/docs
- 헬스체크: http://localhost:8000/health
- Stats API (Mock): http://localhost:8000/api/v1/auctions/stats

---

## Project Structure

```
AuctionBridge-Server/
├── main.py                       # FastAPI 앱 진입점
├── requirements.txt
├── .env.example
├── db/
│   └── schema.sql                # PostgreSQL + PostGIS DDL
└── app/
    ├── core/                     # 설정, DB, 보안 (JWT)
    │   ├── config.py
    │   ├── database.py
    │   └── security.py
    ├── api/
    │   ├── deps.py               # 의존성 주입 (DI)
    │   └── v1/
    │       ├── router.py
    │       └── endpoints/
    │           └── auctions.py   # /api/v1/auctions/*
    ├── domain/                   # 비즈니스 규칙 (외부 의존성 없음)
    │   └── auction/
    │       ├── schemas.py        # Pydantic 모델
    │       ├── repository.py     # 추상 인터페이스
    │       └── service.py        # 도메인 서비스
    ├── infrastructure/           # 외부 시스템 어댑터
    │   ├── db/                   # SQLAlchemy 구현체
    │   ├── external/             # 카카오 OAuth/Local, 온비드 API
    │   └── scrapers/             # Playwright 기반 대법원 크롤러
    └── mock/                     # 클라이언트 개발용 Mock 응답
        └── auction_mock.py
```

### Layer 책임

| Layer | 책임 | 의존 가능 |
|---|---|---|
| `api` | HTTP 라우팅·요청/응답 변환 | `domain`, `core` |
| `domain` | 도메인 규칙·인터페이스 | (없음) |
| `infrastructure` | DB·외부 API·스크레이퍼 구현 | `domain`, `core` |
| `mock` | 인터페이스 Mock 구현 | `domain` |

`USE_MOCK=true` 면 `api/deps.py` 가 `mock` 구현체를, `false` 면 `infrastructure` 구현체를 주입합니다.

---

## Database (Supabase)

1. Supabase 프로젝트 생성 → Database → Extensions에서 **postgis** 활성화
2. SQL Editor에 `db/schema.sql` 내용 실행
3. Connection String을 `.env` 의 `DATABASE_URL` 에 입력
   - 형식: `postgresql+asyncpg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres`

---

## Roadmap

- [x] 프로젝트 스켈레톤 + Mock 기반 `/api/v1/auctions/stats`
- [ ] DB 연동 (SQLAlchemy + GeoAlchemy2)
- [ ] `/api/v1/auctions` 지도 BBox 조회 (PostGIS `&&`, `ST_MakeEnvelope`)
- [ ] `/api/v1/auctions/{id}` 상세 + 권리분석
- [ ] 카카오 OAuth + JWT 발급
- [ ] 즐겨찾기 / 댓글
- [ ] 온비드 공공데이터 API 수집기
- [ ] 대법원 Playwright 크롤러
- [ ] 카카오 Local API 지오코딩 파이프라인
