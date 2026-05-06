"""OnbidClient.extract_image_urls — 부동산 상세 응답에서 사진 URL 추출."""
from __future__ import annotations

from app.infrastructure.external.onbid_client import extract_image_urls


def test_list_of_dicts_with_urlAdr():
    detail = {
        "potoUrlList": [
            {"urlAdr": "https://onbid/img1.jpg"},
            {"urlAdr": "https://onbid/img2.jpg"},
        ],
    }
    assert extract_image_urls(detail) == [
        "https://onbid/img1.jpg",
        "https://onbid/img2.jpg",
    ]


def test_single_dict_block():
    detail = {"potoUrlList": {"urlAdr": "https://onbid/x.jpg"}}
    assert extract_image_urls(detail) == ["https://onbid/x.jpg"]


def test_legacy_keys_fallback():
    # urlAdr 없으면 potoUrl/imgUrl/photoUrl 순으로 시도
    detail = {"potoUrlList": [{"potoUrl": "a"}, {"imgUrl": "b"}, {"photoUrl": "c"}]}
    assert extract_image_urls(detail) == ["a", "b", "c"]


def test_empty_block():
    assert extract_image_urls({"potoUrlList": []}) == []
    assert extract_image_urls({"potoUrlList": None}) == []
    assert extract_image_urls({}) == []
    assert extract_image_urls(None) == []  # type: ignore[arg-type]


def test_strings_in_list():
    detail = {"potoUrlList": ["https://onbid/a.jpg", "  https://onbid/b.jpg  "]}
    assert extract_image_urls(detail) == ["https://onbid/a.jpg", "https://onbid/b.jpg"]


def test_skip_blank_url():
    detail = {"potoUrlList": [{"urlAdr": ""}, {"urlAdr": "  "}, {"urlAdr": "https://x"}]}
    assert extract_image_urls(detail) == ["https://x"]
