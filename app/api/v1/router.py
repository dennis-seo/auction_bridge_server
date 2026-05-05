from fastapi import APIRouter

from app.api.v1.endpoints import admin, auctions

api_v1_router = APIRouter()
api_v1_router.include_router(auctions.router)
api_v1_router.include_router(admin.router)
