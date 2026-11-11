# -*- coding: utf-8 -*-
"""Synthetic-only server region/name correspondence and privacy tests."""
from __future__ import annotations

import json
import unittest

import daangn_v4_1_core as core
import daangn_v4_5_evidence as evidence
from app_v5.region_proof import classify_region_correspondence, verified_region

REGION = core.BY_KEY["cheonan"]
PAGE = ("https://www.daangn.com/kr/search/buy-sell/"
        "?q=HDD&category_id=1&only_on_sale=true&price=__50000")


def model(region_id="2292", filter_region_id="2292", name="불당동"):
    return {"region_id": region_id, "filter_region_id": filter_region_id,
            "search_region_name": name}


class RegionCorrespondenceTests(unittest.TestCase):
    def test_old_id_candidate_stays_non_authoritative(self):
        result = classify_region_correspondence(
            model("999999", "999999"), REGION)
        self.assertEqual(result["search_region_name_state"], "EXACT")
        self.assertEqual(result["server_region_ids_agree"], "YES")
        self.assertTrue(result["historical_id_drift_candidate"])
        self.assertFalse(result["verified"])
        self.assertNotIn("999999", str(result))
        self.assertNotIn("불당동", str(result))

    def test_unequal_ids_are_not_a_stale_id_candidate(self):
        x = classify_region_correspondence(model("900001", "900002"), REGION)
        self.assertEqual(x["server_region_ids_agree"], "NO")
        self.assertFalse(x["historical_id_drift_candidate"])
        self.assertFalse(x["verified"])

    def test_different_region_name_is_not_a_stale_id_candidate(self):
        x = classify_region_correspondence(
            model("900001", "900001", "다른지역"), REGION)
        self.assertEqual(x["search_region_name_state"], "OTHER")
        self.assertFalse(x["historical_id_drift_candidate"])

    def test_name_can_be_full_path_but_is_not_proof(self):
        x = classify_region_correspondence(
            model("900001", "900001", "충청남도 천안시 서북구 불당동"), REGION)
        self.assertEqual(x["search_region_name_state"], "CONTAINS")
        self.assertTrue(x["historical_id_drift_candidate"])
        self.assertFalse(x["verified"])

    def test_missing_values_do_not_count_as_correspondence(self):
        x = classify_region_correspondence(
            model(None, "900001", None), REGION)
        self.assertEqual(x["search_region_name_state"], "MISSING")
        self.assertEqual(x["server_region_ids_agree"], "MISSING")
        self.assertFalse(x["historical_id_drift_candidate"])
        self.assertFalse(x["verified"])

    def test_expected_ids_are_not_drift(self):
        x = classify_region_correspondence(model(), REGION)
        self.assertEqual(x["server_region_ids_agree"], "YES")
        self.assertFalse(x["historical_id_drift_candidate"])
        self.assertFalse(x["verified"])

    def test_region_name_remains_in_memory_model_only(self):
        raw = {
            "data": {
                "searchRegion": {"id": "900001", "name": "불당동"},
                "currentFilters": {"regionId": "900001"},
                "buySellArticles": [{"href": (
                    "https://www.daangn.com/kr/buy-sell/test-123456789abc/"),
                    "price": 19900}],
            }
        }
        extracted = evidence.extract_model(json.dumps(raw).encode())
        self.assertEqual(extracted["search_region_name"], "불당동")
        result = classify_region_correspondence(extracted, REGION)
        self.assertTrue(result["historical_id_drift_candidate"])
        self.assertNotIn("900001", str(result))
        self.assertNotIn("불당동", str(result))


if __name__ == "__main__":
    unittest.main()
