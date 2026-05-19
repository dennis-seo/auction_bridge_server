"""DB 기반 AuctionRepository 구현 (차세대 v2 스키마 기준)."""
from __future__ import annotations

from typing import Any

from geoalchemy2.functions import ST_Intersects, ST_MakeEnvelope, ST_X, ST_Y
from sqlalchemy import String, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.auction.repository import (
    AuctionRepository,
    AuctionSiblingMeta,
    PbancEnrichGroup,
    PbancResolveTarget,
)
from app.domain.auction.schemas import (
    ASSET_TYPE_LABELS_KO,
    PROPERTY_CATEGORY_LABELS_KO,
    VEHICLE_CATEGORY_LABELS_KO,
    AssetGroupStat,
    AssetType,
    AuctionBidOptions,
    AuctionCodeNames,
    AuctionDetail,
    AuctionListItem,
    AuctionSource,
    AuctionStatsResponse,
    AuctionStatus,
    AuctionUpsertItem,
    CategorySubStat,
    MovableDetails,
    PropertyCategory,
    RealtyDetails,
    RightsAnalysisSummary,
    SourceStat,
    VehicleCategory,
    VehicleDetails,
    VehicleFacetCount,
    VehicleListItem,
    VehicleListQuery,
    VehicleMakerCount,
    VehicleStatsResponse,
    VehicleYearBucket,
)
from app.infrastructure.db.models import (
    AuctionBidResultORM,
    AuctionMovableDetailsORM,
    AuctionORM,
    AuctionRealtyDetailsORM,
    AuctionRightsAnalysisORM,
    AuctionVehicleDetailsORM,
)


_ACTIVE_STATUSES = (AuctionStatus.SCHEDULED.value, AuctionStatus.ONGOING.value)


