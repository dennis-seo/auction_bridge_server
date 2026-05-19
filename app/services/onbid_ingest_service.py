"""온비드 차세대 OpenAPI → 정규화 → 지오코딩 → DB upsert 파이프라인.

asset_type별로 별도 normalize 함수를 가지며, 결과는 모두 `AuctionUpsertItem`.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.auction.repository import (
    AuctionRepository,
    AuctionSiblingMeta,
)
from app.domain.auction.schemas import (
    AnnouncementMeta,
    AssetType,
    AuctionSource,
    AuctionStatus,
    AuctionUpsertItem,
    BidInfo,
    BidMethods,
    BidRestrictions,
    BidTerms,
    MovableAttrs,
    PreviousRoundBid,
    PropertyCategory,
    RealtyAttrs,
    RoundBidSchedule,
    VehicleAttrs,
    VehicleCategory,
)
from app.infrastructure.external.kakao_geocoder import KakaoGeocoder
from app.infrastructure.external.onbid_client import (
    CLTR_TYPE_CD,
    OnbidAPIError,
    OnbidAssetService,
    OnbidClient,
    OnbidQuotaExceeded,
    PrptDivCd,
    extract_image_urls,
)

logger = logging.getLogger(__name__)


KST = timezone(timedelta(hours=9))


# =====================================================================
# 코드 / 이름 매핑
# =====================================================================

# pbctStatCd → AuctionStatus
def map_status(code: str | None, name: str | None) -> AuctionStatus:
    if code:
        c = code.strip()
        if c in ("0001", "0009"):
            return AuctionStatus.SCHEDULED
        if c in ("0002", "0006", "0003"):
            # 0003 입찰마감 — 결과는 입찰결과 API로 보강 전까지 ONGOING로 둔다
            return AuctionStatus.ONGOING
        if c == "0010":
            return AuctionStatus.SOLD
        if c == "0011":
            return AuctionStatus.FAILED
        if c in ("0012", "0014"):
            return AuctionStatus.CANCELLED
    blob = (name or "").strip()
    if any(k in blob for k in ("낙찰", "매각결정", "성공")):
        return AuctionStatus.SOLD
    if "유찰" in blob:
        return AuctionStatus.FAILED
    if any(k in blob for k in ("취하", "취소", "변경", "정지")):
        return AuctionStatus.CANCELLED
    if "진행" in blob:
        return AuctionStatus.ONGOING
    return AuctionStatus.SCHEDULED


# 세부 분류(scls/title) 우선 매칭 — 주거용건물 내부에서 아파트/오피스텔/빌라/주택을 분리
_REALTY_SPECIFIC: list[tuple[PropertyCategory, tuple[str, ...]]] = [
    (PropertyCategory.APARTMENT, ("아파트",)),
    (PropertyCategory.OFFICETEL, ("오피스텔",)),
    (PropertyCategory.VILLA, ("빌라", "연립", "다세대")),
    (PropertyCategory.HOUSE, ("단독", "다가구", "주택", "기숙사")),
]

# mcls(중분류)별 기본 매핑 — 세부 분류로 안 잡힌 경우의 fallback
_REALTY_MCLS: list[tuple[PropertyCategory, tuple[str, ...]]] = [
    (PropertyCategory.LAND, ("토지",)),
    (PropertyCategory.HOUSE, ("주거용",)),
    (PropertyCategory.COMMERCIAL, ("상가용", "업무용", "산업용", "특수용")),
]

# 마지막 키워드 fallback (모든 텍스트 blob 검색)
_REALTY_FALLBACK: list[tuple[PropertyCategory, tuple[str, ...]]] = [
    (PropertyCategory.COMMERCIAL, (
        "상가", "근린", "업무", "사무실", "점포",
        "공장", "창고", "판매시설", "숙박",
    )),
    (PropertyCategory.LAND, ("임야", "전답", "대지", "잡종지", "과수원", "도로", "공원")),
]


def map_property_category(
    scls: str | None,
    mcls: str | None,
    lcls: str | None = None,
    title: str | None = None,
) -> PropertyCategory:
    # 1) scls/title 안의 세부 분류 키워드 매칭
    specific_blob = " ".join(t for t in (scls, title) if t)
    for cat, keywords in _REALTY_SPECIFIC:
        if any(kw in specific_blob for kw in keywords):
            return cat
    # 2) mcls 매핑
    if mcls:
        for cat, keywords in _REALTY_MCLS:
            if any(kw in mcls for kw in keywords):
                return cat
    # 3) 전체 blob fallback
    full_blob = " ".join(t for t in (scls, mcls, lcls, title) if t)
    for cat, keywords in _REALTY_FALLBACK:
        if any(kw in full_blob for kw in keywords):
            return cat
    return PropertyCategory.ETC


# 차량 카테고리. carVhknNm은 실데이터에서 모델명(예 "쏘나타")이 들어가는 경우가 많아
# usg_scls_nm을 1순위 매핑 소스로 사용한다.
_VEHICLE_KEYWORDS: list[tuple[VehicleCategory, tuple[str, ...]]] = [
    (VehicleCategory.SEDAN, ("승용", "SUV")),
    (VehicleCategory.VAN, ("승합",)),
    (VehicleCategory.TRUCK, ("화물", "트럭")),
    (VehicleCategory.BUS, ("버스",)),
    (VehicleCategory.MOTORCYCLE, ("이륜", "오토바이")),
    (VehicleCategory.SPECIAL, ("특수", "지게차", "굴삭기", "중기", "소방", "안전", "인명구조")),
]


def map_vehicle_category(*texts: str | None) -> VehicleCategory:
    blob = " ".join(t for t in texts if t)
    for cat, keywords in _VEHICLE_KEYWORDS:
        if any(kw in blob for kw in keywords):
            return cat
    return VehicleCategory.ETC


# =====================================================================
# 파서 helpers
# =====================================================================
_INT_RE = re.compile(r"-?\d+")


def parse_int(v: Any) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = _INT_RE.search(s)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def parse_float(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_yn(v: Any) -> bool | None:
    if v is None:
        return None
    s = str(v).strip().upper()
    if s == "Y":
        return True
    if s == "N":
        return False
    return None


def parse_dt(v: Any) -> datetime | None:
    """yyyyMMddHHmm / yyyyMMddHHmmss / yyyyMMdd 등 다양한 포맷 지원. KST 부여."""
    if v is None:
        return None
    s = str(v).strip()
    if not s.isdigit():
        return None
    fmts = {
        14: "%Y%m%d%H%M%S",
        12: "%Y%m%d%H%M",
        10: "%Y%m%d%H",
        8: "%Y%m%d",
    }
    fmt = fmts.get(len(s))
    if fmt is None:
        return None
    try:
        dt = datetime.strptime(s, fmt).replace(tzinfo=KST)
    except ValueError:
        return None
    # 비현실적 sentinel(예: 2999-12-30) 제거
    if not (1990 <= dt.year <= 2100):
        return None
    return dt


# 지번 토큰: "4-6", "209", "산 12-3" 등. 동/리 다음 첫 숫자(부번 옵션) + "산" prefix 허용.
_PARCEL_TOKEN_RE = re.compile(r"^(산\s*)?(\d+)(?:-(\d+))?(?=\s|$)")


def _extract_parcel(admin: str, title: str | None) -> str | None:
    """title이 admin(='sido sigungu emd')로 시작하면 그 뒤 첫 토큰에서 지번을 잘라낸다.

    예) admin="경기도 성남시 분당구 정자동", title="경기도 성남시 분당구 정자동 4-6 한국잡월드"
        → "4-6"
    """
    if not title or not admin:
        return None
    remainder = title[len(admin):].lstrip() if title.startswith(admin) else None
    if remainder is None:
        return None
    m = _PARCEL_TOKEN_RE.match(remainder)
    if not m:
        return None
    san, bonbeon, bubeon = m.group(1), m.group(2), m.group(3)
    parcel = f"{bonbeon}-{bubeon}" if bubeon else bonbeon
    return f"산 {parcel}" if san else parcel


def compose_address(
    sido: str | None,
    sigungu: str | None,
    emd: str | None,
    fallback: str | None = None,
    *,
    title: str | None = None,
) -> str | None:
    """행정주소 + (가능하면) title에서 추출한 지번까지 합성.

    title이 동까지의 행정주소로 시작하면 그 뒤 첫 숫자 토큰을 지번으로 보고 결합.
    geocoder가 동(洞) centroid 대신 정확한 parcel을 매칭하도록 입력을 강화한다.
    """
    parts = [p for p in (sido, sigungu, emd) if p]
    if not parts:
        return fallback
    admin = " ".join(parts)
    parcel = _extract_parcel(admin, title)
    return f"{admin} {parcel}" if parcel else admin


def str_or_none(v: Any) -> str | None:
    """공백/None을 None으로 통일. 그 외엔 strip된 문자열."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# =====================================================================
