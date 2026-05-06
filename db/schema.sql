-- =====================================================================
-- AuctionBridge - PostgreSQL / PostGIS DDL  (차세대 온비드 v2 기준)
-- Target: Supabase (PostgreSQL 15+) with PostGIS extension
-- Coordinate System: EPSG:4326 (WGS84, lon/lat)
--
-- 구조:  auctions (parent, 공통 메타)
--          ├─ auction_realty_details   1:1
--          ├─ auction_vehicle_details  1:1
--          └─ auction_movable_details  1:1
--        users / favorites / comments / auction_rights_analysis
--
-- 식별자: source='onbid' → (cltr_mng_no, pbct_cdtn_no) UNIQUE
--         source='court' → (case_number) UNIQUE
-- =====================================================================

-- 익스텐션은 별도 schema(`extensions`)에 설치 (security 권고).
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS postgis      WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm      WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"  WITH SCHEMA extensions;

-- ---------------------------------------------------------------------
-- 기존 테이블 정리 (rows=0이라 안전).
-- 운영 시작 후엔 alembic migration으로 전환.
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS comments               CASCADE;
DROP TABLE IF EXISTS favorites              CASCADE;
DROP TABLE IF EXISTS auction_rights_analysis CASCADE;
DROP TABLE IF EXISTS auction_realty_details  CASCADE;
DROP TABLE IF EXISTS auction_vehicle_details CASCADE;
DROP TABLE IF EXISTS auction_movable_details CASCADE;
DROP TABLE IF EXISTS auctions               CASCADE;

DROP TYPE IF EXISTS auction_status     CASCADE;
DROP TYPE IF EXISTS auction_source     CASCADE;
DROP TYPE IF EXISTS asset_type         CASCADE;
DROP TYPE IF EXISTS property_category  CASCADE;
DROP TYPE IF EXISTS vehicle_category   CASCADE;

-- ---------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------
-- ENUMs
-- ---------------------------------------------------------------------
CREATE TYPE auction_source    AS ENUM ('onbid', 'court');
CREATE TYPE asset_type        AS ENUM ('realty', 'movable', 'vehicle');
CREATE TYPE auction_status    AS ENUM (
    'scheduled',  -- 입찰준비중
    'ongoing',    -- 입찰진행중
    'sold',       -- 낙찰
    'failed',     -- 유찰
    'cancelled'   -- 취하/취소/변경
);
-- 부동산 사용자 친화 카테고리 (cltr_usg_*에서 매핑)
CREATE TYPE property_category AS ENUM (
    'apartment','villa','house','officetel','commercial','land','etc'
);
-- 차량 사용자 친화 카테고리 (carVhknNm 매핑)
CREATE TYPE vehicle_category  AS ENUM (
    'sedan','van','truck','bus','motorcycle','special','etc'
);


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
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


