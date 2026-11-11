# -*- coding: utf-8 -*-
"""Offline, privacy-focused legacy-search adapter regressions."""
import json
import unittest

from app_v5.search_surface_probe import (
    SURFACES, check_surface_robots, classify_final_url,
    classify_surface_body, sanitize_surface_probe, surface_url,
)
from daangn_v4_1_core import BY_KEY


class FakeRobots:
    def __init__(self, body: bytes):
        self.status = 200
        self.body = body

    def read(self, count):
        return self.body[:count]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class SearchSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.region = BY_KEY["cheonan"]

    def test_only_known_public_readonly_search_urls(self):
        urls = {name: surface_url(name, self.region) for name in SURFACES}
        self.assertEqual(len(urls), 3)
        self.assertIn("/kr/buy-sell/?", urls["legacy_ssr"])
        self.assertIn("/kr/buy-sell/all/?", urls["legacy_all_data"])
        self.assertIn("routes%2Fkr.buy-sell._index", urls["legacy_all_data"])
        self.assertIn("/kr/buy-sell/s/?", urls["modern_s"])
        for url in urls.values():
            self.assertIn("in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292", url)
            self.assertIn("search=HDD", url)
            self.assertNotIn("api/v1/fleamarket/search", url)

    def test_query_redirect_does_not_authorize_region(self):
        url = surface_url("legacy_ssr", self.region)
        self.assertEqual(classify_final_url(url, "legacy_ssr", self.region)["region"], "EXPECTED")
        changed = "https://www.daangn.com/kr/buy-sell/?search=HDD"
        self.assertEqual(classify_final_url(changed, "legacy_ssr", self.region)["region"], "MISSING")
        other = "https://www.daangn.com/kr/buy-sell/?search=HDD&in=elsewhere-999"
        self.assertEqual(classify_final_url(other, "legacy_ssr", self.region)["region"], "OTHER")
        duplicated = url + "&in=invalid-999"
        self.assertEqual(classify_final_url(duplicated, "legacy_ssr", self.region)["region"], "INVALID")
        evil = "https://evil.example/kr/buy-sell/?search=HDD&in=somewhere-999"
        self.assertEqual(classify_final_url(evil, "legacy_ssr", self.region)["host"], "OTHER")

    def test_legacy_data_is_diagnostic_and_keeps_only_metadata(self):
        listing = {
            "title": "PRIVATE TEST TITLE", "href": "https://example.com/private-token",
            "id": "highly-sensitive-identifier", "price": 12000
        }
        doc = {"allPage": {"fleamarketArticles": [listing],
                           "searchRegion": {"id": "2292"},
                           "currentFilters": {"regionId": "2292"}}}
        result = classify_surface_body(json.dumps(doc).encode(), "application/json", self.region)
        self.assertEqual(result["shape"], "FLEAMARKET_API")
        self.assertEqual(result["article_count"], 1)
        self.assertEqual(result["server_region"], "EXPECTED")
        self.assertEqual(result["filter_region"], "EXPECTED")
        self.assertNotIn("PRIVATE", str(result))
        self.assertNotIn("private-token", str(result))
        self.assertNotIn("2292", str(result))

    def test_browser_emitted_api_json_not_a_listing_promotion(self):
        doc = {"fleamarketArticles": [{"price": 1, "region": "OTHER"}]}
        result = classify_surface_body(json.dumps(doc).encode(), "application/json", self.region)
        self.assertEqual(result["shape"], "FLEAMARKET_API")
        self.assertEqual(result["server_region"], "MISSING")
        self.assertEqual(result["filter_region"], "MISSING")

    def test_ssr_presence_is_not_locality_evidence(self):
        html = b'<script type="application/ld+json">{"@type":"ItemList","itemListElement":[{"title":"SECRET"}]}</script>'
        result = classify_surface_body(html, "text/html; charset=utf-8", self.region)
        self.assertEqual(result["shape"], "SSR_ITEMLIST")
        self.assertEqual(result["article_count"], 0)
        self.assertEqual(result["server_region"], "MISSING")

    def test_refuse_oversized_payload_and_invalid_json(self):
        too_large = b" " * 1_500_001
        self.assertEqual(classify_surface_body(too_large, "text/html", self.region)["shape"], "BODY_LIMIT")
        self.assertEqual(classify_surface_body(b"not json", "application/json", self.region)["shape"],
                         "UNRECOGNIZED")

    def test_robots_check_is_per_exact_path_and_fail_closed(self):
        body = (b"User-agent: *\nDisallow: /kr/buy-sell/s/\n"
                b"Allow: /kr/buy-sell/\n")
        result = check_surface_robots(self.region, getter=lambda *args, **kwargs: FakeRobots(body))
        self.assertEqual(result["state"], "CHECKED")
        self.assertFalse(result["allowed"]["modern_s"])
        self.assertTrue(result["allowed"]["legacy_ssr"])
        self.assertTrue(result["allowed"]["legacy_all_data"])
        unavailable = check_surface_robots(self.region, getter=lambda *a, **kw: (_ for _ in ()).throw(OSError()))
        self.assertTrue(all(not x for x in unavailable["allowed"].values()))

    def test_untrusted_user_content_never_crosses_allowlist(self):
        injected = {"robots": "SECRET_TOKEN", "authorization": True, "blocked": False,
                    "surfaces": {"legacy_ssr": {"status": "PRIVATE TITLE",
                    "shape": "SSR_ITEMLIST", "region": "secret-123456",
                    "article_count": 999999, "api_emitted": 2,
                    "server_region": "secret-id", "token": "cookie=session"}}}
        result = sanitize_surface_probe(injected)
        self.assertFalse(result["authorization"])
        self.assertEqual(result["surfaces"]["legacy_ssr"]["status"], "NOT_RUN")
        self.assertEqual(result["surfaces"]["legacy_ssr"]["region"], "MISSING")
        self.assertEqual(result["surfaces"]["legacy_ssr"]["article_count"], 0)
        self.assertNotIn("secret", str(result).lower())
        self.assertEqual(len(result["surfaces"]), 3)


if __name__ == "__main__":
    unittest.main()
