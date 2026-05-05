from geoalchemy2.functions import ST_Intersects, ST_MakeEnvelope, ST_X, ST_Y
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.domain.auction.repository import AuctionRepository
from app.domain.auction.schemas import (
    PROPERTY_CATEGORY_LABELS_KO,
    AuctionDetail,
    AuctionListItem,
    AuctionSource,
    AuctionStatsResponse,
    AuctionStatus,
    AuctionUpsertItem,
    CategoryStat,
    PropertyCategory,
    RightsAnalysisSummary,
    SourceStat,
)
from app.infrastructure.db.models import AuctionORM, AuctionRightsAnalysisORM


_ACTIVE_STATUSES = (AuctionStatus.SCHEDULED.value, AuctionStatus.ONGOING.value)


class DBAuctionRepository(AuctionRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_stats(self) -> AuctionStatsResponse:
        async with self._session_factory() as session:
            cat_rows = await session.execute(
                select(AuctionORM.category, func.count())
                .where(AuctionORM.status.in_(_ACTIVE_STATUSES))
                .group_by(AuctionORM.category)
            )
            cat_counts: dict[PropertyCategory, int] = {
                row[0]: row[1] for row in cat_rows.all()
            }

            src_rows = await session.execute(
                select(AuctionORM.source, func.count())
                .where(AuctionORM.status.in_(_ACTIVE_STATUSES))
                .group_by(AuctionORM.source)
            )
            src_counts: dict[AuctionSource, int] = {
                row[0]: row[1] for row in src_rows.all()
            }

        categories = [
            CategoryStat(
                key=cat,
                label=PROPERTY_CATEGORY_LABELS_KO[cat],
                count=cat_counts.get(cat, 0),
            )
            for cat in PropertyCategory
        ]
        by_source = [
            SourceStat(source=src, count=src_counts.get(src, 0))
            for src in AuctionSource
        ]
        total = sum(src_counts.values())
        return AuctionStatsResponse(
            total=total, categories=categories, by_source=by_source
        )

    async def get_in_bbox(
        self,
        min_lng: float,
        min_lat: float,
        max_lng: float,
        max_lat: float,
        category: PropertyCategory | None = None,
        status: AuctionStatus | None = None,
        limit: int = 200,
    ) -> list[AuctionListItem]:
        envelope = ST_MakeEnvelope(min_lng, min_lat, max_lng, max_lat, 4326)

        stmt = (
            select(
                AuctionORM.id,
                AuctionORM.source,
                AuctionORM.category,
                AuctionORM.status,
                AuctionORM.title,
                AuctionORM.address,
                AuctionORM.minimum_bid_price,
                AuctionORM.appraisal_price,
                AuctionORM.auction_date,
                ST_X(AuctionORM.location).label("lng"),
                ST_Y(AuctionORM.location).label("lat"),
            )
            .where(
                AuctionORM.location.is_not(None),
                ST_Intersects(AuctionORM.location, envelope),
            )
            .order_by(AuctionORM.auction_date.asc().nullslast())
            .limit(limit)
        )

        if category is not None:
            stmt = stmt.where(AuctionORM.category == category.value)
        if status is not None:
            stmt = stmt.where(AuctionORM.status == status.value)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            AuctionListItem(
                id=r.id,
                source=r.source,
                category=r.category,
                status=r.status,
                title=r.title,
                address=r.address,
                lat=float(r.lat),
                lng=float(r.lng),
                minimum_bid_price=r.minimum_bid_price,
                appraisal_price=r.appraisal_price,
                auction_date=r.auction_date,
            )
            for r in rows
        ]

    async def get_by_id(self, auction_id: int) -> AuctionDetail | None:
        stmt = (
            select(
                AuctionORM,
                ST_X(AuctionORM.location).label("lng"),
                ST_Y(AuctionORM.location).label("lat"),
                AuctionRightsAnalysisORM.summary,
                AuctionRightsAnalysisORM.risk_level,
                AuctionRightsAnalysisORM.rights_data,
            )
            .outerjoin(
                AuctionRightsAnalysisORM,
                AuctionRightsAnalysisORM.auction_id == AuctionORM.id,
            )
            .where(AuctionORM.id == auction_id)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            row = result.first()

        if row is None:
            return None

        a: AuctionORM = row[0]
        rights = None
        if row.summary is not None or row.risk_level is not None or row.rights_data:
            rights = RightsAnalysisSummary(
                summary=row.summary,
                risk_level=row.risk_level,
                rights_data=row.rights_data or {},
            )

        return AuctionDetail(
            id=a.id,
            source=a.source,
            external_id=a.external_id,
            case_number=a.case_number,
            category=a.category,
            status=a.status,
            title=a.title,
            address=a.address,
            address_detail=a.address_detail,
            region_sido=a.region_sido,
            region_sigungu=a.region_sigungu,
            lat=float(row.lat) if row.lat is not None else None,
            lng=float(row.lng) if row.lng is not None else None,
            appraisal_price=a.appraisal_price,
            minimum_bid_price=a.minimum_bid_price,
            bid_deposit=a.bid_deposit,
            auction_date=a.auction_date,
            failed_count=a.failed_count,
            court_name=a.court_name,
            agency_name=a.agency_name,
            description=a.description,
            rights_analysis=rights,
        )

    async def upsert_many(
        self, items: list[AuctionUpsertItem]
    ) -> tuple[int, int]:
        if not items:
            return (0, 0)

        async with self._session_factory() as session:
            keys = [(i.source.value, i.external_id) for i in items]
            existing_rows = await session.execute(
                select(AuctionORM.source, AuctionORM.external_id).where(
                    tuple_(AuctionORM.source, AuctionORM.external_id).in_(keys)
                )
            )
            existing_set: set[tuple[str, str]] = set()
            for r in existing_rows.all():
                src_val = r.source.value if hasattr(r.source, "value") else r.source
                existing_set.add((src_val, r.external_id))

            rows = [self._to_row(i) for i in items]
            stmt = pg_insert(AuctionORM).values(rows)
            update_cols = {
                c.name: stmt.excluded[c.name]
                for c in AuctionORM.__table__.columns
                if c.name not in ("id", "source", "external_id", "created_at")
            }
            stmt = stmt.on_conflict_do_update(
                constraint="uq_auctions_source_external",
                set_=update_cols,
            )
            await session.execute(stmt)
            await session.commit()

        inserted = sum(
            1
            for i in items
            if (i.source.value, i.external_id) not in existing_set
        )
        updated = len(items) - inserted
        return (inserted, updated)

    @staticmethod
    def _to_row(item: AuctionUpsertItem) -> dict:
        location_val = None
        if item.lng is not None and item.lat is not None:
            location_val = func.ST_SetSRID(
                func.ST_MakePoint(item.lng, item.lat), 4326
            )

        return {
            "source": item.source.value,
            "external_id": item.external_id,
            "case_number": item.case_number,
            "category": item.category.value,
            "status": item.status.value,
            "title": item.title,
            "address": item.address,
            "address_detail": item.address_detail,
            "region_sido": item.region_sido,
            "region_sigungu": item.region_sigungu,
            "location": location_val,
            "appraisal_price": item.appraisal_price,
            "minimum_bid_price": item.minimum_bid_price,
            "bid_deposit": item.bid_deposit,
            "auction_date": item.auction_date,
            "failed_count": item.failed_count,
            "court_name": item.court_name,
            "agency_name": item.agency_name,
            "description": item.description,
            "metadata": item.raw,
            "crawled_at": func.now(),
        }