-- ---------------------------------------------------------------------
-- AUCTIONS  (parent — onbid/court 통합 메타)
-- ---------------------------------------------------------------------
CREATE TABLE auctions (
    id                      BIGSERIAL PRIMARY KEY,

    source                  auction_source NOT NULL DEFAULT 'onbid',
    asset_type              asset_type     NOT NULL,
    status                  auction_status NOT NULL DEFAULT 'scheduled',

    -- onbid 식별자들 (source='onbid'일 때 cltr_mng_no, pbct_cdtn_no는 NOT NULL 효과)
    cltr_mng_no             VARCHAR(100),    -- 물건관리번호
    pbct_cdtn_no            BIGINT,          -- 공매조건번호
    onbid_cltr_no           BIGINT,          -- 온비드물건번호
    onbid_pbanc_no          BIGINT,          -- 온비드공고번호
    pbct_no                 BIGINT,          -- 공매번호
    pbct_nsq                VARCHAR(3),      -- 회차
    pbct_sn                 VARCHAR(5),      -- 차수

    -- court 식별자
    case_number             VARCHAR(100),
    court_name              VARCHAR(100),

    title                   VARCHAR(1000),

    -- 원본 상태 코드 (정규화된 status enum과 별개로 보존)
    pbct_stat_cd            VARCHAR(4),
    pbct_stat_nm            VARCHAR(100),

    -- 재산 / 처분 / 입찰 코드 (코드+명 둘 다 보존: 신규 코드 추가 대비)
    prpt_div_cd             VARCHAR(4),
    prpt_div_nm             VARCHAR(100),
    dsps_mthod_cd           VARCHAR(4),
    dsps_mthod_nm           VARCHAR(100),
    bid_div_cd              VARCHAR(4),
    bid_div_nm              VARCHAR(100),
    bid_mthod_cd            VARCHAR(4),
    bid_mthod_nm            VARCHAR(100),
    cptn_mthod_cd           VARCHAR(4),
    cptn_mthod_nm           VARCHAR(100),
    totalamt_unpc_div_cd    VARCHAR(4),
    totalamt_unpc_div_nm    VARCHAR(100),

    -- 용도 (대/중/소)
    usg_lcls_id             VARCHAR(20),
    usg_lcls_nm             VARCHAR(100),
    usg_mcls_id             VARCHAR(20),
    usg_mcls_nm             VARCHAR(100),
    usg_scls_id             VARCHAR(20),
    usg_scls_nm             VARCHAR(100),

    -- 주소
    ltno_pnu                VARCHAR(19),
    rdnm_pnu                VARCHAR(25),
    region_sido             VARCHAR(100),
    region_sigungu          VARCHAR(100),
    region_emd              VARCHAR(100),
    address                 TEXT,                          -- 표시용 결합 주소
    location                GEOMETRY(Point, 4326),         -- 카카오 지오코딩 결과

    -- 가격
    appraisal_price         BIGINT,                        -- apslEvlAmt
    min_bid_price           BIGINT,                        -- 숫자 파싱 가능 시
    min_bid_price_text      VARCHAR(100),                  -- 비공개 텍스트 포함 원문
    first_bid_price         BIGINT,                        -- frstBidPrc (캠코국유)
    apsl_lowst_ratio        NUMERIC(12,6),
    frst_lowst_ratio        NUMERIC(12,6),
    fee_rate                NUMERIC(8,4),

    -- 일정 / 진행
    bid_begin_at            TIMESTAMPTZ,
    bid_end_at              TIMESTAMPTZ,
    failed_count            INTEGER NOT NULL DEFAULT 0,
    progress_count          INTEGER NOT NULL DEFAULT 0,
    pvct_trgt_yn            BOOLEAN,
    batc_bid_yn             BOOLEAN,

    -- 입찰 옵션
    elec_grpr_use_yn        BOOLEAN,
    collb_bid_psbl_yn       BOOLEAN,
    twtm_gthr_bid_psbl_yn   BOOLEAN,
    subt_bid_psbl_yn        BOOLEAN,

    -- 기관
    request_org_nm          VARCHAR(200),                  -- 의뢰기관 (압류재산)
    announce_org_nm         VARCHAR(200),                  -- 공고기관

    -- 임대 (dsps_mthod_cd='0002')
    rent_method_nm          VARCHAR(100),
    rent_period_text        VARCHAR(100),

    -- 기타
    evc_rsby_target         VARCHAR(400),                  -- 인도/인수책임
    dtbt_rqr_edtm           VARCHAR(4000),                 -- 배분요구종기
    thumbnail_url           VARCHAR(500),                  -- thnlImgUrlAdr
    image_urls              JSONB NOT NULL DEFAULT '[]'::jsonb,  -- 상세 API potoUrlList

    correction_yn           BOOLEAN NOT NULL DEFAULT FALSE,
    modified_at             TIMESTAMPTZ,                   -- mdfcnDt

    -- 원본 raw 응답 (디버깅 / 미래 매핑 보강)
    raw                     JSONB NOT NULL DEFAULT '{}'::jsonb,

    crawled_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_auctions_updated_at ON auctions;
CREATE TRIGGER trg_auctions_updated_at BEFORE UPDATE ON auctions
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- per-source partial unique
CREATE UNIQUE INDEX uq_auctions_onbid_id
    ON auctions (cltr_mng_no, pbct_cdtn_no)
    WHERE source = 'onbid';
CREATE UNIQUE INDEX uq_auctions_court_id
    ON auctions (case_number)
    WHERE source = 'court';

-- 검색 / 필터 인덱스
CREATE INDEX idx_auctions_location_gist  ON auctions USING GIST (location);
CREATE INDEX idx_auctions_asset_type     ON auctions (asset_type);
CREATE INDEX idx_auctions_status_asset   ON auctions (status, asset_type);
CREATE INDEX idx_auctions_bid_end_at     ON auctions (bid_end_at);
CREATE INDEX idx_auctions_region         ON auctions (region_sido, region_sigungu);
CREATE INDEX idx_auctions_modified_at    ON auctions (modified_at DESC);
CREATE INDEX idx_auctions_address_trgm
    ON auctions USING GIN (address extensions.gin_trgm_ops);


-- ---------------------------------------------------------------------
-- AUCTION_REALTY_DETAILS  (1:1)
-- ---------------------------------------------------------------------
CREATE TABLE auction_realty_details (
    auction_id          BIGINT      PRIMARY KEY REFERENCES auctions(id) ON DELETE CASCADE,
    property_category   property_category NOT NULL DEFAULT 'etc',
    land_sqms           NUMERIC(18,4),     -- 토지면적
    bld_sqms            NUMERIC(18,4),     -- 건물면적
    alc_yn              BOOLEAN,           -- 지분물건여부
    attrs               JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
DROP TRIGGER IF EXISTS trg_realty_details_updated_at ON auction_realty_details;
CREATE TRIGGER trg_realty_details_updated_at BEFORE UPDATE ON auction_realty_details
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE INDEX idx_realty_property_category ON auction_realty_details (property_category);
CREATE INDEX idx_realty_bld_sqms          ON auction_realty_details (bld_sqms);
CREATE INDEX idx_realty_land_sqms         ON auction_realty_details (land_sqms);


-- ---------------------------------------------------------------------
-- AUCTION_VEHICLE_DETAILS  (1:1)
-- ---------------------------------------------------------------------
CREATE TABLE auction_vehicle_details (
    auction_id          BIGINT      PRIMARY KEY REFERENCES auctions(id) ON DELETE CASCADE,
    vehicle_category    vehicle_category NOT NULL DEFAULT 'etc',
    maker               VARCHAR(200),    -- cltrMkrNm
    vehicle_kind        VARCHAR(500),    -- carVhknNm
    model_name          VARCHAR(500),    -- carMdlNm
    year_model          CHAR(4),         -- yrmdl
    plate_no            VARCHAR(2000),   -- vhrnoCont
    mileage_km          BIGINT,          -- drvDstc
    displacement_cc     BIGINT,          -- dsvlm
    transmission        VARCHAR(500),    -- pnsNm
    fuel                VARCHAR(200),    -- fuelCont
    color               VARCHAR(100),    -- carColrNm
    quantity_text       VARCHAR(100),    -- qntyCont
    attrs               JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
DROP TRIGGER IF EXISTS trg_vehicle_details_updated_at ON auction_vehicle_details;
CREATE TRIGGER trg_vehicle_details_updated_at BEFORE UPDATE ON auction_vehicle_details
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE INDEX idx_vehicle_category   ON auction_vehicle_details (vehicle_category);
CREATE INDEX idx_vehicle_maker_mdl  ON auction_vehicle_details (maker, model_name);
CREATE INDEX idx_vehicle_plate_no   ON auction_vehicle_details (plate_no);
CREATE INDEX idx_vehicle_year_model ON auction_vehicle_details (year_model);


-- ---------------------------------------------------------------------
-- AUCTION_MOVABLE_DETAILS  (1:1) — 기계/예술품/회원권/식품 등 이질성 큼
-- ---------------------------------------------------------------------
CREATE TABLE auction_movable_details (
    auction_id              BIGINT  PRIMARY KEY REFERENCES auctions(id) ON DELETE CASCADE,
    maker                   VARCHAR(200),    -- cltrMkrNm
    model_name              VARCHAR(100),    -- mdlNm
    manufacture_year        CHAR(4),         -- mnftYr
    quantity_text           VARCHAR(100),    -- qntyCont
    production_place        VARCHAR(200),    -- prdlcPlorCont
    use_period_year         NUMERIC(18,4),   -- usePerdQnty
    size_text               VARCHAR(200),    -- mvastSizeCont
    weight_text             VARCHAR(200),    -- cltrWt
    custody_place           VARCHAR(500),    -- cltrCstdPlcNm
    author_name             VARCHAR(300),    -- autrNm (예술품)
    membership_name         VARCHAR(200),    -- mbsNm (회원권)
    membership_section_text VARCHAR(2000),   -- mbsSctnoCont
    commodity_name          VARCHAR(500),    -- mvastCmdtyNm
    property_name           VARCHAR(500),    -- prptNm
    product_name            VARCHAR(500),    -- cltrPrdctNm
    supplier_item_name      VARCHAR(500),    -- splrItmNm
    attrs                   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
DROP TRIGGER IF EXISTS trg_movable_details_updated_at ON auction_movable_details;
CREATE TRIGGER trg_movable_details_updated_at BEFORE UPDATE ON auction_movable_details
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


-- ---------------------------------------------------------------------
-- AUCTION_BID_RESULTS  (입찰 결과 — auction_id에 1:1)
-- ---------------------------------------------------------------------
CREATE TABLE auction_bid_results (
    id                      BIGSERIAL PRIMARY KEY,
    auction_id              BIGINT      NOT NULL UNIQUE
                            REFERENCES auctions(id) ON DELETE CASCADE,
    cltr_mng_no             VARCHAR(100) NOT NULL,
    pbct_cdtn_no            BIGINT       NOT NULL,
    pbct_nsq                VARCHAR(3),
    pbct_sn                 VARCHAR(5),
    status                  auction_status NOT NULL,
    pbct_stat_cd            VARCHAR(4),
    pbct_stat_nm            VARCHAR(100),
    winning_bid_amount      BIGINT,
    winning_bid_amounts     JSONB NOT NULL DEFAULT '[]'::jsonb,
    bid_amounts             JSONB NOT NULL DEFAULT '[]'::jsonb,
    apsl_scfb_ratio         NUMERIC(12,6),
    lowst_scfb_ratio        NUMERIC(12,6),
    valid_bidder_count      INTEGER,
    invalid_bidder_count    INTEGER,
    opbd_at                 TIMESTAMPTZ,
    opbd_begin_at           TIMESTAMPTZ,
    opbd_end_at             TIMESTAMPTZ,
    afsb_rtrcn_reason       TEXT,
    rtrcn_reason            TEXT,
    announce_name           VARCHAR(2000),
    announce_mng_no         VARCHAR(40),
    bid_deposit_text        VARCHAR(400),
    raw                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    crawled_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
DROP TRIGGER IF EXISTS trg_bid_results_updated_at ON auction_bid_results;
CREATE TRIGGER trg_bid_results_updated_at BEFORE UPDATE ON auction_bid_results
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX IF NOT EXISTS idx_bid_results_status   ON auction_bid_results (status);
CREATE INDEX IF NOT EXISTS idx_bid_results_opbd_at  ON auction_bid_results (opbd_at DESC);
CREATE INDEX IF NOT EXISTS idx_bid_results_cltr_mng ON auction_bid_results (cltr_mng_no, pbct_cdtn_no);


-- ---------------------------------------------------------------------
-- AUCTION_RIGHTS_ANALYSIS  (권리분석 — auction_id에 1:1)
-- ---------------------------------------------------------------------
CREATE TABLE auction_rights_analysis (
    id            BIGSERIAL PRIMARY KEY,
    auction_id    BIGINT      NOT NULL UNIQUE
                  REFERENCES auctions(id) ON DELETE CASCADE,
    summary       TEXT,
    risk_level    SMALLINT,
    rights_data   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (risk_level IS NULL OR risk_level BETWEEN 1 AND 3)
);
DROP TRIGGER IF EXISTS trg_rights_updated_at ON auction_rights_analysis;
CREATE TRIGGER trg_rights_updated_at BEFORE UPDATE ON auction_rights_analysis
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


-- ---------------------------------------------------------------------
-- FAVORITES
-- ---------------------------------------------------------------------
CREATE TABLE favorites (
    user_id     BIGINT      NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    auction_id  BIGINT      NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, auction_id)
);
CREATE INDEX idx_favorites_auction_id ON favorites (auction_id);


-- ---------------------------------------------------------------------
-- COMMENTS
-- ---------------------------------------------------------------------
CREATE TABLE comments (
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
CREATE TRIGGER trg_comments_updated_at BEFORE UPDATE ON comments
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE INDEX idx_comments_auction_id_created ON comments (auction_id, created_at DESC);
CREATE INDEX idx_comments_user_id            ON comments (user_id);
