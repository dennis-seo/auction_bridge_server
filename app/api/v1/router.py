from fastapi import APIRouter

from app.api.v1.endpoints import admin, auctions, bid_results, cron, realty, vehicles

api_v1_router = APIRouter()
api_v1_router.include_router(auctions.router)
api_v1_router.include_router(realty.router)
api_v1_router.include_router(bid_results.router)
api_v1_router.include_router(vehicles.router)
api_v1_router.include_router(admin.router)
api_v1_router.include_router(cron.router)
