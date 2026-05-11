"""Pydantic 모델 — 차세대 온비드(B010003) v2 스키마 기준.

DB(`auctions` + 3 detail) 와 1:1로 매핑되는 도메인/응답/적재 모델을 정의한다.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator


# =====================================================================
# Enums (DB enum과 동일 식별자)
# =====================================================================
class AuctionSource(str, Enum):
    ONBID = "onbid"
    COURT = "court"


class AssetType(str, Enum):
    REALTY = "realty"
    MOVABLE = "movable"
    VEHICLE = "vehicle"


class AuctionStatus(str, Enum):
    SCHEDULED = "scheduled"
    ONGOING = "ongoing"
    SOLD = "sold"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PropertyCategory(str, Enum):
    APARTMENT = "apartment"
    VILLA = "villa"
    HOUSE = "house"
    OFFICETEL = "officetel"
    COMMERCIAL = "commercial"
    LAND = "land"
    ETC = "etc"


class VehicleCategory(str, Enum):
    SEDAN = "sedan"
    VAN = "van"
    TRUCK = "truck"
    BUS = "bus"
    MOTORCYCLE = "motorcycle"
    SPECIAL = "special"
    ETC = "etc"


# =====================================================================
# 표시 라벨 (한국어)
# =====================================================================
ASSET_TYPE_LABELS_KO: dict[AssetType, str] = {
    AssetType.REALTY: "부동산",
    AssetType.MOVABLE: "동산",
    AssetType.VEHICLE: "차량",
}

PROPERTY_CATEGORY_LABELS_KO: dict[PropertyCategory, str] = {
    PropertyCategory.APARTMENT: "아파트",
    PropertyCategory.VILLA: "빌라/연립",
    PropertyCategory.HOUSE: "단독/다가구",
    PropertyCategory.OFFICETEL: "오피스텔",
    PropertyCategory.COMMERCIAL: "상가/업무",
    PropertyCategory.LAND: "토지",
    PropertyCategory.ETC: "기타",
}

VEHICLE_CATEGORY_LABELS_KO: dict[VehicleCategory, str] = {
    VehicleCategory.SEDAN: "승용",
    VehicleCategory.VAN: "승합",
    VehicleCategory.TRUCK: "화물",
    VehicleCategory.BUS: "버스",
    VehicleCategory.MOTORCYCLE: "이륜",
    VehicleCategory.SPECIAL: "특수",
    VehicleCategory.ETC: "기타",
}


# =====================================================================
# Stats response
# =====================================================================
class CategorySubStat(BaseModel):
    key: str = Field(description="property_category 또는 vehicle_category 값")
    label: str
    count: int = Field(ge=0)


class AssetGroupStat(BaseModel):
    asset_type: AssetType
    label: str
    total: int = Field(ge=0)
    categories: list[CategorySubStat] = Field(default_factory=list)


class SourceStat(BaseModel):
    source: AuctionSource
    count: int = Field(ge=0)


class AuctionStatsResponse(BaseModel):
    total: int = Field(description="진행 중인 전체 매물 수")
    groups: list[AssetGroupStat]
    by_source: list[SourceStat]


# =====================================================================
# Map / List
# =====================================================================
class AuctionListItem(BaseModel):
    """지도 마커 / 리스트 카드용 경량 페이로드."""
    id: int
    source: AuctionSource
    asset_type: AssetType
    status: AuctionStatus
    title: str | None = None
    address: str | None = None
    region_sido: str | None = None
    region_sigungu: str | None = None
    lat: float | None = None
    lng: float | None = None
    appraisal_price: int | None = None
    min_bid_price: int | None = None
    bid_end_at: datetime | None = None
    fee_rate: float | None = None
    failed_count: int = 0
    thumbnail_url: str | None = None


class AuctionListResponse(BaseModel):
    items: list[AuctionListItem]
    truncated: bool = Field(
        default=False,
        description="True면 limit에 의해 잘림 — 클라이언트가 줌인 유도",
    )


# =====================================================================
# Detail (asset_type별 polymorphic `details` 블록)
# =====================================================================
class RealtyDetails(BaseModel):
    asset_type: Literal["realty"] = "realty"
    property_category: PropertyCategory = PropertyCategory.ETC
    land_sqms: float | None = None
    bld_sqms: float | None = None
    alc_yn: bool | None = None


class VehicleDetails(BaseModel):
    asset_type: Literal["vehicle"] = "vehicle"
    vehicle_category: VehicleCategory = VehicleCategory.ETC
    maker: str | None = None
    vehicle_kind: str | None = None
    model_name: str | None = None
    year_model: str | None = None
    plate_no: str | None = None
    mileage_km: int | None = None
    displacement_cc: int | None = None
    transmission: str | None = None
    fuel: str | None = None
    color: str | None = None
    quantity_text: str | None = None


class MovableDetails(BaseModel):
    asset_type: Literal["movable"] = "movable"
    maker: str | None = None
    model_name: str | None = None
    manufacture_year: str | None = None
    quantity_text: str | None = None
    production_place: str | None = None
    use_period_year: float | None = None
    size_text: str | None = None
    weight_text: str | None = None
    custody_place: str | None = None
    author_name: str | None = None
    membership_name: str | None = None
    commodity_name: str | None = None
    product_name: str | None = None


AssetDetails = Annotated[
    Union[RealtyDetails, VehicleDetails, MovableDetails],
    Field(discriminator="asset_type"),
]


class AuctionCodeNames(BaseModel):
    """온비드 응답의 *코드명* 필드 묶음 — 표시 전용 (카탈로그 그룹)."""
    pbct_stat: str | None = None        # 입찰결과
    prpt_div: str | None = None         # 재산유형
    dsps_mthod: str | None = None       # 처분방식 (매각/임대)
    bid_div: str | None = None          # 입찰구분 (인터넷/현장)
    bid_mthod: str | None = None        # 세부입찰방식
    cptn_mthod: str | None = None       # 입찰방식
    totalamt_unpc_div: str | None = None  # 총액/단가
    usg_lcls: str | None = None         # 용도 대분류
    usg_mcls: str | None = None         # 용도 중분류
    usg_scls: str | None = None         # 용도 소분류


class AuctionBidOptions(BaseModel):
    """입찰 옵션 Y/N 묶음 — 상세화면 카드 1장으로 처리."""
    elec_grpr_use: bool | None = None       # 전자보증서 가능
    collb_bid_psbl: bool | None = None      # 공동입찰 가능
    twtm_gthr_bid_psbl: bool | None = None  # 2회 이상 입찰 가능
    subt_bid_psbl: bool | None = None       # 대리입찰 가능


class RightsAnalysisSummary(BaseModel):
    summary: str | None = None
    risk_level: int | None = Field(default=None, ge=1, le=3)
    rights_data: dict[str, Any] = Field(default_factory=dict)


class AuctionDetail(BaseModel):
    id: int
    source: AuctionSource
    asset_type: AssetType
    status: AuctionStatus
    title: str | None = None

    # 식별자
    cltr_mng_no: str | None = None
    pbct_cdtn_no: int | None = None
    onbid_cltr_no: int | None = None
    onbid_pbanc_no: int | None = None
    pbct_no: int | None = None
    case_number: str | None = None
    court_name: str | None = None

    # 주소
    address: str | None = None
    region_sido: str | None = None
    region_sigungu: str | None = None
    region_emd: str | None = None
    lat: float | None = None
    lng: float | None = None

    # 가격
    appraisal_price: int | None = None
    min_bid_price: int | None = None
    min_bid_price_text: str | None = None
    first_bid_price: int | None = None
    apsl_lowst_ratio: float | None = None
    frst_lowst_ratio: float | None = None
    fee_rate: float | None = None

    # 일정
    bid_begin_at: datetime | None = None
    bid_end_at: datetime | None = None
    failed_count: int = 0
    progress_count: int = 0
    pvct_trgt_yn: bool | None = None

    # 코드명 묶음 (입찰결과/재산유형/처분방식/용도 등)
    code_names: AuctionCodeNames = Field(default_factory=AuctionCodeNames)

    # 입찰 옵션 Y/N 묶음
    bid_options: AuctionBidOptions = Field(default_factory=AuctionBidOptions)

    # 기관
    request_org_nm: str | None = None
    announce_org_nm: str | None = None

    # 이미지
    thumbnail_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)

    # 기타
    evc_rsby_target: str | None = None

    # 카테고리별 디테일
    details: AssetDetails | None = None

    # 권리분석
    rights_analysis: RightsAnalysisSummary | None = None


# =====================================================================
# Ingest payload (외부 API → 정규화 → DB upsert)
# =====================================================================
class RealtyAttrs(BaseModel):
    property_category: PropertyCategory = PropertyCategory.ETC
    land_sqms: float | None = None
    bld_sqms: float | None = None
    alc_yn: bool | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class VehicleAttrs(BaseModel):
    vehicle_category: VehicleCategory = VehicleCategory.ETC
    maker: str | None = None
    vehicle_kind: str | None = None
    model_name: str | None = None
    year_model: str | None = None
    plate_no: str | None = None
    mileage_km: int | None = None
    displacement_cc: int | None = None
    transmission: str | None = None
    fuel: str | None = None
    color: str | None = None
    quantity_text: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class MovableAttrs(BaseModel):
    maker: str | None = None
    model_name: str | None = None
    manufacture_year: str | None = None
    quantity_text: str | None = None
    production_place: str | None = None
    use_period_year: float | None = None
    size_text: str | None = None
    weight_text: str | None = None
    custody_place: str | None = None
    author_name: str | None = None
    membership_name: str | None = None
    membership_section_text: str | None = None
    commodity_name: str | None = None
    property_name: str | None = None
    product_name: str | None = None
    supplier_item_name: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class AuctionUpsertItem(BaseModel):
    """온비드 응답 → DB upsert 정규화 모델."""
    source: AuctionSource = AuctionSource.ONBID
    asset_type: AssetType
    status: AuctionStatus = AuctionStatus.SCHEDULED

    # onbid 식별자 (필수)
    cltr_mng_no: str
    pbct_cdtn_no: int
    onbid_cltr_no: int | None = None
    onbid_pbanc_no: int | None = None
    pbct_no: int | None = None
    pbct_nsq: str | None = None
    pbct_sn: str | None = None

    # court (선택 — 향후 법원 경매)
    case_number: str | None = None
    court_name: str | None = None

    title: str | None = None

    # 코드 + 명
    pbct_stat_cd: str | None = None
    pbct_stat_nm: str | None = None
    prpt_div_cd: str | None = None
    prpt_div_nm: str | None = None
    dsps_mthod_cd: str | None = None
    dsps_mthod_nm: str | None = None
    bid_div_cd: str | None = None
    bid_div_nm: str | None = None
    bid_mthod_cd: str | None = None
    bid_mthod_nm: str | None = None
    cptn_mthod_cd: str | None = None
    cptn_mthod_nm: str | None = None
    totalamt_unpc_div_cd: str | None = None
    totalamt_unpc_div_nm: str | None = None

    # 용도
    usg_lcls_id: str | None = None
    usg_lcls_nm: str | None = None
    usg_mcls_id: str | None = None
    usg_mcls_nm: str | None = None
    usg_scls_id: str | None = None
    usg_scls_nm: str | None = None

    # 주소
    ltno_pnu: str | None = None
    rdnm_pnu: str | None = None
    region_sido: str | None = None
    region_sigungu: str | None = None
    region_emd: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None

    # 가격
    appraisal_price: int | None = None
    min_bid_price: int | None = None
    min_bid_price_text: str | None = None
    first_bid_price: int | None = None
    apsl_lowst_ratio: float | None = None
    frst_lowst_ratio: float | None = None
    fee_rate: float | None = None

    # 일정 / 진행
    bid_begin_at: datetime | None = None
    bid_end_at: datetime | None = None
    failed_count: int = 0
    progress_count: int = 0
    pvct_trgt_yn: bool | None = None
    batc_bid_yn: bool | None = None

    # 입찰 옵션
    elec_grpr_use_yn: bool | None = None
    collb_bid_psbl_yn: bool | None = None
    twtm_gthr_bid_psbl_yn: bool | None = None
    subt_bid_psbl_yn: bool | None = None

    # 기관
    request_org_nm: str | None = None
    announce_org_nm: str | None = None

    # 임대
    rent_method_nm: str | None = None
    rent_period_text: str | None = None

    # 기타
    evc_rsby_target: str | None = None
    dtbt_rqr_edtm: str | None = None
    thumbnail_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    correction_yn: bool = False
    modified_at: datetime | None = None

    raw: dict[str, Any] = Field(default_factory=dict)

    # asset-specific (asset_type에 맞는 1개만 채움)
    realty: RealtyAttrs | None = None
    vehicle: VehicleAttrs | None = None
    movable: MovableAttrs | None = None


# =====================================================================
# Query params
# =====================================================================
class BBoxQuery(BaseModel):
    min_lng: float = Field(ge=-180, le=180)
    min_lat: float = Field(ge=-90, le=90)
    max_lng: float = Field(ge=-180, le=180)
    max_lat: float = Field(ge=-90, le=90)
    asset_type: AssetType | None = None
    property_category: PropertyCategory | None = None
    vehicle_category: VehicleCategory | None = None
    status: AuctionStatus | None = None
    limit: int = Field(default=200, ge=1, le=500)

    @model_validator(mode="after")
    def _bounds(self) -> "BBoxQuery":
        if self.min_lng >= self.max_lng:
            raise ValueError("min_lng must be < max_lng")
        if self.min_lat >= self.max_lat:
            raise ValueError("min_lat must be < max_lat")
        return self


# =====================================================================
# Vehicle list / stats (asset_type=vehicle 전용)
# =====================================================================
class VehicleListItem(BaseModel):
    """자동차 리스트 카드용 페이로드 — 차량 특화 필드 포함."""
    id: int
    source: AuctionSource
    status: AuctionStatus
    title: str | None = None
    region_sido: str | None = None
    region_sigungu: str | None = None
    appraisal_price: int | None = None
    min_bid_price: int | None = None
    bid_begin_at: datetime | None = None
    bid_end_at: datetime | None = None
    fee_rate: float | None = None
    failed_count: int = 0
    thumbnail_url: str | None = None

    vehicle_category: VehicleCategory
    maker: str | None = None
    model_name: str | None = None
    year_model: str | None = None
    mileage_km: int | None = None
    displacement_cc: int | None = None
    transmission: str | None = None
    fuel: str | None = None


class VehicleListResponse(BaseModel):
    items: list[VehicleListItem]
    total: int = Field(description="필터 조건에 매칭되는 총 건수")
    offset: int
    limit: int


class VehicleListQuery(BaseModel):
    vehicle_category: VehicleCategory | None = None
    maker: str | None = Field(default=None, max_length=50)
    fuel: str | None = Field(default=None, max_length=20)
    transmission: str | None = Field(default=None, max_length=20)
    year_model_min: str | None = Field(default=None, pattern=r"^\d{4}$")
    year_model_max: str | None = Field(default=None, pattern=r"^\d{4}$")
    mileage_km_min: int | None = Field(default=None, ge=0)
    mileage_km_max: int | None = Field(default=None, ge=0)
    displacement_cc_min: int | None = Field(default=None, ge=0)
    displacement_cc_max: int | None = Field(default=None, ge=0)
    status: AuctionStatus | None = None
    region_sido: str | None = Field(default=None, max_length=20)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class VehicleFacetCount(BaseModel):
    key: str
    label: str | None = None
    count: int = Field(ge=0)


class VehicleMakerCount(BaseModel):
    maker: str
    count: int = Field(ge=0)


class VehicleYearBucket(BaseModel):
    year_model: str
    count: int = Field(ge=0)


class VehicleStatsResponse(BaseModel):
    total: int = Field(description="진행 중인(scheduled+ongoing) 차량 매물 수")
    by_category: list[VehicleFacetCount]
    by_fuel: list[VehicleFacetCount]
    by_transmission: list[VehicleFacetCount]
    by_maker_top: list[VehicleMakerCount]
    by_year_model: list[VehicleYearBucket]


# =====================================================================
# Bid info (#7 OnbidCltrBidDtlSrvc2) — auctions.bid_info JSONB 정규화 스키마
# =====================================================================
class BidMethods(BaseModel):
    """입찰 방법 가능 여부."""
    collab_bid: bool | None = None              # collbBidPsblYn
    proxy_bid: bool | None = None               # subtBidPsblYn
    electronic_guarantee: bool | None = None    # eltrGrprUseYn
    deposit_substitute_doc: bool | None = None  # tdpsSbtnDcmtYn
    runner_up_application: bool | None = None   # nrnkAplyPsblYn
    multi_bid: bool | None = None               # twtmGthrBidPsblYn
    same_ip_bid: bool | None = None             # smnsIpDpcnBidBlcktYn


class BidTerms(BaseModel):
    """입찰 조건/비용."""
    deposit_text: str | None = None             # pbctTdpsCont (예: "최저입찰가*5%")
    payment_method: str | None = None           # pcmtPayMtdCont
    payment_term: str | None = None             # pcmtPayTermCont
    bid_validity_criterion: str | None = None   # bidVldCrtrCont
    participation_fee: int | None = None        # ptctCmsn
    failed_count_cumulative: int | None = None  # usbdNft


class BidRestrictions(BaseModel):
    """제한경쟁 입찰 조건 (입찰방식=제한경쟁일 때만 채워짐)."""
    qualification: str | None = None    # qlfcLmtCdtnCont
    region: str | None = None           # rgnLmtCdtnCont
    etc: str | None = None              # etcLmtCdtnCont


class AnnouncementMeta(BaseModel):
    """공고 메타데이터."""
    pbanc_mng_no: str | None = None     # pbancMngNo
    pbanc_name: str | None = None       # onbidPbancNm


class PreviousRoundBid(BaseModel):
    """이전 회차 입찰 결과."""
    pbct_nsq: str | None = None
    pbct_sn: str | None = None
    opened_at: datetime | None = None        # cltrOpbdDt
    result_name: str | None = None           # pbctStatNm
    min_bid_price_text: str | None = None    # lowstBidPrcIndctCont
    winning_amount_text: str | None = None   # scfbAmt (VARCHAR — 복수 `|` 구분)
    apsl_to_winning_ratio: float | None = None  # apslPrcCtrsLowstBidRto
    lowest_to_winning_ratio: float | None = None  # frstCtrsLowstBidPrcRto


class RoundBidSchedule(BaseModel):
    """회차별 입찰 일정/장소."""
    bid_mng_no: str | None = None
    pbct_nsq: str | None = None
    pbct_sn: str | None = None
    bid_div: str | None = None              # bidDivNm
    bid_begin_at: datetime | None = None    # cltrBidBgngDt
    bid_end_at: datetime | None = None      # cltrBidEndDt
    opened_at: datetime | None = None       # cltrOpbdDt
    open_place: str | None = None           # pbctOpbdPlcCont
    min_bid_price_text: str | None = None
    sale_decision_at: datetime | None = None  # cltrDodispDt (압류재산 only)


class BidInfo(BaseModel):
    """auctions.bid_info JSONB에 저장되는 정규화 스키마.

    원본 #7 응답에서 클라가 매물 상세 화면에 표시할 6개 묶음만 발췌.
    조건부 필드(평가방식/적정최고가/수의계약/제안서평가 등)는 raw로만 보존.
    """
    methods: BidMethods = Field(default_factory=BidMethods)
    terms: BidTerms = Field(default_factory=BidTerms)
    restrictions: BidRestrictions = Field(default_factory=BidRestrictions)
    announcement: AnnouncementMeta = Field(default_factory=AnnouncementMeta)
    previous_rounds: list[PreviousRoundBid] = Field(default_factory=list)
    round_schedules: list[RoundBidSchedule] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