class DBAuctionRepository(AuctionRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # ---------- stats ----------
    async def get_stats(self) -> AuctionStatsResponse:
        async with self._session_factory() as session:
            asset_rows = await session.execute(
                select(AuctionORM.asset_type, func.count())
                .where(AuctionORM.status.in_(_ACTIVE_STATUSES))
                .group_by(AuctionORM.asset_type)
            )
            asset_counts: dict[AssetType, int] = {
                row[0]: row[1] for row in asset_rows.all()
            }

            src_rows = await session.execute(
                select(AuctionORM.source, func.count())
                .where(AuctionORM.status.in_(_ACTIVE_STATUSES))
                .group_by(AuctionORM.source)
            )
            src_counts: dict[AuctionSource, int] = {
                row[0]: row[1] for row in src_rows.all()
            }

            realty_cat_rows = await session.execute(
                select(AuctionRealtyDetailsORM.property_category, func.count())
                .join(AuctionORM, AuctionORM.id == AuctionRealtyDetailsORM.auction_id)
                .where(AuctionORM.status.in_(_ACTIVE_STATUSES))
                .group_by(AuctionRealtyDetailsORM.property_category)
            )
            realty_cat_counts: dict[PropertyCategory, int] = {
                row[0]: row[1] for row in realty_cat_rows.all()
            }

            vehicle_cat_rows = await session.execute(
                select(AuctionVehicleDetailsORM.vehicle_category, func.count())
                .join(AuctionORM, AuctionORM.id == AuctionVehicleDetailsORM.auction_id)
                .where(AuctionORM.status.in_(_ACTIVE_STATUSES))
                .group_by(AuctionVehicleDetailsORM.vehicle_category)
            )
            vehicle_cat_counts: dict[VehicleCategory, int] = {
                row[0]: row[1] for row in vehicle_cat_rows.all()
            }

        groups = [
            AssetGroupStat(
                asset_type=AssetType.REALTY,
                label=ASSET_TYPE_LABELS_KO[AssetType.REALTY],
                total=asset_counts.get(AssetType.REALTY, 0),
                categories=[
                    CategorySubStat(
                        key=cat.value,
                        label=PROPERTY_CATEGORY_LABELS_KO[cat],
                        count=realty_cat_counts.get(cat, 0),
                    )
                    for cat in PropertyCategory
                ],
            ),
            AssetGroupStat(
                asset_type=AssetType.VEHICLE,
                label=ASSET_TYPE_LABELS_KO[AssetType.VEHICLE],
                total=asset_counts.get(AssetType.VEHICLE, 0),
                categories=[
                    CategorySubStat(
                        key=cat.value,
                        label=VEHICLE_CATEGORY_LABELS_KO[cat],
                        count=vehicle_cat_counts.get(cat, 0),
                    )
                    for cat in VehicleCategory
                ],
            ),
            AssetGroupStat(
                asset_type=AssetType.MOVABLE,
                label=ASSET_TYPE_LABELS_KO[AssetType.MOVABLE],
                total=asset_counts.get(AssetType.MOVABLE, 0),
                categories=[],
            ),
        ]
        by_source = [
            SourceStat(source=src, count=src_counts.get(src, 0))
            for src in AuctionSource
        ]
        total = sum(asset_counts.values())
        return AuctionStatsResponse(total=total, groups=groups, by_source=by_source)

    # ---------- map / list ----------
    async def get_in_bbox(
        self,
        min_lng: float,
        min_lat: float,
        max_lng: float,
        max_lat: float,
        asset_type: AssetType | None = None,
        property_category: PropertyCategory | None = None,
        vehicle_category: VehicleCategory | None = None,
        status: AuctionStatus | None = None,
        limit: int = 200,
    ) -> list[AuctionListItem]:
        envelope = ST_MakeEnvelope(min_lng, min_lat, max_lng, max_lat, 4326)

        # 같은 물건(cltr_mng_no)의 여러 회차/차수 중 "대표 회차" 1건만 노출.
        # 우선순위: ongoing → scheduled → sold → failed → cancelled.
        # 동률 시 bid_end_at이 가장 임박한 회차를 선택.
        status_priority = case(
            (AuctionORM.status == AuctionStatus.ONGOING.value, 1),
            (AuctionORM.status == AuctionStatus.SCHEDULED.value, 2),
            (AuctionORM.status == AuctionStatus.SOLD.value, 3),
            (AuctionORM.status == AuctionStatus.FAILED.value, 4),
            (AuctionORM.status == AuctionStatus.CANCELLED.value, 5),
            else_=99,
        )
        dedup_key = func.coalesce(
            AuctionORM.cltr_mng_no,
            AuctionORM.case_number,
            func.cast(AuctionORM.id, String),
        )

        inner = (
            select(
                AuctionORM.id.label("id"),
                AuctionORM.source.label("source"),
                AuctionORM.asset_type.label("asset_type"),
                AuctionORM.status.label("status"),
                AuctionORM.title.label("title"),
                AuctionORM.address.label("address"),
                AuctionORM.region_sido.label("region_sido"),
                AuctionORM.region_sigungu.label("region_sigungu"),
                AuctionORM.appraisal_price.label("appraisal_price"),
                AuctionORM.min_bid_price.label("min_bid_price"),
                AuctionORM.bid_end_at.label("bid_end_at"),
                AuctionORM.fee_rate.label("fee_rate"),
                AuctionORM.failed_count.label("failed_count"),
                AuctionORM.thumbnail_url.label("thumbnail_url"),
                ST_X(AuctionORM.location).label("lng"),
                ST_Y(AuctionORM.location).label("lat"),
            )
            .distinct(dedup_key)
            .where(
                AuctionORM.location.is_not(None),
                ST_Intersects(AuctionORM.location, envelope),
            )
        )

        if asset_type is not None:
            inner = inner.where(AuctionORM.asset_type == asset_type.value)
        if status is not None:
            inner = inner.where(AuctionORM.status == status.value)
        if property_category is not None:
            inner = inner.join(
                AuctionRealtyDetailsORM,
                AuctionRealtyDetailsORM.auction_id == AuctionORM.id,
            ).where(
                AuctionRealtyDetailsORM.property_category == property_category.value
            )
        if vehicle_category is not None:
            inner = inner.join(
                AuctionVehicleDetailsORM,
                AuctionVehicleDetailsORM.auction_id == AuctionORM.id,
            ).where(
                AuctionVehicleDetailsORM.vehicle_category == vehicle_category.value
            )

        inner = inner.order_by(
            dedup_key,
            status_priority,
            AuctionORM.bid_end_at.asc().nullslast(),
            AuctionORM.id,
        )
        sub = inner.subquery()

        stmt = (
            select(sub)
            .order_by(sub.c.bid_end_at.asc().nullslast())
            .limit(limit)
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            AuctionListItem(
                id=r.id,
                source=r.source,
                asset_type=r.asset_type,
                status=r.status,
                title=r.title,
                address=r.address,
                region_sido=r.region_sido,
                region_sigungu=r.region_sigungu,
                lat=float(r.lat) if r.lat is not None else None,
                lng=float(r.lng) if r.lng is not None else None,
                appraisal_price=r.appraisal_price,
                min_bid_price=r.min_bid_price,
                bid_end_at=r.bid_end_at,
                fee_rate=float(r.fee_rate) if r.fee_rate is not None else None,
                failed_count=r.failed_count or 0,
                thumbnail_url=r.thumbnail_url,
            )
            for r in rows
        ]

    # ---------- detail ----------
    async def get_by_id(self, auction_id: int) -> AuctionDetail | None:
        stmt = (
            select(
                AuctionORM,
                ST_X(AuctionORM.location).label("lng"),
                ST_Y(AuctionORM.location).label("lat"),
                AuctionRightsAnalysisORM.summary,
                AuctionRightsAnalysisORM.risk_level,
                AuctionRightsAnalysisORM.rights_data,
                AuctionRealtyDetailsORM,
                AuctionVehicleDetailsORM,
                AuctionMovableDetailsORM,
            )
            .outerjoin(
                AuctionRightsAnalysisORM,
                AuctionRightsAnalysisORM.auction_id == AuctionORM.id,
            )
            .outerjoin(
                AuctionRealtyDetailsORM,
                AuctionRealtyDetailsORM.auction_id == AuctionORM.id,
            )
            .outerjoin(
                AuctionVehicleDetailsORM,
                AuctionVehicleDetailsORM.auction_id == AuctionORM.id,
            )
            .outerjoin(
                AuctionMovableDetailsORM,
                AuctionMovableDetailsORM.auction_id == AuctionORM.id,
            )
            .where(AuctionORM.id == auction_id)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            row = result.first()

        if row is None:
            return None

        a: AuctionORM = row[0]
        realty: AuctionRealtyDetailsORM | None = row[6]
        vehicle: AuctionVehicleDetailsORM | None = row[7]
        movable: AuctionMovableDetailsORM | None = row[8]

        rights = None
        if row.summary is not None or row.risk_level is not None or row.rights_data:
            rights = RightsAnalysisSummary(
                summary=row.summary,
                risk_level=row.risk_level,
                rights_data=row.rights_data or {},
            )

        details = None
        if a.asset_type == AssetType.REALTY and realty is not None:
            details = RealtyDetails(
                property_category=realty.property_category,
                land_sqms=float(realty.land_sqms) if realty.land_sqms is not None else None,
                bld_sqms=float(realty.bld_sqms) if realty.bld_sqms is not None else None,
                alc_yn=realty.alc_yn,
            )
        elif a.asset_type == AssetType.VEHICLE and vehicle is not None:
            details = VehicleDetails(
                vehicle_category=vehicle.vehicle_category,
                maker=vehicle.maker,
                vehicle_kind=vehicle.vehicle_kind,
                model_name=vehicle.model_name,
                year_model=vehicle.year_model,
                plate_no=vehicle.plate_no,
                mileage_km=vehicle.mileage_km,
                displacement_cc=vehicle.displacement_cc,
                transmission=vehicle.transmission,
                fuel=vehicle.fuel,
                color=vehicle.color,
                quantity_text=vehicle.quantity_text,
            )
        elif a.asset_type == AssetType.MOVABLE and movable is not None:
            details = MovableDetails(
                maker=movable.maker,
                model_name=movable.model_name,
                manufacture_year=movable.manufacture_year,
                quantity_text=movable.quantity_text,
                production_place=movable.production_place,
                use_period_year=(
                    float(movable.use_period_year)
                    if movable.use_period_year is not None
                    else None
                ),
                size_text=movable.size_text,
                weight_text=movable.weight_text,
                custody_place=movable.custody_place,
                author_name=movable.author_name,
                membership_name=movable.membership_name,
                commodity_name=movable.commodity_name,
                product_name=movable.product_name,
            )

        return AuctionDetail(
            id=a.id,
            source=a.source,
            asset_type=a.asset_type,
            status=a.status,
            title=a.title,
            cltr_mng_no=a.cltr_mng_no,
            pbct_cdtn_no=a.pbct_cdtn_no,
            onbid_cltr_no=a.onbid_cltr_no,
            onbid_pbanc_no=a.onbid_pbanc_no,
            pbct_no=a.pbct_no,
            case_number=a.case_number,
            court_name=a.court_name,
            address=a.address,
            region_sido=a.region_sido,
            region_sigungu=a.region_sigungu,
            region_emd=a.region_emd,
            lat=float(row.lat) if row.lat is not None else None,
            lng=float(row.lng) if row.lng is not None else None,
            appraisal_price=a.appraisal_price,
            min_bid_price=a.min_bid_price,
            min_bid_price_text=a.min_bid_price_text,
            first_bid_price=a.first_bid_price,
            apsl_lowst_ratio=float(a.apsl_lowst_ratio) if a.apsl_lowst_ratio is not None else None,
            frst_lowst_ratio=float(a.frst_lowst_ratio) if a.frst_lowst_ratio is not None else None,
            fee_rate=float(a.fee_rate) if a.fee_rate is not None else None,
            bid_begin_at=a.bid_begin_at,
            bid_end_at=a.bid_end_at,
            failed_count=a.failed_count,
            progress_count=a.progress_count,
            pvct_trgt_yn=a.pvct_trgt_yn,
            code_names=AuctionCodeNames(
                pbct_stat=a.pbct_stat_nm,
                prpt_div=a.prpt_div_nm,
                dsps_mthod=a.dsps_mthod_nm,
                bid_div=a.bid_div_nm,
                bid_mthod=a.bid_mthod_nm,
                cptn_mthod=a.cptn_mthod_nm,
                totalamt_unpc_div=a.totalamt_unpc_div_nm,
                usg_lcls=a.usg_lcls_nm,
                usg_mcls=a.usg_mcls_nm,
                usg_scls=a.usg_scls_nm,
            ),
            bid_options=AuctionBidOptions(
                elec_grpr_use=a.elec_grpr_use_yn,
                collb_bid_psbl=a.collb_bid_psbl_yn,
                twtm_gthr_bid_psbl=a.twtm_gthr_bid_psbl_yn,
                subt_bid_psbl=a.subt_bid_psbl_yn,
            ),
            request_org_nm=a.request_org_nm,
            announce_org_nm=a.announce_org_nm,
            thumbnail_url=a.thumbnail_url,
            image_urls=list(a.image_urls or []),
            evc_rsby_target=a.evc_rsby_target,
            details=details,
            rights_analysis=rights,
        )

    # ---------- ingest upsert ----------
    async def upsert_many(
        self, items: list[AuctionUpsertItem]
    ) -> tuple[int, int]:
        if not items:
            return (0, 0)

        async with self._session_factory() as session:
            # 사전 조회 (insert/update 카운트용)
            keys = [(i.cltr_mng_no, i.pbct_cdtn_no) for i in items]
            existing_rows = await session.execute(
                select(AuctionORM.id, AuctionORM.cltr_mng_no, AuctionORM.pbct_cdtn_no).where(
                    AuctionORM.source == AuctionSource.ONBID.value,
                    AuctionORM.cltr_mng_no.in_({k[0] for k in keys}),
                )
            )
            existing_map: dict[tuple[str, int], int] = {}
            for r in existing_rows.all():
                if r.cltr_mng_no and r.pbct_cdtn_no is not None:
                    existing_map[(r.cltr_mng_no, r.pbct_cdtn_no)] = r.id

            # 1) parent upsert
            parent_rows = [self._to_parent_row(i) for i in items]
            stmt = pg_insert(AuctionORM).values(parent_rows)
            update_cols = {
                c.name: stmt.excluded[c.name]
                for c in AuctionORM.__table__.columns
                if c.name not in ("id", "source", "cltr_mng_no", "pbct_cdtn_no", "created_at", "raw")
            }
            update_cols["raw"] = stmt.excluded.raw
            # 신규 페치는 image_urls가 늘 빈 [] — 별도 enrich로 채워둔 사진을 덮지 않도록
            # 새 값이 비어있을 때만 기존 값을 유지한다.
            update_cols["image_urls"] = case(
                (
                    func.jsonb_array_length(stmt.excluded.image_urls) > 0,
                    stmt.excluded.image_urls,
                ),
                else_=AuctionORM.image_urls,
            )
            # realty list ingest는 pbanc_mng_no를 모르므로 늘 NULL. 별도 enrich로
            # 해결된 매핑이 NULL로 덮이지 않도록 NULL-safe coalesce.
            update_cols["pbanc_mng_no"] = func.coalesce(
                stmt.excluded.pbanc_mng_no, AuctionORM.pbanc_mng_no,
            )
            # 회차(scdul) 가드: (cltr_mng_no, pbct_cdtn_no) 동일하지만 더 늦은
            # 회차가 들어와 진행 중인 이른 회차의 일정/금액을 덮어쓰는 것을 방지.
            # 기존 bid_end_at이 미래이고 들어오는 값이 더 늦은 시점이면 기존 유지.
            schedule_guard = or_(
                AuctionORM.bid_end_at.is_(None),
                AuctionORM.bid_end_at <= func.now(),
                stmt.excluded.bid_end_at.is_(None),
                stmt.excluded.bid_end_at <= AuctionORM.bid_end_at,
            )
            guarded_cols = (
                "min_bid_price",
                "min_bid_price_text",
                "first_bid_price",
                "apsl_lowst_ratio",
                "frst_lowst_ratio",
                "bid_begin_at",
                "bid_end_at",
                "failed_count",
                "progress_count",
                "status",
            )
            for col_name in guarded_cols:
                if col_name in update_cols:
                    update_cols[col_name] = case(
                        (schedule_guard, stmt.excluded[col_name]),
                        else_=getattr(AuctionORM, col_name),
                    )
            stmt = stmt.on_conflict_do_update(
                index_elements=["cltr_mng_no", "pbct_cdtn_no"],
                index_where=AuctionORM.source == AuctionSource.ONBID.value,
                set_=update_cols,
            ).returning(AuctionORM.id, AuctionORM.cltr_mng_no, AuctionORM.pbct_cdtn_no)

            result = await session.execute(stmt)
            parent_id_map: dict[tuple[str, int], int] = {}
            for r in result.all():
                parent_id_map[(r.cltr_mng_no, r.pbct_cdtn_no)] = r.id

            # 2) detail upsert (asset_type별 분기)
            realty_rows: list[dict[str, Any]] = []
            vehicle_rows: list[dict[str, Any]] = []
            movable_rows: list[dict[str, Any]] = []
            for i in items:
                aid = parent_id_map.get((i.cltr_mng_no, i.pbct_cdtn_no))
                if aid is None:
                    continue
                if i.realty is not None:
                    realty_rows.append({
                        "auction_id": aid,
                        "property_category": i.realty.property_category.value,
                        "land_sqms": i.realty.land_sqms,
                        "bld_sqms": i.realty.bld_sqms,
                        "alc_yn": i.realty.alc_yn,
                    })
                if i.vehicle is not None:
                    vehicle_rows.append({
                        "auction_id": aid,
                        "vehicle_category": i.vehicle.vehicle_category.value,
                        "maker": i.vehicle.maker,
                        "vehicle_kind": i.vehicle.vehicle_kind,
                        "model_name": i.vehicle.model_name,
                        "year_model": i.vehicle.year_model,
                        "plate_no": i.vehicle.plate_no,
                        "mileage_km": i.vehicle.mileage_km,
                        "displacement_cc": i.vehicle.displacement_cc,
                        "transmission": i.vehicle.transmission,
                        "fuel": i.vehicle.fuel,
                        "color": i.vehicle.color,
                        "quantity_text": i.vehicle.quantity_text,
                    })
                if i.movable is not None:
                    movable_rows.append({
                        "auction_id": aid,
                        "maker": i.movable.maker,
                        "model_name": i.movable.model_name,
                        "manufacture_year": i.movable.manufacture_year,
                        "quantity_text": i.movable.quantity_text,
                        "production_place": i.movable.production_place,
                        "use_period_year": i.movable.use_period_year,
                        "size_text": i.movable.size_text,
                        "weight_text": i.movable.weight_text,
                        "custody_place": i.movable.custody_place,
                        "author_name": i.movable.author_name,
                        "membership_name": i.movable.membership_name,
                        "membership_section_text": i.movable.membership_section_text,
                        "commodity_name": i.movable.commodity_name,
                        "property_name": i.movable.property_name,
                        "product_name": i.movable.product_name,
                        "supplier_item_name": i.movable.supplier_item_name,
                    })

            await self._upsert_details(session, AuctionRealtyDetailsORM, realty_rows)
            await self._upsert_details(session, AuctionVehicleDetailsORM, vehicle_rows)
            await self._upsert_details(session, AuctionMovableDetailsORM, movable_rows)

            await session.commit()

        inserted = sum(
            1 for i in items if (i.cltr_mng_no, i.pbct_cdtn_no) not in existing_map
        )
        updated = len(items) - inserted
        return (inserted, updated)

    # ---------- image enrichment ----------
    async def list_realty_missing_images(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        return await self._list_missing_images(AssetType.REALTY, limit)

    async def list_movable_missing_images(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        return await self._list_missing_images(AssetType.MOVABLE, limit)

    async def _list_missing_images(
        self, asset_type: AssetType, limit: int
    ) -> list[tuple[int, str, int]]:
        async with self._session_factory() as session:
            rows = (await session.execute(
                select(AuctionORM.id, AuctionORM.cltr_mng_no, AuctionORM.pbct_cdtn_no)
                .where(
                    AuctionORM.asset_type == asset_type.value,
                    AuctionORM.cltr_mng_no.is_not(None),
                    AuctionORM.pbct_cdtn_no.is_not(None),
                    func.jsonb_array_length(AuctionORM.image_urls) == 0,
                )
                .order_by(AuctionORM.id)
                .limit(limit)
            )).all()
        return [(r.id, r.cltr_mng_no, r.pbct_cdtn_no) for r in rows]

    async def lookup_active_auction_ids(
        self, keys: list[tuple[str, int]]
    ) -> dict[tuple[str, int], int]:
        if not keys:
            return {}
        cltr_set = {k[0] for k in keys}
        pbct_set = {k[1] for k in keys}
        async with self._session_factory() as session:
            rows = (await session.execute(
                select(
                    AuctionORM.id, AuctionORM.cltr_mng_no, AuctionORM.pbct_cdtn_no,
                )
                .where(
                    AuctionORM.source == AuctionSource.ONBID.value,
                    AuctionORM.status.in_(_ACTIVE_STATUSES),
                    AuctionORM.cltr_mng_no.in_(cltr_set),
                    AuctionORM.pbct_cdtn_no.in_(pbct_set),
                )
            )).all()
        # DB 후보 중 정확한 (cltr, pbct) 짝만 채택
        wanted = set(keys)
        out: dict[tuple[str, int], int] = {}
        for r in rows:
            key = (r.cltr_mng_no, r.pbct_cdtn_no)
            if key in wanted:
                out[key] = r.id
        return out

    async def update_image_urls(
        self, auction_id: int, image_urls: list[str]
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(AuctionORM)
                .where(AuctionORM.id == auction_id)
                .values(image_urls=image_urls)
            )
            await session.commit()

    # ---------- pbanc enrichment (D안 — 누락 회차 보강) ----------
    async def list_auctions_missing_pbanc_mng_no(
        self, limit: int,
    ) -> list[PbancResolveTarget]:
        async with self._session_factory() as session:
            rows = (await session.execute(
                select(
                    AuctionORM.id,
                    AuctionORM.onbid_pbanc_no,
                    AuctionORM.asset_type,
                    AuctionORM.bid_begin_at,
                )
                .where(
                    AuctionORM.source == AuctionSource.ONBID.value,
                    AuctionORM.status.in_(_ACTIVE_STATUSES),
                    AuctionORM.onbid_pbanc_no.is_not(None),
                    AuctionORM.pbanc_mng_no.is_(None),
                )
                .order_by(AuctionORM.id)
                .limit(limit)
            )).all()
        return [
            PbancResolveTarget(
                auction_id=r.id,
                onbid_pbanc_no=int(r.onbid_pbanc_no),
                asset_type=AssetType(r.asset_type) if isinstance(r.asset_type, str) else r.asset_type,
                bid_begin_at=r.bid_begin_at,
            )
            for r in rows
        ]

    async def update_pbanc_mng_no_batch(
        self, mapping: list[tuple[int, str]],
    ) -> int:
        if not mapping:
            return 0
        async with self._session_factory() as session:
            count = 0
            for auction_id, pbanc_mng_no in mapping:
                res = await session.execute(
                    update(AuctionORM)
                    .where(AuctionORM.id == auction_id)
                    .values(pbanc_mng_no=pbanc_mng_no)
                )
                count += res.rowcount or 0
            await session.commit()
        return count

    async def list_pbanc_groups_for_round_enrich(
        self, limit: int,
    ) -> list[PbancEnrichGroup]:
        # 1) limit개의 distinct pbanc_mng_no 선정 (active onbid)
        async with self._session_factory() as session:
            pbanc_rows = (await session.execute(
                select(AuctionORM.pbanc_mng_no)
                .where(
                    AuctionORM.source == AuctionSource.ONBID.value,
                    AuctionORM.status.in_(_ACTIVE_STATUSES),
                    AuctionORM.pbanc_mng_no.is_not(None),
                )
                .group_by(AuctionORM.pbanc_mng_no)
                .order_by(AuctionORM.pbanc_mng_no)
                .limit(limit)
            )).all()
            pbanc_set = [r.pbanc_mng_no for r in pbanc_rows]
            if not pbanc_set:
                return []

            # 2) 해당 공고들의 모든 row + realty.property_category join
            detail_rows = (await session.execute(
                select(
                    AuctionORM.pbanc_mng_no,
                    AuctionORM.cltr_mng_no,
                    AuctionORM.pbct_cdtn_no,
                    AuctionORM.asset_type,
                    AuctionORM.region_sido,
                    AuctionORM.region_sigungu,
                    AuctionORM.region_emd,
                    AuctionORM.address,
                    ST_X(AuctionORM.location).label("lng"),
                    ST_Y(AuctionORM.location).label("lat"),
                    AuctionORM.ltno_pnu,
                    AuctionORM.rdnm_pnu,
                    AuctionORM.request_org_nm,
                    AuctionORM.announce_org_nm,
                    AuctionORM.thumbnail_url,
                    AuctionRealtyDetailsORM.property_category,
                )
                .outerjoin(
                    AuctionRealtyDetailsORM,
                    AuctionRealtyDetailsORM.auction_id == AuctionORM.id,
                )
                .where(
                    AuctionORM.source == AuctionSource.ONBID.value,
                    AuctionORM.pbanc_mng_no.in_(pbanc_set),
                )
            )).all()

        # 3) Python에서 그룹핑
        groups: dict[str, PbancEnrichGroup] = {
            p: PbancEnrichGroup(pbanc_mng_no=p) for p in pbanc_set
        }
        for r in detail_rows:
            g = groups[r.pbanc_mng_no]
            cltr = r.cltr_mng_no
            if cltr and r.pbct_cdtn_no is not None:
                g.existing_keys.add((cltr, int(r.pbct_cdtn_no)))
            if cltr and cltr not in g.siblings:
                asset_type = (
                    AssetType(r.asset_type) if isinstance(r.asset_type, str)
                    else r.asset_type
                )
                prop_cat = (
                    PropertyCategory(r.property_category)
                    if isinstance(r.property_category, str)
                    else r.property_category
                )
                g.siblings[cltr] = AuctionSiblingMeta(
                    asset_type=asset_type,
                    region_sido=r.region_sido,
                    region_sigungu=r.region_sigungu,
                    region_emd=r.region_emd,
                    address=r.address,
                    lat=float(r.lat) if r.lat is not None else None,
                    lng=float(r.lng) if r.lng is not None else None,
                    ltno_pnu=r.ltno_pnu,
                    rdnm_pnu=r.rdnm_pnu,
                    request_org_nm=r.request_org_nm,
                    announce_org_nm=r.announce_org_nm,
                    thumbnail_url=r.thumbnail_url,
                    property_category=prop_cat,
                )
        return list(groups.values())

    async def get_sibling_for_cltr(
        self, cltr_mng_no: str,
    ) -> tuple[AuctionSiblingMeta | None, set[int], str | None]:
        async with self._session_factory() as session:
            rows = (await session.execute(
                select(
                    AuctionORM.pbct_cdtn_no,
                    AuctionORM.pbanc_mng_no,
                    AuctionORM.asset_type,
                    AuctionORM.region_sido,
                    AuctionORM.region_sigungu,
                    AuctionORM.region_emd,
                    AuctionORM.address,
                    ST_X(AuctionORM.location).label("lng"),
                    ST_Y(AuctionORM.location).label("lat"),
                    AuctionORM.ltno_pnu,
                    AuctionORM.rdnm_pnu,
                    AuctionORM.request_org_nm,
                    AuctionORM.announce_org_nm,
                    AuctionORM.thumbnail_url,
                    AuctionRealtyDetailsORM.property_category,
                )
                .outerjoin(
                    AuctionRealtyDetailsORM,
                    AuctionRealtyDetailsORM.auction_id == AuctionORM.id,
                )
                .where(
                    AuctionORM.source == AuctionSource.ONBID.value,
                    AuctionORM.cltr_mng_no == cltr_mng_no,
                )
            )).all()

        if not rows:
            return (None, set(), None)

        existing_pbct: set[int] = set()
        pbanc_mng_no: str | None = None
        for r in rows:
            if r.pbct_cdtn_no is not None:
                existing_pbct.add(int(r.pbct_cdtn_no))
            if pbanc_mng_no is None and r.pbanc_mng_no:
                pbanc_mng_no = r.pbanc_mng_no

        r0 = rows[0]
        asset_type = (
            AssetType(r0.asset_type) if isinstance(r0.asset_type, str) else r0.asset_type
        )
        prop_cat = (
            PropertyCategory(r0.property_category)
            if isinstance(r0.property_category, str) else r0.property_category
        )
        sibling = AuctionSiblingMeta(
            asset_type=asset_type,
            region_sido=r0.region_sido,
            region_sigungu=r0.region_sigungu,
            region_emd=r0.region_emd,
            address=r0.address,
            lat=float(r0.lat) if r0.lat is not None else None,
            lng=float(r0.lng) if r0.lng is not None else None,
            ltno_pnu=r0.ltno_pnu,
            rdnm_pnu=r0.rdnm_pnu,
            request_org_nm=r0.request_org_nm,
            announce_org_nm=r0.announce_org_nm,
            thumbnail_url=r0.thumbnail_url,
            property_category=prop_cat,
        )
        return (sibling, existing_pbct, pbanc_mng_no)

    async def list_cltrs_missing_default_round(
        self, limit: int, ratio: float = 0.95,
    ) -> list[str]:
        from sqlalchemy import exists, not_

        async with self._session_factory() as session:
            a2 = AuctionORM.__table__.alias("a2")
            full_price_exists = (
                select(1)
                .select_from(a2)
                .where(
                    a2.c.source == AuctionSource.ONBID.value,
                    a2.c.cltr_mng_no == AuctionORM.cltr_mng_no,
                    a2.c.min_bid_price.is_not(None),
                    a2.c.appraisal_price.is_not(None),
                    a2.c.min_bid_price >= a2.c.appraisal_price * ratio,
                )
                .exists()
            )
            rows = (await session.execute(
                select(AuctionORM.cltr_mng_no)
                .where(
                    AuctionORM.source == AuctionSource.ONBID.value,
                    AuctionORM.status.in_(_ACTIVE_STATUSES),
                    AuctionORM.cltr_mng_no.is_not(None),
                    AuctionORM.appraisal_price.is_not(None),
                    AuctionORM.appraisal_price > 0,
                    AuctionORM.min_bid_price.is_not(None),
                    AuctionORM.min_bid_price < AuctionORM.appraisal_price * ratio,
                    not_(full_price_exists),
                )
                .group_by(AuctionORM.cltr_mng_no)
                .order_by(AuctionORM.cltr_mng_no.desc())
                .limit(limit)
            )).all()
        return [r.cltr_mng_no for r in rows if r.cltr_mng_no]

    # ---------- bid info enrichment (#7) ----------
    async def list_auctions_missing_bid_info(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        """active 매물 중 bid_info가 빈 객체(`{}`)인 N건."""
        async with self._session_factory() as session:
            rows = (await session.execute(
                select(AuctionORM.id, AuctionORM.cltr_mng_no, AuctionORM.pbct_cdtn_no)
                .where(
                    AuctionORM.status.in_(_ACTIVE_STATUSES),
                    AuctionORM.cltr_mng_no.is_not(None),
                    AuctionORM.pbct_cdtn_no.is_not(None),
                    AuctionORM.bid_info == {},
                )
                .order_by(AuctionORM.id)
                .limit(limit)
            )).all()
        return [(r.id, r.cltr_mng_no, r.pbct_cdtn_no) for r in rows]

    async def update_bid_info(
        self, auction_id: int, bid_info: dict
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(AuctionORM)
                .where(AuctionORM.id == auction_id)
                .values(bid_info=bid_info)
            )
            await session.commit()

    # ---------- bid result enrichment ----------
    async def list_auctions_pending_results(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        """bid_end_at < now() 이고 status가 ongoing인 매물 — 결과 보강 대상."""
        from sqlalchemy import outerjoin
        async with self._session_factory() as session:
            rows = (await session.execute(
                select(AuctionORM.id, AuctionORM.cltr_mng_no, AuctionORM.pbct_cdtn_no)
                .outerjoin(
                    AuctionBidResultORM,
                    AuctionBidResultORM.auction_id == AuctionORM.id,
                )
                .where(
                    AuctionORM.cltr_mng_no.is_not(None),
                    AuctionORM.pbct_cdtn_no.is_not(None),
                    AuctionORM.status == AuctionStatus.ONGOING.value,
                    AuctionORM.bid_end_at.is_not(None),
                    AuctionORM.bid_end_at < func.now(),
                    AuctionBidResultORM.id.is_(None),
                )
                .order_by(AuctionORM.bid_end_at.asc())
                .limit(limit)
            )).all()
        return [(r.id, r.cltr_mng_no, r.pbct_cdtn_no) for r in rows]

    async def upsert_bid_result(self, auction_id: int, payload) -> None:
        row = {
            "auction_id": auction_id,
            "cltr_mng_no": payload.cltr_mng_no,
            "pbct_cdtn_no": payload.pbct_cdtn_no,
            "pbct_nsq": payload.pbct_nsq,
            "pbct_sn": payload.pbct_sn,
            "status": payload.status.value,
            "pbct_stat_cd": payload.pbct_stat_cd,
            "pbct_stat_nm": payload.pbct_stat_nm,
            "winning_bid_amount": payload.winning_bid_amount,
            "winning_bid_amounts": payload.winning_bid_amounts,
            "bid_amounts": payload.bid_amounts,
            "apsl_scfb_ratio": payload.apsl_scfb_ratio,
            "lowst_scfb_ratio": payload.lowst_scfb_ratio,
            "valid_bidder_count": payload.valid_bidder_count,
            "invalid_bidder_count": payload.invalid_bidder_count,
            "opbd_at": payload.opbd_at,
            "opbd_begin_at": payload.opbd_begin_at,
            "opbd_end_at": payload.opbd_end_at,
            "afsb_rtrcn_reason": payload.afsb_rtrcn_reason,
            "rtrcn_reason": payload.rtrcn_reason,
            "announce_name": payload.announce_name,
            "announce_mng_no": payload.announce_mng_no,
            "bid_deposit_text": payload.bid_deposit_text,
            "raw": payload.raw,
            "crawled_at": func.now(),
        }
        async with self._session_factory() as session:
            stmt = pg_insert(AuctionBidResultORM).values(row)
            update_cols = {
                c.name: stmt.excluded[c.name]
                for c in AuctionBidResultORM.__table__.columns
                if c.name not in ("id", "auction_id", "created_at")
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["auction_id"], set_=update_cols
            )
            await session.execute(stmt)
            # 결과가 확정 상태면 auctions.status도 갱신
            if payload.status in (
                AuctionStatus.SOLD, AuctionStatus.FAILED, AuctionStatus.CANCELLED,
            ):
                await session.execute(
                    update(AuctionORM)
                    .where(AuctionORM.id == auction_id)
                    .values(
                        status=payload.status.value,
                        pbct_stat_cd=payload.pbct_stat_cd,
                        pbct_stat_nm=payload.pbct_stat_nm,
                    )
                )
            await session.commit()

    # ---------- vehicle list / stats ----------
    async def list_vehicles(
        self, q: VehicleListQuery
    ) -> tuple[list[VehicleListItem], int]:
        v = AuctionVehicleDetailsORM
        a = AuctionORM

        conditions = [a.asset_type == AssetType.VEHICLE.value]
        if q.vehicle_category is not None:
            conditions.append(v.vehicle_category == q.vehicle_category.value)
        if q.maker:
            conditions.append(v.maker.ilike(f"%{q.maker}%"))
        if q.fuel:
            conditions.append(v.fuel.ilike(f"%{q.fuel}%"))
        if q.transmission:
            conditions.append(v.transmission.ilike(f"%{q.transmission}%"))
        if q.year_model_min:
            conditions.append(v.year_model >= q.year_model_min)
        if q.year_model_max:
            conditions.append(v.year_model <= q.year_model_max)
        if q.mileage_km_min is not None:
            conditions.append(v.mileage_km >= q.mileage_km_min)
        if q.mileage_km_max is not None:
            conditions.append(v.mileage_km <= q.mileage_km_max)
        if q.displacement_cc_min is not None:
            conditions.append(v.displacement_cc >= q.displacement_cc_min)
        if q.displacement_cc_max is not None:
            conditions.append(v.displacement_cc <= q.displacement_cc_max)
        if q.status is not None:
            conditions.append(a.status == q.status.value)
        if q.region_sido:
            conditions.append(a.region_sido == q.region_sido)

        list_stmt = (
            select(
                a.id, a.source, a.status, a.title,
                a.region_sido, a.region_sigungu,
                a.appraisal_price, a.min_bid_price,
                a.bid_begin_at, a.bid_end_at, a.fee_rate,
                a.failed_count, a.thumbnail_url,
                v.vehicle_category, v.maker, v.model_name, v.year_model,
                v.mileage_km, v.displacement_cc, v.transmission, v.fuel,
            )
            .join(v, v.auction_id == a.id)
            .where(*conditions)
            .order_by(a.bid_begin_at.desc().nullslast(), a.id.desc())
            .offset(q.offset)
            .limit(q.limit)
        )
        count_stmt = (
            select(func.count())
            .select_from(a)
            .join(v, v.auction_id == a.id)
            .where(*conditions)
        )

        async with self._session_factory() as session:
            rows = (await session.execute(list_stmt)).all()
            total = (await session.execute(count_stmt)).scalar_one()

        items = [
            VehicleListItem(
                id=r.id,
                source=r.source,
                status=r.status,
                title=r.title,
                region_sido=r.region_sido,
                region_sigungu=r.region_sigungu,
                appraisal_price=r.appraisal_price,
                min_bid_price=r.min_bid_price,
                bid_begin_at=r.bid_begin_at,
                bid_end_at=r.bid_end_at,
                fee_rate=float(r.fee_rate) if r.fee_rate is not None else None,
                failed_count=r.failed_count or 0,
                thumbnail_url=r.thumbnail_url,
                vehicle_category=r.vehicle_category,
                maker=r.maker,
                model_name=r.model_name,
                year_model=r.year_model,
                mileage_km=r.mileage_km,
                displacement_cc=r.displacement_cc,
                transmission=r.transmission,
                fuel=r.fuel,
            )
            for r in rows
        ]
        return items, int(total)

    async def get_vehicle_stats(self) -> VehicleStatsResponse:
        v = AuctionVehicleDetailsORM
        a = AuctionORM
        active = a.status.in_(_ACTIVE_STATUSES)
        is_vehicle = a.asset_type == AssetType.VEHICLE.value

        async with self._session_factory() as session:
            total = (await session.execute(
                select(func.count(a.id))
                .join(v, v.auction_id == a.id)
                .where(active, is_vehicle)
            )).scalar_one()

            cat_rows = (await session.execute(
                select(v.vehicle_category, func.count())
                .join(a, a.id == v.auction_id)
                .where(active, is_vehicle)
                .group_by(v.vehicle_category)
            )).all()

            fuel_rows = (await session.execute(
                select(v.fuel, func.count())
                .join(a, a.id == v.auction_id)
                .where(active, is_vehicle, v.fuel.is_not(None), v.fuel != "")
                .group_by(v.fuel)
                .order_by(func.count().desc())
            )).all()

            trans_rows = (await session.execute(
                select(v.transmission, func.count())
                .join(a, a.id == v.auction_id)
                .where(active, is_vehicle, v.transmission.is_not(None), v.transmission != "")
                .group_by(v.transmission)
                .order_by(func.count().desc())
            )).all()

            maker_rows = (await session.execute(
                select(v.maker, func.count())
                .join(a, a.id == v.auction_id)
                .where(active, is_vehicle, v.maker.is_not(None), v.maker != "")
                .group_by(v.maker)
                .order_by(func.count().desc())
                .limit(20)
            )).all()

            year_rows = (await session.execute(
                select(v.year_model, func.count())
                .join(a, a.id == v.auction_id)
                .where(active, is_vehicle, v.year_model.is_not(None), v.year_model != "")
                .group_by(v.year_model)
                .order_by(v.year_model.desc())
            )).all()

        by_category = [
            VehicleFacetCount(
                key=cat.value,
                label=VEHICLE_CATEGORY_LABELS_KO.get(cat),
                count=count,
            )
            for cat, count in cat_rows
        ]
        return VehicleStatsResponse(
            total=int(total),
            by_category=by_category,
            by_fuel=[
                VehicleFacetCount(key=val, label=val, count=cnt)
                for val, cnt in fuel_rows
            ],
            by_transmission=[
                VehicleFacetCount(key=val, label=val, count=cnt)
                for val, cnt in trans_rows
            ],
            by_maker_top=[
                VehicleMakerCount(maker=val, count=cnt)
                for val, cnt in maker_rows
            ],
            by_year_model=[
                VehicleYearBucket(year_model=val, count=cnt)
                for val, cnt in year_rows
            ],
        )

    @staticmethod
    async def _upsert_details(session: AsyncSession, model, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        stmt = pg_insert(model).values(rows)
        update_cols = {
            c.name: stmt.excluded[c.name]
            for c in model.__table__.columns
            if c.name not in ("auction_id", "created_at")
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["auction_id"],
            set_=update_cols,
        )
        await session.execute(stmt)

    @staticmethod
    def _to_parent_row(item: AuctionUpsertItem) -> dict[str, Any]:
        location_val = None
        if item.lng is not None and item.lat is not None:
            location_val = func.ST_SetSRID(
                func.ST_MakePoint(item.lng, item.lat), 4326
            )
        return {
            "source": item.source.value,
            "asset_type": item.asset_type.value,
            "status": item.status.value,
            "cltr_mng_no": item.cltr_mng_no,
            "pbct_cdtn_no": item.pbct_cdtn_no,
            "onbid_cltr_no": item.onbid_cltr_no,
            "onbid_pbanc_no": item.onbid_pbanc_no,
            "pbanc_mng_no": item.pbanc_mng_no,
            "pbct_no": item.pbct_no,
            "pbct_nsq": item.pbct_nsq,
            "pbct_sn": item.pbct_sn,
            "case_number": item.case_number,
            "court_name": item.court_name,
            "title": item.title,
            "pbct_stat_cd": item.pbct_stat_cd,
            "pbct_stat_nm": item.pbct_stat_nm,
            "prpt_div_cd": item.prpt_div_cd,
            "prpt_div_nm": item.prpt_div_nm,
            "dsps_mthod_cd": item.dsps_mthod_cd,
            "dsps_mthod_nm": item.dsps_mthod_nm,
            "bid_div_cd": item.bid_div_cd,
            "bid_div_nm": item.bid_div_nm,
            "bid_mthod_cd": item.bid_mthod_cd,
            "bid_mthod_nm": item.bid_mthod_nm,
            "cptn_mthod_cd": item.cptn_mthod_cd,
            "cptn_mthod_nm": item.cptn_mthod_nm,
            "totalamt_unpc_div_cd": item.totalamt_unpc_div_cd,
            "totalamt_unpc_div_nm": item.totalamt_unpc_div_nm,
            "usg_lcls_id": item.usg_lcls_id,
            "usg_lcls_nm": item.usg_lcls_nm,
            "usg_mcls_id": item.usg_mcls_id,
            "usg_mcls_nm": item.usg_mcls_nm,
            "usg_scls_id": item.usg_scls_id,
            "usg_scls_nm": item.usg_scls_nm,
            "ltno_pnu": item.ltno_pnu,
            "rdnm_pnu": item.rdnm_pnu,
            "region_sido": item.region_sido,
            "region_sigungu": item.region_sigungu,
            "region_emd": item.region_emd,
            "address": item.address,
            "location": location_val,
            "appraisal_price": item.appraisal_price,
            "min_bid_price": item.min_bid_price,
            "min_bid_price_text": item.min_bid_price_text,
            "first_bid_price": item.first_bid_price,
            "apsl_lowst_ratio": item.apsl_lowst_ratio,
            "frst_lowst_ratio": item.frst_lowst_ratio,
            "fee_rate": item.fee_rate,
            "bid_begin_at": item.bid_begin_at,
            "bid_end_at": item.bid_end_at,
            "failed_count": item.failed_count,
            "progress_count": item.progress_count,
            "pvct_trgt_yn": item.pvct_trgt_yn,
            "batc_bid_yn": item.batc_bid_yn,
            "elec_grpr_use_yn": item.elec_grpr_use_yn,
            "collb_bid_psbl_yn": item.collb_bid_psbl_yn,
            "twtm_gthr_bid_psbl_yn": item.twtm_gthr_bid_psbl_yn,
            "subt_bid_psbl_yn": item.subt_bid_psbl_yn,
            "request_org_nm": item.request_org_nm,
            "announce_org_nm": item.announce_org_nm,
            "rent_method_nm": item.rent_method_nm,
            "rent_period_text": item.rent_period_text,
            "evc_rsby_target": item.evc_rsby_target,
            "dtbt_rqr_edtm": item.dtbt_rqr_edtm,
            "thumbnail_url": item.thumbnail_url,
            "image_urls": item.image_urls,
            "correction_yn": item.correction_yn,
            "modified_at": item.modified_at,
            "raw": item.raw,
            "crawled_at": func.now(),
        }
