"""map_status / map_property_category / map_vehicle_category 회귀."""
from __future__ import annotations

import pytest

from app.domain.auction.schemas import (
    AuctionStatus,
    PropertyCategory,
    VehicleCategory,
)
from app.services.onbid_ingest_service import (
    map_property_category,
    map_status,
    map_vehicle_category,
)


class TestMapStatus:
    @pytest.mark.parametrize("code,expected", [
        ("0001", AuctionStatus.SCHEDULED),
        ("0009", AuctionStatus.SCHEDULED),
        ("0002", AuctionStatus.ONGOING),
        ("0003", AuctionStatus.ONGOING),  # 입찰마감 — 결과 미정
        ("0006", AuctionStatus.ONGOING),
        ("0010", AuctionStatus.SOLD),
        ("0011", AuctionStatus.FAILED),
        ("0012", AuctionStatus.CANCELLED),
        ("0014", AuctionStatus.CANCELLED),
    ])
    def test_known_codes(self, code, expected):
        assert map_status(code, "") == expected

    def test_falls_back_to_name_낙찰(self):
        assert map_status(None, "낙찰") == AuctionStatus.SOLD

    def test_falls_back_to_name_유찰(self):
        assert map_status(None, "유찰") == AuctionStatus.FAILED

    def test_falls_back_to_name_취하(self):
        assert map_status(None, "취하") == AuctionStatus.CANCELLED


class TestMapPropertyCategory:
    @pytest.mark.parametrize("scls,mcls,expected", [
        ("아파트", "주거용건물", PropertyCategory.APARTMENT),
        ("오피스텔", "상가용및업무용건물", PropertyCategory.OFFICETEL),
        ("다세대주택", "주거용건물", PropertyCategory.VILLA),
        ("단독주택", "주거용건물", PropertyCategory.HOUSE),
        ("기숙사", "주거용건물", PropertyCategory.HOUSE),
        ("기타주거용건물", "주거용건물", PropertyCategory.HOUSE),
        ("근린생활시설", "상가용및업무용건물", PropertyCategory.COMMERCIAL),
        ("판매시설", "상가용및업무용건물", PropertyCategory.COMMERCIAL),
        ("공장시설", "산업용및기타특수용건물", PropertyCategory.COMMERCIAL),
        ("창고시설", "산업용및기타특수용건물", PropertyCategory.COMMERCIAL),
        ("전", "토지", PropertyCategory.LAND),
        ("답", "토지", PropertyCategory.LAND),
        ("임야", "토지", PropertyCategory.LAND),
        ("도로", "토지", PropertyCategory.LAND),
        # 미분류는 etc
        ("외계인기지", "외계용건물", PropertyCategory.ETC),
    ])
    def test_categories(self, scls, mcls, expected):
        assert map_property_category(scls, mcls) == expected

    def test_title_fallback_apartment(self):
        # scls 없을 때 타이틀로 매칭
        assert map_property_category(
            scls=None, mcls=None, lcls="부동산", title="○○동 아파트 5층",
        ) == PropertyCategory.APARTMENT


class TestMapVehicleCategory:
    @pytest.mark.parametrize("scls,expected", [
        ("승용차", VehicleCategory.SEDAN),
        ("SUV", VehicleCategory.SEDAN),
        ("승합차", VehicleCategory.VAN),
        ("화물차", VehicleCategory.TRUCK),
        ("트럭", VehicleCategory.TRUCK),
        ("버스", VehicleCategory.BUS),
        ("이륜차", VehicleCategory.MOTORCYCLE),
        ("오토바이", VehicleCategory.MOTORCYCLE),
        ("특수자동차", VehicleCategory.SPECIAL),
        ("지게차", VehicleCategory.SPECIAL),
        ("굴삭기", VehicleCategory.SPECIAL),
        ("소방차", VehicleCategory.SPECIAL),
        ("기타차량", VehicleCategory.ETC),
    ])
    def test_vehicle_categories(self, scls, expected):
        assert map_vehicle_category(scls) == expected