# 공통 base normalize — (모델 필드, 응답 키, 변환자) 선언적 매핑
# =====================================================================
# 새 필드 추가 / 변환 변경 시 이 테이블만 손대면 됨.
_COMMON_FIELD_MAP: tuple[tuple[str, str, Any], ...] = (
    # identifiers
    ("onbid_cltr_no",         "onbidCltrno",          parse_int),
    ("onbid_pbanc_no",        "onbidPbancNo",         parse_int),
    ("pbct_no",               "pbctNo",               parse_int),
    ("pbct_nsq",              "pbctNsq",              str_or_none),
    ("pbct_sn",               "pbctsn",               str_or_none),
    ("title",                 "onbidCltrNm",          str_or_none),
    # status / codes
    ("pbct_stat_cd",          "pbctStatCd",           str_or_none),
    ("pbct_stat_nm",          "pbctStatNm",           str_or_none),
    ("prpt_div_cd",           "prptDivCd",            str_or_none),
    ("prpt_div_nm",           "prptDivNm",            str_or_none),
    ("dsps_mthod_cd",         "dspsMthodCd",          str_or_none),
    ("dsps_mthod_nm",         "dspsMthodNm",          str_or_none),
    ("bid_div_cd",            "bidDivCd",             str_or_none),
    ("bid_div_nm",            "bidDivNm",             str_or_none),
    ("bid_mthod_cd",          "bidMthodCd",           str_or_none),
    ("bid_mthod_nm",          "bidMthodNm",           str_or_none),
    ("cptn_mthod_cd",         "cptnMthodCd",          str_or_none),
    ("cptn_mthod_nm",         "cptnMthodNm",          str_or_none),
    ("totalamt_unpc_div_cd",  "totalamtUnpcDivCd",    str_or_none),
    ("totalamt_unpc_div_nm",  "totalamtUnpcDivNm",    str_or_none),
    # 용도 분류
    ("usg_lcls_id",           "cltrUsgLclsCtgrId",    str_or_none),
    ("usg_lcls_nm",           "cltrUsgLclsCtgrNm",    str_or_none),
    ("usg_mcls_id",           "cltrUsgMclsCtgrId",    str_or_none),
    ("usg_mcls_nm",           "cltrUsgMclsCtgrNm",    str_or_none),
    ("usg_scls_id",           "cltrUsgSclsCtgrId",    str_or_none),
    ("usg_scls_nm",           "cltrUsgSclsCtgrNm",    str_or_none),
    # 주소 PNU (지역 sido/sigungu/emd는 별도 처리 — address 합성에 사용)
    ("ltno_pnu",              "ltnoPnu",              str_or_none),
    ("rdnm_pnu",              "rdnmPnu",              str_or_none),
    # 가격
    ("appraisal_price",       "apslEvlAmt",           parse_int),
    ("min_bid_price",         "lowstBidPrcIndctCont", parse_int),
    ("min_bid_price_text",    "lowstBidPrcIndctCont", str_or_none),
    ("first_bid_price",       "frstBidPrc",           parse_int),
    ("apsl_lowst_ratio",      "apslPrcCtrsLowstBidRto", parse_float),
    ("frst_lowst_ratio",      "frstCtrsLowstBidPrcRto", parse_float),
    ("fee_rate",              "feeRate",              parse_float),
    # 일정
    ("bid_begin_at",          "cltrBidBgngDt",        parse_dt),
    ("bid_end_at",             "cltrBidEndDt",        parse_dt),
    ("pvct_trgt_yn",          "pvctTrgtYn",           parse_yn),
    ("batc_bid_yn",           "batcBidYn",            parse_yn),
    # 입찰 옵션
    ("elec_grpr_use_yn",      "eltrGrprUseYn",        parse_yn),
    ("collb_bid_psbl_yn",     "collbBidPsblYn",       parse_yn),
    ("twtm_gthr_bid_psbl_yn", "twtmGthrBidPsblYn",    parse_yn),
    ("subt_bid_psbl_yn",      "subtBidPsblYn",        parse_yn),
    # 기관 / 기타
    ("request_org_nm",        "rqstOrgNm",            str_or_none),
    ("announce_org_nm",       "orgNm",                str_or_none),
    ("rent_method_nm",        "rentMthodNm",          str_or_none),
    ("rent_period_text",      "rentPerdCont",         str_or_none),
    ("evc_rsby_target",       "evcRsbyTrgtCont",      str_or_none),
    ("dtbt_rqr_edtm",         "dtbtRqrEdtmCont",      str_or_none),
    ("thumbnail_url",         "thnlImgUrlAdr",        str_or_none),
    ("modified_at",           "mdfcnDt",              parse_dt),
)


