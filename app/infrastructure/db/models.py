"""SQLAlchemy ORM 모델 — 차세대 온비드 v2 스키마 기준.

DDL은 db/schema.sql이 만들었으므로 모든 ENUM에 create_type=False.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.auction.schemas import (
    AssetType,
    AuctionSource,
    AuctionStatus,
    PropertyCategory,
    VehicleCategory,
)


class Base(DeclarativeBase):
    pass


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        create_type=False,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
    )


class AuctionORM(Base):
    __tablename__ = "auctions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    source: Mapped[AuctionSource] = mapped_column(
        _pg_enum(AuctionSource, "auction_source"),
        nullable=False, server_default="onbid",
    )
    asset_type: Mapped[AssetType] = mapped_column(
        _pg_enum(AssetType, "asset_type"), nullable=False
    )
    status: Mapped[AuctionStatus] = mapped_column(
        _pg_enum(AuctionStatus, "auction_status"),
        nullable=False, server_default="scheduled",
    )

    cltr_mng_no: Mapped[str | None] = mapped_column(String(100))
    pbct_cdtn_no: Mapped[int | None] = mapped_column(BigInteger)
    onbid_cltr_no: Mapped[int | None] = mapped_column(BigInteger)
    onbid_pbanc_no: Mapped[int | None] = mapped_column(BigInteger)
    pbct_no: Mapped[int | None] = mapped_column(BigInteger)
    pbct_nsq: Mapped[str | None] = mapped_column(String(3))
    pbct_sn: Mapped[str | None] = mapped_column(String(5))

    case_number: Mapped[str | None] = mapped_column(String(100))
    court_name: Mapped[str | None] = mapped_column(String(100))

    title: Mapped[str | None] = mapped_column(String(1000))

    pbct_stat_cd: Mapped[str | None] = mapped_column(String(4))
    pbct_stat_nm: Mapped[str | None] = mapped_column(String(100))
    prpt_div_cd: Mapped[str | None] = mapped_column(String(4))
    prpt_div_nm: Mapped[str | None] = mapped_column(String(100))
    dsps_mthod_cd: Mapped[str | None] = mapped_column(String(4))
    dsps_mthod_nm: Mapped[str | None] = mapped_column(String(100))
    bid_div_cd: Mapped[str | None] = mapped_column(String(4))
    bid_div_nm: Mapped[str | None] = mapped_column(String(100))
    bid_mthod_cd: Mapped[str | None] = mapped_column(String(4))
    bid_mthod_nm: Mapped[str | None] = mapped_column(String(100))
    cptn_mthod_cd: Mapped[str | None] = mapped_column(String(4))
    cptn_mthod_nm: Mapped[str | None] = mapped_column(String(100))
    totalamt_unpc_div_cd: Mapped[str | None] = mapped_column(String(4))
    totalamt_unpc_div_nm: Mapped[str | None] = mapped_column(String(100))

    usg_lcls_id: Mapped[str | None] = mapped_column(String(20))
    usg_lcls_nm: Mapped[str | None] = mapped_column(String(100))
    usg_mcls_id: Mapped[str | None] = mapped_column(String(20))
    usg_mcls_nm: Mapped[str | None] = mapped_column(String(100))
    usg_scls_id: Mapped[str | None] = mapped_column(String(20))
    usg_scls_nm: Mapped[str | None] = mapped_column(String(100))

    ltno_pnu: Mapped[str | None] = mapped_column(String(19))
    rdnm_pnu: Mapped[str | None] = mapped_column(String(25))
    region_sido: Mapped[str | None] = mapped_column(String(100))
    region_sigungu: Mapped[str | None] = mapped_column(String(100))
    region_emd: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)

    location: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )

    appraisal_price: Mapped[int | None] = mapped_column(BigInteger)
    min_bid_price: Mapped[int | None] = mapped_column(BigInteger)
    min_bid_price_text: Mapped[str | None] = mapped_column(String(100))
    first_bid_price: Mapped[int | None] = mapped_column(BigInteger)
    apsl_lowst_ratio: Mapped[float | None] = mapped_column(Numeric(12, 6))
    frst_lowst_ratio: Mapped[float | None] = mapped_column(Numeric(12, 6))
    fee_rate: Mapped[float | None] = mapped_column(Numeric(8, 4))

    bid_begin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bid_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    progress_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pvct_trgt_yn: Mapped[bool | None] = mapped_column(Boolean)
    batc_bid_yn: Mapped[bool | None] = mapped_column(Boolean)

    elec_grpr_use_yn: Mapped[bool | None] = mapped_column(Boolean)
    collb_bid_psbl_yn: Mapped[bool | None] = mapped_column(Boolean)
    twtm_gthr_bid_psbl_yn: Mapped[bool | None] = mapped_column(Boolean)
    subt_bid_psbl_yn: Mapped[bool | None] = mapped_column(Boolean)

    request_org_nm: Mapped[str | None] = mapped_column(String(200))
    announce_org_nm: Mapped[str | None] = mapped_column(String(200))

    rent_method_nm: Mapped[str | None] = mapped_column(String(100))
    rent_period_text: Mapped[str | None] = mapped_column(String(100))

    evc_rsby_target: Mapped[str | None] = mapped_column(String(400))
    dtbt_rqr_edtm: Mapped[str | None] = mapped_column(String(4000))
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    image_urls: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    correction_yn: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    raw: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    realty: Mapped["AuctionRealtyDetailsORM | None"] = relationship(
        back_populates="auction", uselist=False, cascade="all, delete-orphan"
    )
    vehicle: Mapped["AuctionVehicleDetailsORM | None"] = relationship(
        back_populates="auction", uselist=False, cascade="all, delete-orphan"
    )
    movable: Mapped["AuctionMovableDetailsORM | None"] = relationship(
        back_populates="auction", uselist=False, cascade="all, delete-orphan"
    )


class AuctionRealtyDetailsORM(Base):
    __tablename__ = "auction_realty_details"

    auction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auctions.id", ondelete="CASCADE"), primary_key=True
    )
    property_category: Mapped[PropertyCategory] = mapped_column(
        _pg_enum(PropertyCategory, "property_category"),
        nullable=False, server_default="etc",
    )
    land_sqms: Mapped[float | None] = mapped_column(Numeric(18, 4))
    bld_sqms: Mapped[float | None] = mapped_column(Numeric(18, 4))
    alc_yn: Mapped[bool | None] = mapped_column(Boolean)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    auction: Mapped[AuctionORM] = relationship(back_populates="realty")


class AuctionVehicleDetailsORM(Base):
    __tablename__ = "auction_vehicle_details"

    auction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auctions.id", ondelete="CASCADE"), primary_key=True
    )
    vehicle_category: Mapped[VehicleCategory] = mapped_column(
        _pg_enum(VehicleCategory, "vehicle_category"),
        nullable=False, server_default="etc",
    )
    maker: Mapped[str | None] = mapped_column(String(200))
    vehicle_kind: Mapped[str | None] = mapped_column(String(500))
    model_name: Mapped[str | None] = mapped_column(String(500))
    year_model: Mapped[str | None] = mapped_column(CHAR(4))
    plate_no: Mapped[str | None] = mapped_column(String(2000))
    mileage_km: Mapped[int | None] = mapped_column(BigInteger)
    displacement_cc: Mapped[int | None] = mapped_column(BigInteger)
    transmission: Mapped[str | None] = mapped_column(String(500))
    fuel: Mapped[str | None] = mapped_column(String(200))
    color: Mapped[str | None] = mapped_column(String(100))
    quantity_text: Mapped[str | None] = mapped_column(String(100))
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    auction: Mapped[AuctionORM] = relationship(back_populates="vehicle")


class AuctionMovableDetailsORM(Base):
    __tablename__ = "auction_movable_details"

    auction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auctions.id", ondelete="CASCADE"), primary_key=True
    )
    maker: Mapped[str | None] = mapped_column(String(200))
    model_name: Mapped[str | None] = mapped_column(String(100))
    manufacture_year: Mapped[str | None] = mapped_column(CHAR(4))
    quantity_text: Mapped[str | None] = mapped_column(String(100))
    production_place: Mapped[str | None] = mapped_column(String(200))
    use_period_year: Mapped[float | None] = mapped_column(Numeric(18, 4))
    size_text: Mapped[str | None] = mapped_column(String(200))
    weight_text: Mapped[str | None] = mapped_column(String(200))
    custody_place: Mapped[str | None] = mapped_column(String(500))
    author_name: Mapped[str | None] = mapped_column(String(300))
    membership_name: Mapped[str | None] = mapped_column(String(200))
    membership_section_text: Mapped[str | None] = mapped_column(String(2000))
    commodity_name: Mapped[str | None] = mapped_column(String(500))
    property_name: Mapped[str | None] = mapped_column(String(500))
    product_name: Mapped[str | None] = mapped_column(String(500))
    supplier_item_name: Mapped[str | None] = mapped_column(String(500))
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    auction: Mapped[AuctionORM] = relationship(back_populates="movable")


class AuctionRightsAnalysisORM(Base):
    __tablename__ = "auction_rights_analysis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    auction_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auctions.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    summary: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[int | None] = mapped_column(Integer)
    rights_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
