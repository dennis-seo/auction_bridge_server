"""parse_int / parse_float / parse_yn / parse_dt — 변환 helper 회귀 테스트."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.onbid_ingest_service import (
    parse_dt,
    parse_float,
    parse_int,
    parse_yn,
)

KST = timezone(timedelta(hours=9))


class TestParseInt:
    @pytest.mark.parametrize("v,expected", [
        (None, None),
        ("", None),
        ("12", 12),
        ("-5", -5),
        ("12-34", 12),         # B2 회귀: 다중 하이픈 입력 시 크래시 안 함
        ("비공개", None),
        ("12.5", 12),
        ("   42  ", 42),
        ("-1234.5", -1234),
        (256000000, 256000000),
        ("0", 0),
    ])
    def test_parse_int(self, v, expected):
        assert parse_int(v) == expected


class TestParseFloat:
    @pytest.mark.parametrize("v,expected", [
        (None, None),
        ("", None),
        ("3.14", 3.14),
        ("-0.5", -0.5),
        ("abc", None),
        ("62.453", 62.453),
    ])
    def test_parse_float(self, v, expected):
        assert parse_float(v) == expected


class TestParseYn:
    @pytest.mark.parametrize("v,expected", [
        (None, None),
        ("", None),
        ("Y", True),
        ("y", True),
        ("N", False),
        ("n", False),
        ("X", None),
        (" Y ", True),
    ])
    def test_parse_yn(self, v, expected):
        assert parse_yn(v) == expected


class TestParseDt:
    def test_yyyymmddhhmm(self):
        assert parse_dt("202604290800") == datetime(2026, 4, 29, 8, 0, tzinfo=KST)

    def test_yyyymmddhhmmss(self):
        assert parse_dt("20220208090001") == datetime(2022, 2, 8, 9, 0, 1, tzinfo=KST)

    def test_yyyymmdd(self):
        assert parse_dt("20260615") == datetime(2026, 6, 15, tzinfo=KST)

    def test_sentinel_year_filtered(self):
        # 2999-12-30 같은 sentinel은 None 처리 (회귀: bid_end_at 무한대 방지)
        assert parse_dt("299912301600") is None

    def test_year_too_old_filtered(self):
        assert parse_dt("198912301600") is None

    @pytest.mark.parametrize("v", [None, "", "abc", "2026-04-29", "12345"])
    def test_invalid_returns_none(self, v):
        assert parse_dt(v) is None