def _normalize_common(raw: dict[str, Any], asset_type: AssetType) -> AuctionUpsertItem | None:
    cltr = str_or_none(raw.get("cltrMngNo"))
    pbct = parse_int(raw.get("pbctCdtnNo"))
    if not cltr or pbct is None:
        return None

    sido = str_or_none(raw.get("lctnSdnm"))
    sigungu = str_or_none(raw.get("lctnSggnm"))
    emd = str_or_none(raw.get("lctnEmdNm"))

    fields: dict[str, Any] = {field: parser(raw.get(key)) for field, key, parser in _COMMON_FIELD_MAP}

    return AuctionUpsertItem(
        source=AuctionSource.ONBID,
        asset_type=asset_type,
        status=map_status(raw.get("pbctStatCd"), raw.get("pbctStatNm")),
        cltr_mng_no=cltr,
        pbct_cdtn_no=pbct,
        region_sido=sido,
        region_sigungu=sigungu,
        region_emd=emd,
        address=compose_address(
            sido, sigungu, emd, title=str_or_none(raw.get("onbidCltrNm")),
        ),
        failed_count=parse_int(raw.get("usbdNft")) or 0,
        progress_count=parse_int(raw.get("bidPrgnNft")) or 0,
        correction_yn=bool(parse_yn(raw.get("crtnYn"))),
        raw=raw,
        **fields,
    )


# =====================================================================
# asset_type별 attrs builder + 일반화된 normalize
# =====================================================================
def _build_realty_attrs(raw: dict[str, Any]) -> RealtyAttrs:
    return RealtyAttrs(
        property_category=map_property_category(
            scls=raw.get("cltrUsgSclsCtgrNm"),
            mcls=raw.get("cltrUsgMclsCtgrNm"),
            lcls=raw.get("cltrUsgLclsCtgrNm"),
            title=raw.get("onbidCltrNm"),
        ),
        land_sqms=parse_float(raw.get("landSqms")),
        bld_sqms=parse_float(raw.get("bldSqms")),
        alc_yn=parse_yn(raw.get("alcYn")),
    )


def _build_movable_attrs(raw: dict[str, Any]) -> MovableAttrs:
    return MovableAttrs(
        maker=str_or_none(raw.get("cltrMkrNm")),
        model_name=str_or_none(raw.get("mdlNm")),
        manufacture_year=str_or_none(raw.get("mnftYr")),
        quantity_text=str_or_none(raw.get("qntyCont")),
        production_place=str_or_none(raw.get("prdlcPlorCont")),
        use_period_year=parse_float(raw.get("usePerdQnty")),
        size_text=str_or_none(raw.get("mvastSizeCont")),
        weight_text=str_or_none(raw.get("cltrWt")),
        custody_place=str_or_none(raw.get("cltrCstdPlcNm")),
        author_name=str_or_none(raw.get("autrNm")),
        membership_name=str_or_none(raw.get("mbsNm")),
        membership_section_text=str_or_none(raw.get("mbsSctnoCont")),
        commodity_name=str_or_none(raw.get("mvastCmdtyNm")),
        property_name=str_or_none(raw.get("prptNm")),
        product_name=str_or_none(raw.get("cltrPrdctNm")),
        supplier_item_name=str_or_none(raw.get("splrItmNm")),
    )


def _build_vehicle_attrs(raw: dict[str, Any]) -> VehicleAttrs:
    return VehicleAttrs(
        vehicle_category=map_vehicle_category(
            raw.get("cltrUsgSclsCtgrNm"),
            raw.get("cltrUsgMclsCtgrNm"),
            raw.get("carVhknNm"),
        ),
        maker=str_or_none(raw.get("cltrMkrNm")),
        vehicle_kind=str_or_none(raw.get("carVhknNm")),
        model_name=str_or_none(raw.get("carMdlNm")),
        year_model=str_or_none(raw.get("yrmdl")),
        plate_no=str_or_none(raw.get("vhrnoCont")),
        mileage_km=parse_int(raw.get("drvDstc")),
        displacement_cc=parse_int(raw.get("dsvlm")),
        transmission=str_or_none(raw.get("pnsNm")),
        fuel=str_or_none(raw.get("fuelCont")),
        color=str_or_none(raw.get("carColrNm")),
        quantity_text=str_or_none(raw.get("qntyCont")),
    )


# (asset_type, model 필드명, attrs builder)
_ASSET_BUILDERS: dict[AssetType, tuple[str, Any]] = {
    AssetType.REALTY:  ("realty",  _build_realty_attrs),
    AssetType.MOVABLE: ("movable", _build_movable_attrs),
    AssetType.VEHICLE: ("vehicle", _build_vehicle_attrs),
}


def normalize(raw: dict[str, Any], asset_type: AssetType) -> AuctionUpsertItem | None:
    """공통 normalize + asset별 attrs 채워서 반환."""
    item = _normalize_common(raw, asset_type)
    if item is None:
        return None
    field_name, builder = _ASSET_BUILDERS[asset_type]
    setattr(item, field_name, builder(raw))
    return item


# 하위 호환 — 직접 호출하는 곳을 위해 얇은 래퍼 유지 (테스트 / 호출자)
def normalize_realty(raw: dict[str, Any]) -> AuctionUpsertItem | None:
    return normalize(raw, AssetType.REALTY)


def normalize_movable(raw: dict[str, Any]) -> AuctionUpsertItem | None:
    return normalize(raw, AssetType.MOVABLE)


def normalize_vehicle(raw: dict[str, Any]) -> AuctionUpsertItem | None:
    return normalize(raw, AssetType.VEHICLE)


