from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.domain.auction.repository import AuctionRepository
from app.domain.auction.service import AuctionService
from app.infrastructure.db.auction_repository import DBAuctionRepository
from app.mock.auction_mock import MockAuctionRepository


def get_auction_repository() -> AuctionRepository:
    settings = get_settings()
    if settings.USE_MOCK:
        return MockAuctionRepository()
    return DBAuctionRepository(session_factory=AsyncSessionLocal)


def get_auction_service() -> AuctionService:
    return AuctionService(repo=get_auction_repository())
