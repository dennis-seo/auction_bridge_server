"""compose_address 지번 추출 + KakaoGeocoder 동 centroid 거부 회귀."""
from __future__ import annotations

import pytest

from app.infrastructure.external.kakao_geocoder import _is_parcel_level
from app.services.onbid_ingest_service import compose_address


class TestComposeAddressParcel:
    def test_extracts_parcel_from_title(self):
        out = compose_address(
            "경기도", "성남시 분당구", "정자동",
            title="경기도 성남시 분당구 정자동 4-6 한국잡월드 문화및집회시설",
        )
        assert out == "경기도 성남시 분당구 정자동 4-6"

    def test_extracts_single_number_parcel(self):
        out = compose_address(
            "경기도", "성남시 분당구", "정자동",
            title="경기도 성남시 분당구 정자동 209 (정원속궁전 3층 에이338호)",
        )
        assert out == "경기도 성남시 분당구 정자동 209"

    def test_extracts_san_parcel(self):
        out = compose_address(
            "강원도", "정선군", "고한읍",
            title="강원도 정선군 고한읍 산 12-3 임야",
        )
        assert out == "강원도 정선군 고한읍 산 12-3"

    def test_falls_back_to_emd_when_title_missing(self):
        out = compose_address("경기도", "성남시 분당구", "정자동", title=None)
        assert out == "경기도 성남시 분당구 정자동"

    def test_falls_back_when_title_prefix_mismatch(self):
        out = compose_address(
            "경기도", "성남시 분당구", "정자동",
            title="서울특별시 강남구 …",
        )
        assert out == "경기도 성남시 분당구 정자동"

    def test_falls_back_when_no_parcel_after_admin(self):
        out = compose_address(
            "경기도", "성남시 분당구", "정자동",
            title="경기도 성남시 분당구 정자동 (단지명만)",
        )
        assert out == "경기도 성남시 분당구 정자동"

    def test_fallback_kwarg_used_only_when_all_admin_missing(self):
        assert compose_address(None, None, None, fallback="x") == "x"


class TestIsParcelLevel:
    def test_region_centroid_rejected(self):
        doc = {
            "x": "127.1115",
            "y": "37.3614",
            "address": {
                "address_name": "경기 성남시 분당구 정자동",
                "address_type": "REGION",
                "main_address_no": "",
            },
            "road_address": None,
        }
        assert _is_parcel_level(doc) is False

    def test_parcel_accepted_via_main_address_no(self):
        doc = {
            "address": {
                "address_type": "REGION_ADDR",
                "main_address_no": "4",
                "sub_address_no": "6",
            },
            "road_address": None,
        }
        assert _is_parcel_level(doc) is True

    def test_road_address_accepted(self):
        doc = {
            "address": {"address_type": "REGION", "main_address_no": ""},
            "road_address": {"address_name": "경기 성남시 분당구 정자일로 123"},
        }
        assert _is_parcel_level(doc) is True

    def test_main_address_no_zero_rejected(self):
        doc = {
            "address": {"address_type": "REGION_ADDR", "main_address_no": "0"},
            "road_address": None,
        }
        assert _is_parcel_level(doc) is False