_NORMALIZERS = {
    OnbidAssetService.REALTY: normalize_realty,
    OnbidAssetService.MOVABLE: normalize_movable,
    OnbidAssetService.VEHICLE: normalize_vehicle,
}


def _normalize_pbanc_cltr_item(
    raw: dict[str, Any],
    sibling: AuctionSiblingMeta,
    pbanc_mng_no: str,
) -> AuctionUpsertItem | None:
    """공고상세 물건정보(getPbancCltrInf2) 응답 1행 → AuctionUpsertItem.

    응답에 부재한 cltr-stable 필드(주소·지오·PNU·기관·썸네일·asset_type)는
    sibling 메타에서 그대로 상속한다. 같은 cltr_mng_no의 기존 회차가 보유하고
    있는 값이라 위치·카테고리는 회차가 바뀌어도 동일하다.
    """
    cltr = str_or_none(raw.get("cltrMngNo"))
    pbct = parse_int(raw.get("pbctCdtnNo"))
    if not cltr or pbct is None:
        return None

    fields: dict[str, Any] = {
        f: parser(raw.get(k)) for f, k, parser in _COMMON_FIELD_MAP
    }
    # 공고 응답에 없는 cltr-stable 필드는 sibling 값으로 채움 (None일 때만)
    for sib_field, sib_val in (
        ("ltno_pnu", sibling.ltno_pnu),
        ("rdnm_pnu", sibling.rdnm_pnu),
        ("thumbnail_url", sibling.thumbnail_url),
        ("request_org_nm", sibling.request_org_nm),
        ("announce_org_nm", sibling.announce_org_nm),
    ):
        if fields.get(sib_field) is None:
            fields[sib_field] = sib_val

    item = AuctionUpsertItem(
        source=AuctionSource.ONBID,
        asset_type=sibling.asset_type,
        status=map_status(raw.get("pbctStatCd"), raw.get("pbctStatNm")),
        cltr_mng_no=cltr,
        pbct_cdtn_no=pbct,
        pbanc_mng_no=pbanc_mng_no,
        region_sido=sibling.region_sido,
        region_sigungu=sibling.region_sigungu,
        region_emd=sibling.region_emd,
        address=sibling.address,
        lat=sibling.lat,
        lng=sibling.lng,
        failed_count=parse_int(raw.get("usbdNft")) or 0,
        correction_yn=bool(parse_yn(raw.get("crtnYn"))),
        raw=raw,
        **fields,
    )

    if sibling.asset_type == AssetType.REALTY:
        item.realty = RealtyAttrs(
            property_category=sibling.property_category or PropertyCategory.ETC,
        )
    elif sibling.asset_type == AssetType.VEHICLE:
        item.vehicle = VehicleAttrs()
    elif sibling.asset_type == AssetType.MOVABLE:
        item.movable = MovableAttrs()

    return item


# =====================================================================
# Service
# =====================================================================
@dataclass(slots=True)
class IngestStats:
    fetched: int = 0
    normalized: int = 0
    geocoded: int = 0
    inserted: int = 0
    updated: int = 0
    pages: int = 0
    by_asset: dict[str, int] = field(default_factory=dict)
    by_prpt_div: dict[str, int] = field(default_factory=dict)


def _accumulate(into: IngestStats, src: IngestStats) -> None:
    into.fetched += src.fetched
    into.normalized += src.normalized
    into.geocoded += src.geocoded
    into.inserted += src.inserted
    into.updated += src.updated
    into.pages += src.pages


@dataclass(slots=True)
class EnrichStats:
    targeted: int = 0
    api_calls: int = 0
    enriched: int = 0
    failed: int = 0


@dataclass(slots=True)
class BidResultPayload:
    """auction_bid_results upsert에 쓰일 정규화 결과."""
    cltr_mng_no: str
    pbct_cdtn_no: int
    pbct_nsq: str | None
    pbct_sn: str | None
    status: AuctionStatus
    pbct_stat_cd: str | None
    pbct_stat_nm: str | None
    winning_bid_amount: int | None
    winning_bid_amounts: list[int]
    bid_amounts: list[int]
    apsl_scfb_ratio: float | None
    lowst_scfb_ratio: float | None
    valid_bidder_count: int | None
    invalid_bidder_count: int | None
    opbd_at: datetime | None
    opbd_begin_at: datetime | None
    opbd_end_at: datetime | None
    afsb_rtrcn_reason: str | None
    rtrcn_reason: str | None
    announce_name: str | None
    announce_mng_no: str | None
    bid_deposit_text: str | None
    raw: dict[str, Any]


def _split_amounts(s: Any) -> list[int]:
    """`scfbAmt` / `bidAmtClgCont`는 복수 값일 때 `|`로 연결됨."""
    if s is None:
        return []
    text = str(s).strip()
    if not text:
        return []
    out: list[int] = []
    for token in text.split("|"):
        n = parse_int(token)
        if n is not None:
            out.append(n)
    return out


def _iter_list_block(block: Any) -> list[dict[str, Any]]:
    """Onbid 응답의 array 필드는 list / dict / None 모두 가능 — 통일."""
    if block is None:
        return []
    if isinstance(block, list):
        return [el for el in block if isinstance(el, dict)]
    if isinstance(block, dict):
        return [block]
    return []


