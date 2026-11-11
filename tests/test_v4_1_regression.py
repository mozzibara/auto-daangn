import json
import unittest

from daangn_v4_1_core import (
    BY_KEY, classify_ui, compare_urls, jaccard, normalized_listing,
    parse_search_route_json, region_id_in_url, sanitized_url, search_url,
)

A = "https://www.daangn.com/kr/buy-sell/abc-product-123456789abc/"
B = "https://www.daangn.com/kr/buy-sell/other-product-234567890abc/"
C = "https://www.daangn.com/kr/buy-sell/third-product-345678901abc/"


def route_json(region="2292", rows=None, filter_region=None):
    if rows is None:
        rows = [{"href": A, "title": "HDD 2TB", "price": "35000", "region": {"name": "불당동"}},
                {"href": B, "title": "HDD 4TB", "price": "59000", "region": {"name": "사당제3동"}}]
    return {"keyword": "HDD", "searchRegion": {"id": region, "name": "불당동"},
            "currentFilters": {"regionId": filter_region or region, "search": "HDD"},
            "buySellArticles": rows}


def before_page():
    return {"dom_visible": [C], "region_button": "지역 선택: 서울특별시 동작구 사당제3동",
            "initial_loader_region_id": "334"}


def after_page():
    return {"dom_visible": [A], "region_button": "지역 선택: 충청남도 천안시 서북구 불당동",
            "initial_loader_region_id": "334"}


class ParsingTests(unittest.TestCase):
    def test_region_url_query(self):
        u = search_url("HDD", BY_KEY["cheonan"])
        self.assertEqual(region_id_in_url(u), "2292")

    def test_missing_region_url(self):
        self.assertIsNone(region_id_in_url(search_url("HDD", BY_KEY["control"])))

    def test_canonical_url(self):
        self.assertEqual(normalized_listing("/kr/buy-sell/abc-product-123456789abc/?track=one"), A)
        self.assertIsNone(normalized_listing("https://other.example/kr/buy-sell/a-b-123456789abc/"))

    def test_route_json_direct(self):
        d = parse_search_route_json(json.dumps(route_json()).encode())
        self.assertTrue(d["route_found"])
        self.assertEqual(d["search_region_id"], "2292")
        self.assertEqual(d["filter_region_id"], "2292")
        self.assertEqual(d["article_count"], 2)
        self.assertEqual(d["unique_url_count"], 2)
        self.assertEqual(d["article_samples"][0]["price"], "35000")

    def test_route_json_nested(self):
        raw = {"data": {"loaderData": {"routes/kr.search.buy-sell._index": route_json()}}}
        d = parse_search_route_json(json.dumps(raw).encode())
        self.assertEqual(d["search_region_id"], "2292")

    def test_bad_json_handled(self):
        self.assertFalse(parse_search_route_json(b"{oops")["parsed"])

    def test_non_route_json_handled(self):
        self.assertFalse(parse_search_route_json(b'{"root": {"regionId": "2292"}}')["route_found"])

    def test_sets_not_requiring_equality(self):
        self.assertEqual(compare_urls([A, B], [A, C])["overlap"], 1)
        self.assertEqual(jaccard([A, B], [A, C]), 0.33333)

    def test_url_sanitization(self):
        safe = sanitized_url("https://www.daangn.com/kr/search/buy-sell/?q=HDD&in=a-334&token=SECRET&sid=private")
        self.assertNotIn("SECRET", safe)
        self.assertNotIn("private", safe)
        self.assertIn("q=HDD", safe)


class VerdictTests(unittest.TestCase):
    def setUp(self):
        self.target = BY_KEY["cheonan"]
        self.url = "https://www.daangn.com/kr/search/buy-sell/?in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292&q=HDD"
        self.data = parse_search_route_json(json.dumps(route_json()).encode())

    def test_stale_boot_loader_does_not_fail(self):
        d = classify_ui(self.target, before_page(), after_page(), self.data, self.url)
        self.assertTrue(d["verified"])
        self.assertTrue(d["stale_boot_loader_observed"])
        self.assertEqual(d["verdict"], "UI_REGION_CHANGE_VERIFIED_FETCH_DOM")
        self.assertEqual(d["dom_fetch_overlap_count"], 1)

    def test_fetch_region_mismatch_fails(self):
        data = parse_search_route_json(json.dumps(route_json(region="334")).encode())
        d = classify_ui(self.target, before_page(), after_page(), data, self.url)
        self.assertFalse(d["verified"])
        self.assertEqual(d["verdict"], "UI_FETCH_REGION_MISMATCH")

    def test_filter_region_mismatch_fails(self):
        data = parse_search_route_json(json.dumps(route_json(filter_region="2333")).encode())
        d = classify_ui(self.target, before_page(), after_page(), data, self.url)
        self.assertEqual(d["verdict"], "UI_FETCH_REGION_MISMATCH")

    def test_missing_fetch_is_provisional(self):
        d = classify_ui(self.target, before_page(), after_page(), None, self.url)
        self.assertFalse(d["verified"])
        self.assertEqual(d["verdict"], "UI_CHANGED_FETCH_NOT_CAPTURED")

    def test_dom_not_correlated_is_provisional(self):
        page = after_page()
        page["dom_visible"] = [C]
        d = classify_ui(self.target, before_page(), page, self.data, self.url)
        self.assertEqual(d["verdict"], "UI_FETCH_REGION_OK_DOM_UNCONFIRMED")

    def test_button_wrong_not_verified(self):
        page = after_page()
        page["region_button"] = "지역 선택: 사당제3동"
        d = classify_ui(self.target, before_page(), page, self.data, self.url)
        self.assertEqual(d["verdict"], "UI_FETCH_OK_BUTTON_NOT_CONFIRMED")

    def test_fetch_filter_missing_not_full_success(self):
        data = dict(self.data)
        data["filter_region_id"] = None
        d = classify_ui(self.target, before_page(), after_page(), data, self.url)
        self.assertEqual(d["verdict"], "UI_FETCH_INCOMPLETE_REGION_METADATA")
        self.assertFalse(d["verified"])

    def test_weak_dom_overlap_does_not_verify(self):
        data = dict(self.data)
        data["article_urls"] = [A, B, C]
        page = after_page()
        page["dom_visible"] = [A,
            "https://www.daangn.com/kr/buy-sell/item-one-456789012abc/",
            "https://www.daangn.com/kr/buy-sell/item-two-567890123abc/"]
        d = classify_ui(self.target, before_page(), page, data, self.url)
        self.assertEqual(d["verdict"], "UI_FETCH_REGION_OK_DOM_UNCONFIRMED")

    def test_stop_access_challenge(self):
        d = classify_ui(self.target, before_page(), after_page(), self.data, self.url, True)
        self.assertEqual(d["verdict"], "STOP_ACCESS_RESTRICTED")
        self.assertFalse(d["verified"])


if __name__ == "__main__":
    unittest.main()
