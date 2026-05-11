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

from app.domain.auction.repository import AuctionRepository
from app.domain.auction.schemas import (
    AssetType,
    AuctionSource,
    AuctionStatus,
    AuctionUpsertItem,
    MovableAttrs,
    PropertyCategory,
    RealtyAttrs,
    VehicleAttrs,
    VehicleCategory,
)
from app.infrastructure.external.kakao_geocoder import KakaoGeocoder
from app.infrastructure.external.onbid_client import (
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


def compose_address(
    sido: str | None, sigungu: str | None, emd: str | None, fallback: str | None = None
) -> str | None:
    parts = [p for p in (sido, sigungu, emd) if p]
    if parts:
        return " ".join(parts)
    return fallback


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
        address=compose_address(sido, sigungu, emd),
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
        """이미지가 비어 있는 부동산 N건에 대해 상세 API를 호출해 image_urls 보강.

        일일 쿼터 1000/서비스 고려해 호출자가 limit 제어. 부분 실패는 카운트만.
        """
        stats = EnrichStats()
        targets = await self._repo.list_realty_missing_images(limit=limit)
        stats.targeted = len(targets)
        for auction_id, cltr, pbct in targets:
            stats.api_calls += 1
            try:
                detail = await self._client.get_realty_detail(
                    cltr_mng_no=cltr, pbct_cdtn_no=pbct
                )
            except OnbidQuotaExceeded as e:
                logger.warning("enrich quota exceeded — stopping: %s", e)
                break
            except OnbidAPIError as e:
                logger.info("enrich skip auction_id=%d: %s", auction_id, e)
                stats.failed += 1
                continue
            urls = extract_image_urls(detail)
            if urls:
                await self._repo.update_image_urls(auction_id, urls)
                stats.enriched += 1
        return stats