def normalize_bid_info(raw: dict[str, Any]) -> BidInfo:
    """#7 응답 dict → 정규화된 BidInfo 모델.

    빈 응답이어도 BidInfo (모든 필드 default) 를 반환. 호출자는 `bid_info.raw`로
    원본 보존을 확인할 수 있다.
    """
    if not isinstance(raw, dict):
        return BidInfo()

    methods = BidMethods(
        collab_bid=parse_yn(raw.get("collbBidPsblYn")),
        proxy_bid=parse_yn(raw.get("subtBidPsblYn")),
        electronic_guarantee=parse_yn(raw.get("eltrGrprUseYn")),
        deposit_substitute_doc=parse_yn(raw.get("tdpsSbtnDcmtYn")),
        runner_up_application=parse_yn(raw.get("nrnkAplyPsblYn")),
        multi_bid=parse_yn(raw.get("twtmGthrBidPsblYn")),
        same_ip_bid=parse_yn(raw.get("smnsIpDpcnBidBlcktYn")),
    )
    terms = BidTerms(
        deposit_text=str_or_none(raw.get("pbctTdpsCont")),
        payment_method=str_or_none(raw.get("pcmtPayMtdCont")),
        payment_term=str_or_none(raw.get("pcmtPayTermCont")),
        bid_validity_criterion=str_or_none(raw.get("bidVldCrtrCont")),
        participation_fee=parse_int(raw.get("ptctCmsn")),
        failed_count_cumulative=parse_int(raw.get("usbdNft")),
    )
    restrictions = BidRestrictions(
        qualification=str_or_none(raw.get("qlfcLmtCdtnCont")),
        region=str_or_none(raw.get("rgnLmtCdtnCont")),
        etc=str_or_none(raw.get("etcLmtCdtnCont")),
    )
    announcement = AnnouncementMeta(
        pbanc_mng_no=str_or_none(raw.get("pbancMngNo")),
        pbanc_name=str_or_none(raw.get("onbidPbancNm")),
    )

    previous_rounds = [
        PreviousRoundBid(
            pbct_nsq=str_or_none(el.get("pbctNsq")),
            pbct_sn=str_or_none(el.get("pbctsn")),
            opened_at=parse_dt(el.get("cltrOpbdDt")),
            result_name=str_or_none(el.get("pbctStatNm")),
            min_bid_price_text=str_or_none(el.get("lowstBidPrcIndctCont")),
            winning_amount_text=str_or_none(el.get("scfbAmt")),
            apsl_to_winning_ratio=parse_float(el.get("apslPrcCtrsLowstBidRto")),
            lowest_to_winning_ratio=parse_float(el.get("frstCtrsLowstBidPrcRto")),
        )
        for el in _iter_list_block(raw.get("prcnBidClgList"))
    ]

    round_schedules = [
        RoundBidSchedule(
            bid_mng_no=str_or_none(el.get("bidMngNo")),
            pbct_nsq=str_or_none(el.get("pbctNsq")),
            pbct_sn=str_or_none(el.get("pbctsn")),
            bid_div=str_or_none(el.get("bidDivNm")),
            bid_begin_at=parse_dt(el.get("cltrBidBgngDt")),
            bid_end_at=parse_dt(el.get("cltrBidEndDt")),
            opened_at=parse_dt(el.get("cltrOpbdDt")),
            open_place=str_or_none(el.get("pbctOpbdPlcCont")),
            min_bid_price_text=str_or_none(el.get("lowstBidPrcIndctCont")),
            sale_decision_at=parse_dt(el.get("cltrDodispDt")),
        )
        for el in _iter_list_block(raw.get("cseqBidInfClgList"))
    ]

    return BidInfo(
        methods=methods,
        terms=terms,
        restrictions=restrictions,
        announcement=announcement,
        previous_rounds=previous_rounds,
        round_schedules=round_schedules,
        raw=raw,
    )


def normalize_bid_result(raw: dict[str, Any]) -> BidResultPayload | None:
    cltr = (raw.get("cltrMngNo") or "").strip()
    pbct = parse_int(raw.get("pbctCdtnNo"))
    if not cltr or pbct is None:
        return None
    winning_amounts = _split_amounts(raw.get("scfbAmt"))
    bid_amounts = _split_amounts(raw.get("bidAmtClgCont"))
    return BidResultPayload(
        cltr_mng_no=cltr,
        pbct_cdtn_no=pbct,
        pbct_nsq=(raw.get("pbctNsq") or None),
        pbct_sn=(raw.get("pbctsn") or None),
        status=map_status(raw.get("pbctStatCd"), raw.get("pbctStatNm")),
        pbct_stat_cd=(raw.get("pbctStatCd") or None),
        pbct_stat_nm=(raw.get("pbctStatNm") or None),
        winning_bid_amount=winning_amounts[0] if winning_amounts else None,
        winning_bid_amounts=winning_amounts,
        bid_amounts=bid_amounts,
        apsl_scfb_ratio=parse_float(raw.get("apslPrcCtrsScfbPrcRto")),
        lowst_scfb_ratio=parse_float(raw.get("lowstBidCtrsScfbPrcRto")),
        valid_bidder_count=parse_int(raw.get("vldBddrNope")),
        invalid_bidder_count=parse_int(raw.get("nfctBddrNope")),
        opbd_at=parse_dt(raw.get("cltrOpbdDt")),
        opbd_begin_at=parse_dt(raw.get("opbdBgngDt")),
        opbd_end_at=parse_dt(raw.get("opbdCmptnDt")),
        afsb_rtrcn_reason=(raw.get("afsbRtrcnRsnCont") or None),
        rtrcn_reason=(raw.get("rtrcnRsnCont") or None),
        announce_name=(raw.get("onbidPbancNm") or None),
        announce_mng_no=(raw.get("pbancMngNo") or None),
        bid_deposit_text=(raw.get("pbctTdpsCont") or None),
        raw=raw,
    )


