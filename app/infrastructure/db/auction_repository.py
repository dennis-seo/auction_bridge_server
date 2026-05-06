"""DB 기반 AuctionRepository 구현 (차세대 v2 스키마 기준)."""
from __future__ import annotations

from typing import Any

from geoalchemy2.functions import ST_Intersects, ST_MakeEnvelope, ST_X, ST_Y
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.auction.repository import AuctionRepository
from app.domain.auction.schemas import (
    ASSET_TYPE_LABELS_KO,
    PROPERTY_CATEGORY_LABELS_KO,
    VEHICLE_CATEGORY_LABELS_KO,
    AssetGroupStat,
    AssetType,
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
)
from app.infrastructure.db.models import (
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

        stmt = (
            select(
                AuctionORM.id,
                AuctionORM.source,
                AuctionORM.asset_type,
                AuctionORM.status,
                AuctionORM.title,
                AuctionORM.address,
                AuctionORM.region_sido,
                AuctionORM.region_sigungu,
                AuctionORM.appraisal_price,
                AuctionORM.min_bid_price,
                AuctionORM.bid_end_at,
                AuctionORM.fee_rate,
                AuctionORM.failed_count,
                AuctionORM.thumbnail_url,
                ST_X(AuctionORM.location).label("lng"),
                ST_Y(AuctionORM.location).label("lat"),
            )
            .where(
                AuctionORM.location.is_not(None),
                ST_Intersects(AuctionORM.location, envelope),
            )
            .order_by(AuctionORM.bid_end_at.asc().nullslast())
            .limit(limit)
        )

        if asset_type is not None:
            stmt = stmt.where(AuctionORM.asset_type == asset_type.value)
        if status is not None:
            stmt = stmt.where(AuctionORM.status == status.value)
        if property_category is not None:
            stmt = stmt.join(
                AuctionRealtyDetailsORM,
                AuctionRealtyDetailsORM.auction_id == AuctionORM.id,
            ).where(
                AuctionRealtyDetailsORM.property_category == property_category.value
            )
        if vehicle_category is not None:
            stmt = stmt.join(
                AuctionVehicleDetailsORM,
                AuctionVehicleDetailsORM.auction_id == AuctionORM.id,
            ).where(
                AuctionVehicleDetailsORM.vehicle_category == vehicle_category.value
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
            pbct_stat_nm=a.pbct_stat_nm,
            prpt_div_nm=a.prpt_div_nm,
            dsps_mthod_nm=a.dsps_mthod_nm,
            bid_div_nm=a.bid_div_nm,
            bid_mthod_nm=a.bid_mthod_nm,
            cptn_mthod_nm=a.cptn_mthod_nm,
            totalamt_unpc_div_nm=a.totalamt_unpc_div_nm,
            usg_lcls_nm=a.usg_lcls_nm,
            usg_mcls_nm=a.usg_mcls_nm,
            usg_scls_nm=a.usg_scls_nm,
            elec_grpr_use_yn=a.elec_grpr_use_yn,
            collb_bid_psbl_yn=a.collb_bid_psbl_yn,
            twtm_gthr_bid_psbl_yn=a.twtm_gthr_bid_psbl_yn,
            subt_bid_psbl_yn=a.subt_bid_psbl_yn,
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
