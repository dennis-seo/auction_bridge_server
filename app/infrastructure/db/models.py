from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.auction.schemas import (
    AuctionSource,
    AuctionStatus,
    PropertyCategory,
)


class Base(DeclarativeBase):
    pass


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    """기존 Postgres ENUM 타입 재사용 — DDL은 schema.sql이 이미 만들었으므로 create_type=False."""
    return SAEnum(
        enum_cls,
        name=name,
        create_type=False,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
    )


class AuctionORM(Base):
    __tablename__ = "auctions"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_auctions_source_external"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    source: Mapped[AuctionSource] = mapped_column(
        _pg_enum(AuctionSource, "auction_source"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    case_number: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[PropertyCategory] = mapped_column(
        _pg_enum(PropertyCategory, "property_category"), nullable=False
    )
    status: Mapped[AuctionStatus] = mapped_column(
        _pg_enum(AuctionStatus, "auction_status"),
        nullable=False,
        server_default="scheduled",
    )

    title: Mapped[str | None] = mapped_column(String(500))
    address: Mapped[str] = mapped_column(Text, nullable=False)
    address_detail: Mapped[str | None] = mapped_column(Text)
    region_sido: Mapped[str | None] = mapped_column(String(40))
    region_sigungu: Mapped[str | None] = mapped_column(String(80))

    # PostGIS Point (lon, lat) - WGS84
    location: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )

    appraisal_price: Mapped[int | None] = mapped_column(BigInteger)
    minimum_bid_price: Mapped[int | None] = mapped_column(BigInteger)
    bid_deposit: Mapped[int | None] = mapped_column(BigInteger)
    auction_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    court_name: Mapped[str | None] = mapped_column(String(100))
    agency_name: Mapped[str | None] = mapped_column(String(100))

    description: Mapped[str | None] = mapped_column(Text)
    # 'metadata' is reserved on DeclarativeBase — Python attribute is `extra`,
    # but the actual DB column name stays 'metadata'.
    extra: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuctionRightsAnalysisORM(Base):
    __tablename__ = "auction_rights_analysis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    auction_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
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