class OnbidIngestService:
    def __init__(
        self,
        client: OnbidClient,
        geocoder: KakaoGeocoder,
        repo: AuctionRepository,
        *,
        geocode_concurrency: int = 10,
    ) -> None:
        self._client = client
        self._geocoder = geocoder
        self._repo = repo
        self._geocode_concurrency = geocode_concurrency

    async def run_one(
        self,
        asset: OnbidAssetService,
        *,
        max_pages: int = 1,
        num_of_rows: int = 100,
        prpt_div_cd: str | tuple[str, ...] = PrptDivCd.DEFAULT_INGEST,
        pvct_trgt_yn: str = "N",
    ) -> IngestStats:
        codes = (prpt_div_cd,) if isinstance(prpt_div_cd, str) else tuple(prpt_div_cd)
        total = IngestStats()
        for code in codes:
            try:
                s = await self._run(
                    asset=asset,
                    max_pages=max_pages,
                    num_of_rows=num_of_rows,
                    prpt_div_cd=code,
                    pvct_trgt_yn=pvct_trgt_yn,
                )
            except OnbidQuotaExceeded as e:
                logger.warning(
                    "Quota exceeded — stopping run_one at %s/%s: %s",
                    asset.value, code, e,
                )
                break
            _accumulate(total, s)
            total.by_prpt_div[code] = total.by_prpt_div.get(code, 0) + s.normalized
        total.by_asset[asset.value] = total.normalized
        return total

    async def run_full(
        self,
        *,
        max_pages_per_asset: int = 50,
        num_of_rows: int = 500,
        prpt_div_cd: str | tuple[str, ...] = PrptDivCd.DEFAULT_INGEST,
        pvct_trgt_yn: str = "N",
    ) -> IngestStats:
        codes = (prpt_div_cd,) if isinstance(prpt_div_cd, str) else tuple(prpt_div_cd)
        total = IngestStats()
        quota_hit = False
        for asset in OnbidAssetService:
            asset_total = 0
            for code in codes:
                try:
                    s = await self._run(
                        asset=asset,
                        max_pages=max_pages_per_asset,
                        num_of_rows=num_of_rows,
                        prpt_div_cd=code,
                        pvct_trgt_yn=pvct_trgt_yn,
                    )
                except OnbidQuotaExceeded as e:
                    logger.warning(
                        "Quota exceeded — stopping run_full at %s/%s: %s",
                        asset.value, code, e,
                    )
                    quota_hit = True
                    break
                _accumulate(total, s)
                asset_total += s.normalized
                total.by_prpt_div[code] = total.by_prpt_div.get(code, 0) + s.normalized
            total.by_asset[asset.value] = asset_total
            if quota_hit:
                break
        return total

    async def _run(
        self,
        *,
        asset: OnbidAssetService,
        max_pages: int,
        num_of_rows: int,
        prpt_div_cd: str | tuple[str, ...],
        pvct_trgt_yn: str,
    ) -> IngestStats:
        stats = IngestStats()
        normalizer = _NORMALIZERS[asset]

        async for page in self._client.iter_assets(
            asset,
            prpt_div_cd=prpt_div_cd,
            pvct_trgt_yn=pvct_trgt_yn,
            num_of_rows=num_of_rows,
            max_pages=max_pages,
        ):
            stats.pages += 1
            stats.fetched += len(page.items)
            normalized: list[AuctionUpsertItem] = []
            for raw in page.items:
                item = normalizer(raw)
                if item is None:
                    continue
                normalized.append(item)
            stats.normalized += len(normalized)

            # 부동산만 지오코딩 (동산/차량은 주소가 없거나 보관소라 우선순위 낮음)
            if asset == OnbidAssetService.REALTY:
                stats.geocoded += await self._geocode_batch(normalized)

            if normalized:
                ins, upd = await self._repo.upsert_many(normalized)
                stats.inserted += ins
                stats.updated += upd
                logger.info(
                    "ingest asset=%s prpt_div=%s page=%d fetched=%d normalized=%d "
                    "geocoded=%d inserted=%d updated=%d",
                    asset.value, prpt_div_cd, page.page_no, len(page.items),
                    len(normalized), stats.geocoded, ins, upd,
                )
        return stats

    async def _geocode_batch(self, items: list[AuctionUpsertItem]) -> int:
        """주소가 있는 item에 대해 동시 지오코딩 — Semaphore로 동시 호출 수 제한."""
        sem = asyncio.Semaphore(self._geocode_concurrency)

        async def _one(it: AuctionUpsertItem) -> bool:
            if not it.address:
                return False
            async with sem:
                lng, lat = await self._geocoder.lookup(it.address)
            if lng is not None and lat is not None:
                it.lng = lng
                it.lat = lat
                return True
            return False

        results = await asyncio.gather(*[_one(i) for i in items])
        return sum(1 for r in results if r)

    async def enrich_bid_results(self, *, limit: int = 50) -> EnrichStats:
        """bid_end_at 지난 ongoing 매물에 대해 입찰결과상세(#9)를 호출해 결과를 적재.

        결과가 SOLD/FAILED/CANCELLED로 확정되면 auctions.status도 갱신.
        """
        stats = EnrichStats()
        targets = await self._repo.list_auctions_pending_results(limit=limit)
        stats.targeted = len(targets)
        for auction_id, cltr, pbct in targets:
            stats.api_calls += 1
            try:
                detail = await self._client.get_bid_result_detail(
                    cltr_mng_no=cltr, pbct_cdtn_no=pbct
                )
            except OnbidQuotaExceeded as e:
                logger.warning("bid_result quota exceeded — stopping: %s", e)
                break
            except OnbidAPIError as e:
                logger.info("bid_result skip auction_id=%d: %s", auction_id, e)
                stats.failed += 1
                continue
            payload = normalize_bid_result(detail) if detail else None
            if payload is None:
                stats.failed += 1
                continue
            await self._repo.upsert_bid_result(auction_id, payload)
            stats.enriched += 1
        return stats

    async def enrich_realty_image_urls(self, *, limit: int = 50) -> EnrichStats:
        """이미지가 비어 있는 부동산 N건에 대해 상세 API(#4)를 호출해 image_urls 보강.

        일일 쿼터 1000/서비스 고려해 호출자가 limit 제어. 부분 실패는 카운트만.
        """
        return await self._enrich_image_urls(
            limit=limit,
            list_fn=self._repo.list_realty_missing_images,
            detail_fn=self._client.get_realty_detail,
            asset_label="realty",
        )

    async def enrich_movable_image_urls(self, *, limit: int = 50) -> EnrichStats:
        """이미지가 비어 있는 동산 N건에 대해 상세 API(#5)를 호출해 image_urls 보강."""
        return await self._enrich_image_urls(
            limit=limit,
            list_fn=self._repo.list_movable_missing_images,
            detail_fn=self._client.get_movable_detail,
            asset_label="movable",
        )

    async def enrich_bid_info(self, *, limit: int = 50) -> EnrichStats:
        """#7 입찰정보로 매물 1건당 1콜 → 정규화된 BidInfo dict를 auctions.bid_info에 저장.

        원본 raw는 `bid_info.raw`에 보존. scheduled/ongoing 매물 중 bid_info가
        비어있는 N건만 처리. 일일 1,000/일 한도 안에서 호출자가 limit 제어.
        """
        stats = EnrichStats()
        targets = await self._repo.list_auctions_missing_bid_info(limit=limit)
        stats.targeted = len(targets)
        for auction_id, cltr, pbct in targets:
            stats.api_calls += 1
            try:
                detail = await self._client.get_bid_info(
                    cltr_mng_no=cltr, pbct_cdtn_no=pbct,
                )
            except OnbidQuotaExceeded as e:
                logger.warning("bid_info enrich quota exceeded — stopping: %s", e)
                break
            except OnbidAPIError as e:
                logger.info(
                    "bid_info enrich skip auction_id=%d: %s", auction_id, e,
                )
                stats.failed += 1
                continue
            if not detail:
                stats.failed += 1
                continue
            bid_info = normalize_bid_info(detail)
            await self._repo.update_bid_info(
                auction_id, bid_info.model_dump(mode="json"),
            )
            stats.enriched += 1
        return stats

    async def _enrich_image_urls(
        self,
        *,
        limit: int,
        list_fn,
        detail_fn,
        asset_label: str,
    ) -> EnrichStats:
        stats = EnrichStats()
        targets = await list_fn(limit=limit)
        stats.targeted = len(targets)
        for auction_id, cltr, pbct in targets:
            stats.api_calls += 1
            try:
                detail = await detail_fn(cltr_mng_no=cltr, pbct_cdtn_no=pbct)
            except OnbidQuotaExceeded as e:
                logger.warning(
                    "%s image enrich quota exceeded — stopping: %s", asset_label, e
                )
                break
            except OnbidAPIError as e:
                logger.info(
                    "%s image enrich skip auction_id=%d: %s", asset_label, auction_id, e
                )
                stats.failed += 1
                continue
            urls = extract_image_urls(detail)
            if urls:
                await self._repo.update_image_urls(auction_id, urls)
                stats.enriched += 1
        return stats

    async def enrich_pbanc_mng_no(self, *, limit: int = 100) -> EnrichStats:
        """Phase A: active onbid 매물 중 pbanc_mng_no가 NULL인 것들에 대해
        getPbancList2를 호출해 매핑을 해결하고 DB에 캐시한다.

        같은 asset_type × bidPrdYmd(yyyyMMdd)로 그룹화하여 호출을 절감.
        bid_begin_at이 NULL인 매물은 검색 키가 없어 failed로 카운트.
        """
        stats = EnrichStats()
        targets = await self._repo.list_auctions_missing_pbanc_mng_no(limit=limit)
        stats.targeted = len(targets)
        if not targets:
            return stats

        # (asset_type, yyyyMMdd) 단위 그룹화
        buckets: dict[tuple[AssetType, str], list[Any]] = {}
        for t in targets:
            if t.bid_begin_at is None:
                stats.failed += 1
                continue
            ymd = t.bid_begin_at.astimezone(KST).strftime("%Y%m%d")
            buckets.setdefault((t.asset_type, ymd), []).append(t)

        resolved: list[tuple[int, str]] = []
        quota_hit = False
        for (asset_type, ymd), bucket in buckets.items():
            if quota_hit:
                for _ in bucket:
                    stats.failed += 1
                continue
            cltr_type_cd = CLTR_TYPE_CD[OnbidAssetService(asset_type.value)]
            pbanc_map: dict[int, str] = {}
            page_no = 1
            max_pages = 10
            while page_no <= max_pages:
                stats.api_calls += 1
                try:
                    page = await self._client.list_announcements(
                        cltr_type_cd=cltr_type_cd,
                        prpt_div_cd=PrptDivCd.DEFAULT_INGEST,
                        bid_prd_ymd_start=ymd,
                        bid_prd_ymd_end=ymd,
                        page_no=page_no,
                        num_of_rows=500,
                    )
                except OnbidQuotaExceeded as e:
                    logger.warning("pbanc resolve quota exceeded — stopping: %s", e)
                    quota_hit = True
                    break
                except OnbidAPIError as e:
                    logger.info(
                        "pbanc resolve error asset=%s ymd=%s page=%d: %s",
                        asset_type.value, ymd, page_no, e,
                    )
                    break
                for it in page.items:
                    onbid_no = parse_int(it.get("onbidPbancNo"))
                    mng_no = str_or_none(it.get("pbancMngNo"))
                    if onbid_no is not None and mng_no:
                        pbanc_map[onbid_no] = mng_no
                if not page.has_more:
                    break
                page_no += 1
            for t in bucket:
                mng = pbanc_map.get(t.onbid_pbanc_no)
                if mng:
                    resolved.append((t.auction_id, mng))
                else:
                    stats.failed += 1

        if resolved:
            n = await self._repo.update_pbanc_mng_no_batch(resolved)
            stats.enriched = n
            logger.info(
                "pbanc resolve done — resolved=%d / targeted=%d", n, stats.targeted,
            )
        return stats

    async def enrich_missing_rounds_via_pbanc(
        self, *, limit: int = 50,
    ) -> EnrichStats:
        """Phase B: pbanc_mng_no가 알려진 공고 그룹에 대해 getPbancCltrInf2 호출 →
        응답의 (cltr, pbct) 중 DB에 없는 회차만 골라 sibling 메타 상속 후 upsert.
        """
        stats = EnrichStats()
        groups = await self._repo.list_pbanc_groups_for_round_enrich(limit=limit)
        stats.targeted = len(groups)
        if not groups:
            return stats

        new_items: list[AuctionUpsertItem] = []
        for grp in groups:
            stats.api_calls += 1
            try:
                page = await self._client.get_announcement_cltrs(
                    pbanc_mng_no=grp.pbanc_mng_no, page_no=1, num_of_rows=500,
                )
            except OnbidQuotaExceeded as e:
                logger.warning(
                    "pbanc round enrich quota exceeded — stopping: %s", e,
                )
                break
            except OnbidAPIError as e:
                logger.info(
                    "pbanc round enrich error pbanc=%s: %s", grp.pbanc_mng_no, e,
                )
                stats.failed += 1
                continue
            for raw in page.items:
                cltr = str_or_none(raw.get("cltrMngNo"))
                pbct = parse_int(raw.get("pbctCdtnNo"))
                if not cltr or pbct is None:
                    continue
                if (cltr, pbct) in grp.existing_keys:
                    continue
                sibling = grp.siblings.get(cltr)
                if sibling is None:
                    continue
                item = _normalize_pbanc_cltr_item(raw, sibling, grp.pbanc_mng_no)
                if item is not None:
                    new_items.append(item)

        if new_items:
            ins, upd = await self._repo.upsert_many(new_items)
            stats.enriched = ins
            logger.info(
                "pbanc round enrich done — inserted=%d updated=%d / groups=%d",
                ins, upd, stats.targeted,
            )
        return stats

    async def enrich_default_round_for_cltr(
        self, cltr_mng_no: str,
    ) -> EnrichStats:
        """단일 cltr_mng_no의 "현재 노출 회차"를 OnBid에서 받아 DB에 upsert.

        Phase A/B가 미래/과거 매물의 pbanc_mng_no를 해결하지 못해 누락된 회차에
        대해 핀포인트로 동작. `getRlstDtlInf2`를 cltrMngNo만 필터로 호출하면
        OnBid 공식 사이트가 보여주는 그 회차(보통 1회차)를 1건 응답으로 받는다.
        """
        stats = EnrichStats(targeted=1)
        sibling, existing_pbct, pbanc_mng_no = await self._repo.get_sibling_for_cltr(
            cltr_mng_no,
        )
        if sibling is None:
            logger.info(
                "default-round enrich skipped — cltr=%s DB에 없음", cltr_mng_no,
            )
            stats.failed = 1
            return stats

        stats.api_calls = 1
        try:
            raw = await self._client.get_realty_detail(cltr_mng_no=cltr_mng_no)
        except OnbidQuotaExceeded as e:
            logger.warning("default-round enrich quota exceeded: %s", e)
            stats.failed = 1
            return stats
        except OnbidAPIError as e:
            logger.info("default-round enrich error cltr=%s: %s", cltr_mng_no, e)
            stats.failed = 1
            return stats

        if not raw or not raw.get("cltrMngNo"):
            logger.info(
                "default-round enrich empty response cltr=%s", cltr_mng_no,
            )
            stats.failed = 1
            return stats

        pbct = parse_int(raw.get("pbctCdtnNo"))
        if pbct is None:
            stats.failed = 1
            return stats
        if pbct in existing_pbct:
            logger.info(
                "default-round enrich noop cltr=%s pbct=%d already exists",
                cltr_mng_no, pbct,
            )
            return stats

        item = _normalize_pbanc_cltr_item(raw, sibling, pbanc_mng_no or "")
        if item is None:
            stats.failed = 1
            return stats
        # pbanc_mng_no 미해결인 경우는 빈 문자열로 들어가지 않게 None 처리.
        if not pbanc_mng_no:
            item.pbanc_mng_no = None

        ins, upd = await self._repo.upsert_many([item])
        stats.enriched = ins + upd
        logger.info(
            "default-round enrich done cltr=%s pbct=%d ins=%d upd=%d",
            cltr_mng_no, pbct, ins, upd,
        )
        return stats

    async def enrich_default_rounds_auto(
        self, *, limit: int = 50, dry_run: bool = False, ratio: float = 0.95,
    ) -> dict:
        """1회차 row 누락 의심 cltr를 자동 검출해 enrich_default_round_for_cltr 일괄 실행.

        dry_run=True면 후보 cltr 리스트만 반환하고 OnBid 호출/DB 변경 없음.
        """
        cltrs = await self._repo.list_cltrs_missing_default_round(
            limit=limit, ratio=ratio,
        )
        result: dict = {
            "targeted": len(cltrs),
            "dry_run": dry_run,
            "ratio": ratio,
            "cltr_mng_nos": cltrs[:50],  # 앞 50개 샘플만 응답에
        }
        if dry_run or not cltrs:
            result["enriched"] = 0
            result["failed"] = 0
            result["api_calls"] = 0
            return result

        total_enriched = 0
        total_failed = 0
        total_calls = 0
        for cltr in cltrs:
            try:
                s = await self.enrich_default_round_for_cltr(cltr)
            except OnbidQuotaExceeded as e:
                logger.warning("auto default-round quota exceeded: %s", e)
                break
            total_enriched += s.enriched
            total_failed += s.failed
            total_calls += s.api_calls
        result["enriched"] = total_enriched
        result["failed"] = total_failed
        result["api_calls"] = total_calls
        return result

    async def enrich_bid_results_by_list(
        self,
        *,
        days_lookback: int = 2,
        num_of_rows: int = 100,
        max_pages_per_combo: int = 20,
        prpt_div_cd: str | tuple[str, ...] = PrptDivCd.DEFAULT_INGEST,
    ) -> EnrichStats:
        """#8 입찰결과목록으로 최근 개찰된 매물 결과를 일괄 보강.

        cltrTypeCd(부동산/자동차/동산) × prptDivCd로 한 번에 100건씩 페이지 순회.
        결과는 DB ongoing/scheduled 매물과 (cltr_mng_no, pbct_cdtn_no)로 매칭해서
        upsert. #9 호출당 1건 보강 대비 호출 수 대폭 절감.

        days_lookback=2면 어제~오늘 개찰 범위. 운영 권장 안전 마진.
        """
        stats = EnrichStats()
        today = datetime.now(KST).date()
        start = today - timedelta(days=max(0, days_lookback - 1))
        opbd_start = start.strftime("%Y%m%d")
        opbd_end = today.strftime("%Y%m%d")

        for asset in OnbidAssetService:
            cltr_type_cd = CLTR_TYPE_CD[asset]
            page_no = 1
            while page_no <= max_pages_per_combo:
                stats.api_calls += 1
                try:
                    page = await self._client.list_bid_results(
                        cltr_type_cd=cltr_type_cd,
                        prpt_div_cd=prpt_div_cd,
                        opbd_dt_start=opbd_start,
                        opbd_dt_end=opbd_end,
                        page_no=page_no,
                        num_of_rows=num_of_rows,
                    )
                except OnbidQuotaExceeded as e:
                    logger.warning(
                        "bid_result list quota exceeded — stopping: %s", e
                    )
                    return stats
                except OnbidAPIError as e:
                    logger.info(
                        "bid_result list error asset=%s page=%d: %s",
                        asset.value, page_no, e,
                    )
                    break

                if not page.items:
                    break
                stats.targeted += len(page.items)

                # 결과 → 정규화 + 키 추출
                payloads: list[BidResultPayload] = []
                keys: list[tuple[str, int]] = []
                for raw in page.items:
                    payload = normalize_bid_result(raw)
                    if payload is None:
                        continue
                    payloads.append(payload)
                    keys.append((payload.cltr_mng_no, payload.pbct_cdtn_no))

                if not payloads:
                    if not page.has_more:
                        break
                    page_no += 1
                    continue

                id_map = await self._repo.lookup_active_auction_ids(keys)
                for payload in payloads:
                    aid = id_map.get((payload.cltr_mng_no, payload.pbct_cdtn_no))
                    if aid is None:
                        continue
                    await self._repo.upsert_bid_result(aid, payload)
                    stats.enriched += 1

                logger.info(
                    "bid_result list asset=%s page=%d items=%d matched=%d",
                    asset.value, page_no, len(page.items),
                    sum(1 for p in payloads if (p.cltr_mng_no, p.pbct_cdtn_no) in id_map),
                )
                if not page.has_more:
                    break
                page_no += 1
        return stats
