# -*- coding: utf-8 -*-
"""Synthetic-only region proof tests. No marketplace access or private items."""
from __future__ import annotations

import copy
import hashlib
from types import SimpleNamespace
import unittest

import daangn_v4_1_core as core
import daangn_browser_v4_6 as v46
import daangn_price_bands_v4_8 as bands
import daangn_v4_5_evidence as evidence
from app_v5.region_proof import verified_region
from daangn_full_route_v4_14 import RouteBodies


REGION = core.BY_KEY["cheonan"]
OTHER = core.BY_KEY["asan"]
FILTERED = ("https://www.daangn.com/kr/search/buy-sell/"
            "?q=HDD&category_id=1&only_on_sale=true&price=__50000")
WITH_REGION = FILTERED + "&in=" + REGION["slug"]
BAD_REGION = FILTERED + "&in=" + OTHER["slug"]
PRODUCT = "https://www.daangn.com/kr/buy-sell/synthetic-drive-123456789abc/"


def event(url=FILTERED, region_id="2292", filter_region_id="2292",
          digest=None, status=200):
    return {
        "status": status,
        "digest": digest or hashlib.sha256(b"synthetic first-party Route").hexdigest(),
        "public_request": evidence.public_url(url),
        "model": {
            "region_id": region_id,
            "filter_region_id": filter_region_id,
            "filters": {"regionId": filter_region_id, "categoryId": 1,
                        "maxPrice": 50000, "onlyOnSale": True, "search": "HDD"},
            "articles": [{"href": PRODUCT, "price": 18000,
                          "categoryId": 1, "isSoldOut": False}],
        },
    }


class ProofTests(unittest.TestCase):
    def verify(self, **overrides):
        return verified_region(
            REGION, overrides.pop("page_url", FILTERED),
            overrides.pop("route_event", event()),
            overrides.pop("ui", {"verified": True}),
            picker_selected=overrides.pop("picker_selected", True),
            keyword="HDD",
        )

    def test_stripped_region_passes_only_all_independent_witnesses(self):
        proof = self.verify()
        self.assertEqual(proof["status"], "UI_FRESH_ROUTE_REGION_VERIFIED")
        self.assertTrue(proof["verified"])
        self.assertTrue(proof["region_param_missing"])
        self.assertEqual(proof["url_region"], "MISSING")

    def test_explicit_region_can_be_validated_too(self):
        result = self.verify(page_url=WITH_REGION,route_event=event(WITH_REGION),
                             picker_selected=False)
        self.assertTrue(result["verified"])

    def test_missing_ui_control_rejected_even_if_both_route_ids_match(self):
        self.assertEqual(self.verify(ui={"verified": False})["status"],
                         "REGION_UI_NOT_VERIFIED")

    def test_click_only_never_proves_geography(self):
        self.assertEqual(self.verify(ui={"matching_controls": 1})["status"],
                         "REGION_UI_NOT_VERIFIED")

    def test_no_fresh_route_and_stale_boot_data_fail_closed(self):
        self.assertEqual(self.verify(route_event=None)["status"],
                         "FRESH_ROUTE_NOT_VERIFIED")
        self.assertEqual(self.verify(route_event={
            "model": {"region_id": "2292", "filter_region_id": "2292"},
        })["status"], "FRESH_ROUTE_NOT_VERIFIED")

    def test_wrong_server_search_or_filter_region_is_hard_conflict(self):
        self.assertEqual(self.verify(route_event=event(
            region_id="2333"))["status"], "ROUTE_REGION_CONFLICT")
        self.assertEqual(self.verify(route_event=event(
            filter_region_id="2333"))["status"], "ROUTE_REGION_CONFLICT")

    def test_explicit_wrong_url_region_cannot_be_ignored(self):
        self.assertEqual(self.verify(page_url=BAD_REGION)["status"],
                         "REGION_URL_INVALID")
        self.assertEqual(self.verify(route_event=event(BAD_REGION))["status"],
                         "REGION_URL_INVALID")

    def test_failed_or_tampered_route_never_corroborates(self):
        self.assertEqual(self.verify(route_event=event(status=429))["status"],
                         "FRESH_ROUTE_NOT_VERIFIED")
        self.assertEqual(self.verify(route_event=event(digest="invalid"))["status"],
                         "FRESH_ROUTE_NOT_VERIFIED")

    def test_unapproved_missing_region_rejected(self):
        self.assertEqual(self.verify(picker_selected=False)["status"],
                         "REGION_OMISSION_WITHOUT_UI_SELECTION")

    def test_document_and_response_region_must_agree(self):
        self.assertEqual(self.verify(page_url=WITH_REGION)["status"],
                         "REGION_URL_RESPONSE_DISAGREEMENT")

    def test_query_ambiguity_wrong_host_and_keyword_rejected(self):
        for url in (FILTERED.replace("q=HDD", "q=SSD"),
                    "https://evil.example/kr/search/buy-sell/?q=HDD",
                    FILTERED + "&in=x&in=y",
                    FILTERED.replace("/kr/search/buy-sell/",
                                     "/kr/buy-sell/")):
            with self.subTest(url=url):
                self.assertEqual(self.verify(page_url=url)["status"],
                                 "REGION_URL_INVALID")

    def test_price_band_route_match_requires_both_region_ids_when_missing(self):
        x = event()
        self.assertFalse(bands.matched_route(x,"cap_50000",REGION))
        self.assertTrue(bands.matched_route(
            x,"cap_50000",REGION,allow_missing_region_url=True))
        x["model"]["filter_region_id"] = "2333"
        self.assertFalse(bands.matched_route(
            x,"cap_50000",REGION,allow_missing_region_url=True))
        self.assertFalse(bands.matched_route(
            event(BAD_REGION),"cap_50000",REGION,
            allow_missing_region_url=True))

    def test_v46_stage_requires_authority_for_url_omission(self):
        x = event()
        dom = {"dom_visible": [PRODUCT], "region_button": ""}
        args = SimpleNamespace(regions={"target": REGION})
        without = v46.stage(args,"cheonan_a","target",3,dom,x["model"],FILTERED)
        self.assertFalse(without["region_ok"])
        authorized = v46.stage(args,"cheonan_a","target",3,dom,x["model"],
                               FILTERED,region_authority=self.verify())
        self.assertTrue(authorized["region_ok"])
        invalid = v46.stage(args,"cheonan_a","target",3,dom,x["model"],
                            FILTERED,region_authority=self.verify(ui={"verified": False}))
        self.assertFalse(invalid["region_ok"])

    def test_raw_route_collector_must_correlate_sha_and_missing_url_policy(self):
        x = event()
        store = RouteBodies()
        store.events.append(x)
        proof = self.verify()
        stage = {"matched_route_digest": [x["digest"]],
                 "region_authority": proof}
        self.assertIsNotNone(store.matched(stage,"cheonan"))
        stage["region_authority"] = self.verify(ui={"verified": False})
        self.assertIsNone(store.matched(stage,"cheonan"))
        stage["region_authority"] = proof
        stage["matched_route_digest"] = ["0"*64]
        self.assertIsNone(store.matched(stage,"cheonan"))


if __name__ == "__main__":
    unittest.main()
