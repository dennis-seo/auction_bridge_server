-- =====================================================================
-- AuctionBridge - PostgreSQL / PostGIS DDL
-- Target: Supabase (PostgreSQL 15+) with PostGIS extension
-- Coordinate System: EPSG:4326 (WGS84, lon/lat)
-- =====================================================================

-- Supabase에서는 PostGIS가 기본 활성화되지 않을 수 있어 명시적으로 활성화.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- 주소 부분 검색용
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- 필요 시 UUID 사용


-- ---------------------------------------------------------------------
-- ENUMs
-- ---------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE auction_source AS ENUM ('court', 'onbid');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE auction_status AS ENUM (
        'scheduled',   -- 신건/예정
        'ongoing',     -- 진행중
        'sold',        -- 매각/낙찰
        'failed',      -- 유찰
        'cancelled'    -- 취하/변경
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE property_category AS ENUM (
        'apartment',
        'villa',
        'house',
        'officetel',
        'commercial',
        'land',
        'etc'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- ---------------------------------------------------------------------
-- updated_at 자동 갱신 트리거 함수
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ---------------------------------------------------------------------
-- USERS  (카카오 OAuth 기반)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                  BIGSERIAL PRIMARY KEY,
    kakao_id            BIGINT      NOT NULL UNIQUE,
    nickname            VARCHAR(100),
    profile_image_url   TEXT,
    email               VARCHAR(255),
    last_login_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ---------------------------------------------------------------------
-- AUCTIONS  (법원 경매 + 온비드 공매 통합 테이블)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auctions (
    id                  BIGSERIAL PRIMARY KEY,
    source              auction_source     NOT NULL,
    external_id         VARCHAR(100)       NOT NULL,         -- 사건번호(법원) 또는 물건관리번호(온비드)
    case_number         VARCHAR(100),                        -- 사용자 표시용 사건번호
    category            property_category  NOT NULL,
    status              auction_status     NOT NULL DEFAULT 'scheduled',

    title               VARCHAR(500),
    address             TEXT               NOT NULL,         -- 도로명 주소 우선
    address_detail      TEXT,                                -- 동/호수 등
    region_sido         VARCHAR(40),                         -- 검색·필터용 정규화 컬럼
    region_sigungu      VARCHAR(80),

    -- PostGIS Point (lon, lat) - WGS84
    location            GEOMETRY(Point, 4326),

    appraisal_price     BIGINT,                              -- 감정가 (원)
    minimum_bid_price   BIGINT,                              -- 최저입찰가 (원)
    bid_deposit         BIGINT,                              -- 입찰보증금
    auction_date        TIMESTAMPTZ,                         -- 입찰/매각기일
    failed_count        INTEGER            NOT NULL DEFAULT 0,
    court_name          VARCHAR(100),                        -- 관할 법원 (법원 경매)
    agency_name         VARCHAR(100),                        -- 처분기관 (온비드)

    description         TEXT,
    metadata            JSONB              NOT NULL DEFAULT '{}'::JSONB,

    crawled_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ        NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_auctions_source_external UNIQUE (source, external_id)
);

DROP TRIGGER IF EXISTS trg_auctions_updated_at ON auctions;
CREATE TRIGGER trg_auctions_updated_at
    BEFORE UPDATE ON auctions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 공간 인덱스 (지도 Bounding Box 쿼리용)
CREATE INDEX IF NOT EXISTS idx_auctions_location_gist
    ON auctions USING GIST (location);

-- 자주 쓰는 필터 조합
CREATE INDEX IF NOT EXISTS idx_auctions_status_category
    ON auctions (status, category);

CREATE INDEX IF NOT EXISTS idx_auctions_auction_date
    ON auctions (auction_date);

CREATE INDEX IF NOT EXISTS idx_auctions_region
    ON auctions (region_sido, region_sigungu);

-- 주소 부분 검색 (LIKE '%xxx%')용 trigram 인덱스
CREATE INDEX IF NOT EXISTS idx_auctions_address_trgm
    ON auctions USING GIN (address gin_trgm_ops);


-- ---------------------------------------------------------------------
-- AUCTION_RIGHTS_ANALYSIS  (권리분석 요약 - 1:1)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auction_rights_analysis (
    id            BIGSERIAL PRIMARY KEY,
    auction_id    BIGINT      NOT NULL UNIQUE
                  REFERENCES auctions(id) ON DELETE CASCADE,
    summary       TEXT,
    risk_level    SMALLINT,                       -- 1: low, 2: medium, 3: high
    rights_data   JSONB       NOT NULL DEFAULT '{}'::JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (risk_level IS NULL OR risk_level BETWEEN 1 AND 3)
);

DROP TRIGGER IF EXISTS trg_rights_updated_at ON auction_rights_analysis;
CREATE TRIGGER trg_rights_updated_at
    BEFORE UPDATE ON auction_rights_analysis
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ---------------------------------------------------------------------
-- FAVORITES  (즐겨찾기)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS favorites (
    user_id     BIGINT      NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    auction_id  BIGINT      NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, auction_id)
);

CREATE INDEX IF NOT EXISTS idx_favorites_auction_id
    ON favorites (auction_id);


-- ---------------------------------------------------------------------
-- COMMENTS  (물건별 댓글 - 1단계 대댓글 허용)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comments (
    id           BIGSERIAL PRIMARY KEY,
    auction_id   BIGINT      NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
    user_id      BIGINT      NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    parent_id    BIGINT               REFERENCES comments(id) ON DELETE CASCADE,
    content      TEXT        NOT NULL CHECK (length(trim(content)) > 0),
    is_deleted   BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_comments_updated_at ON comments;
CREATE TRIGGER trg_comments_updated_at
    BEFORE UPDATE ON comments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_comments_auction_id_created
    ON comments (auction_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_comments_user_id
    ON comments (user_id);


-- =====================================================================
-- 참고 쿼리 예시
-- =====================================================================
--
-- 1) 지도 Bounding Box 안의 진행중 매물 조회
--    ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
--
-- SELECT id, category, status, address,
--        ST_X(location) AS lon, ST_Y(location) AS lat
-- FROM   auctions
-- WHERE  status IN ('scheduled', 'ongoing')
--   AND  location && ST_MakeEnvelope(126.95, 37.50, 127.10, 37.60, 4326)
-- LIMIT  500;
--
-- 2) 특정 좌표 기준 반경 N km 내 매물
--
-- SELECT id, address,
--        ST_DistanceSphere(location, ST_MakePoint(127.0, 37.55)) AS dist_m
-- FROM   auctions
-- WHERE  ST_DWithin(location::geography,
--                   ST_MakePoint(127.0, 37.55)::geography,
--                   3000)
-- ORDER  BY dist_m;
--
-- 3) 카테고리별 진행 건수 (stats API용)
--
-- SELECT category, COUNT(*) AS cnt
-- FROM   auctions
-- WHERE  status IN ('scheduled', 'ongoing')
-- GROUP  BY category;
