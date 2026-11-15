# -*- coding: utf-8 -*-
"""RED/GREEN: bounded in-memory price sample and non-admitting locality proof."""
import json
import unittest
from app_v5.price_sample_evidence import (
    inspect_bounded_price_sample, attest_bounded_price_sample,
)
from app_v5.region_apply_correspondence import classify_apply_region_correspondence
from app_v5.precollection_filter_gate import sanitize_precollection


def payload(prices, *, duplicate=False):
    model = {
        "searchRegion": {"id": 2292},
        "currentFilters": {
            "regionId": 2292, "categoryId": 1,
            "onlyOnSale": True, "price": "__50000"
        },
        "buySellArticles": [
            {"price": price, "title": "SENSITIVE_TITLE",
             "seller": "SENSITIVE_SELLER", "href": "https://invalid.test/secret"}
            for price in prices
        ],
    }
    return json.dumps({"routes": [model, model] if duplicate else [model]}).encode()


def original_proof():
    fields = {"keyword":"EXPECTED", "region":"MISSING", "category":"EXPECTED",
              "price_max":"EXPECTED", "available":"EXPECTED"}
    url = {"shape":"FIRST_PARTY_SEARCH", "fields":fields}
    return {
        "region_gate_confirmed":True,
        "ui_selected_before_apply":True,
        "filter_apply_returned":True,
        "apply_request_listener_armed":True,
        "filtered_url_matches":False,
        "status":"BLOCKED_FILTER_URL",
        "post_apply_region_header":"TARGET",
        "filtered_url_diagnostics":url,
        "filter_transport_diagnostics":{
            "search_requests":1, "search_responses":1,
            "search_response_200":1, "search_request_failures":0,
            "search_response_restricted":0,
        },
        "apply_search_request_diagnostics":{
            "observation":"ONE_OBSERVED", "method":"GET",
            "transport":"FETCH_OR_XHR", "outcome":"HTTP_200",
            "request_extra_query_family":"OTHER_REMIX_DATA_ID",
            "response_extra_query_family":"OTHER_REMIX_DATA_ID",
            "request_data_route_family":"SEARCH_PREFIX",
            "response_data_route_family":"SEARCH_PREFIX",
            "request_url":url, "response_url":url,
        },
        "dynamic_loader_metadata_mode":True,
        "dynamic_loader_metadata_count":1,
        "dynamic_loader_metadata_status":"ONE_PARSED",
        "dynamic_loader_server_filters":{
            "region":"EXPECTED", "category":"EXPECTED",
            "available":"EXPECTED", "price_max":"MISSING",
        },
        "dynamic_loader_price_shape":"UNTRUSTED_PRICE_ONLY",
        "dynamic_loader_price_echo":"ENCODED_MAX_MATCH",
        "dynamic_price_sample_mode":True,
        "dynamic_price_sample_verdict":"SAMPLE_WITHIN_CAP",
        "secret":"DO_NOT_EXPORT",
    }


class PriceSampleTests(unittest.TestCase):
    def test_all_numeric_prices_within_cap(self):
        self.assertEqual(inspect_bounded_price_sample(payload([0, 50000, "49999"])),
                         "SAMPLE_WITHIN_CAP")

    def test_any_above_cap_is_counterexample(self):
        self.assertEqual(inspect_bounded_price_sample(payload([1000, 50001])),
                         "ABOVE_CAP_OBSERVED")

    def test_incomplete_price_coverage_blocks_consistency(self):
        for prices in ([None], [True], [-1], [1.5], ["50,000"], [{}]):
            with self.subTest(prices=prices):
                self.assertEqual(inspect_bounded_price_sample(payload(prices)),
                                 "INCOMPLETE_PRICE_COVERAGE")

    def test_ambiguous_empty_oversized_and_invalid_payloads(self):
        self.assertEqual(inspect_bounded_price_sample(payload([], duplicate=True)),
                         "AMBIGUOUS_MODEL")
        self.assertEqual(inspect_bounded_price_sample(payload([])),
                         "EMPTY_SAMPLE")
        self.assertEqual(inspect_bounded_price_sample(payload([1]*651)),
                         "TOO_MANY_ROWS")
        self.assertEqual(inspect_bounded_price_sample(b"not-json"),
                         "UNOBSERVABLE")

    def test_sanitized_price_sample_never_proves_backend(self):
        safe = sanitize_precollection(original_proof())
        sample = safe["bounded_price_sample_evidence"]
        self.assertEqual(sample["sample_verdict"], "SAMPLE_WITHIN_CAP")
        self.assertEqual(sample["source_provenance"], "SINGLE_BROWSER_REMIX_DATA_200")
        self.assertFalse(sample["price_cap_enforced"])
        self.assertFalse(sample["authorizes_listings"])
        self.assertFalse(safe["strict_filter_evidence"])
        self.assertNotIn("DO_NOT_EXPORT", json.dumps(safe))

    def test_weak_or_competing_source_cannot_promote_sample(self):
        for change in (
            ("region_gate_confirmed",False),
            ("dynamic_loader_metadata_count",2),
            ("dynamic_loader_metadata_status","ONE_UNREADABLE"),
            ("filter_apply_returned",False),
        ):
            with self.subTest(change=change):
                raw=original_proof()
                raw[change[0]]=change[1]
                safe=sanitize_precollection(raw)
                self.assertEqual(safe["bounded_price_sample_evidence"]["sample_verdict"],
                                 "UNVERIFIED")

    def test_mode_not_approved_must_not_promote(self):
        raw=original_proof()
        raw["dynamic_price_sample_mode"]=False
        self.assertEqual(attest_bounded_price_sample(raw)["sample_verdict"],
                         "NOT_REQUESTED")

    def test_raw_enum_injection_fails_closed(self):
        raw=original_proof()
        raw["dynamic_price_sample_verdict"]="SENSITIVE_PRICE_STRING"
        safe=sanitize_precollection(raw)
        self.assertEqual(safe["bounded_price_sample_evidence"]["sample_verdict"],
                         "UNVERIFIED")
        self.assertNotIn("SENSITIVE_PRICE_STRING",json.dumps(safe))


class RegionCorrespondenceTests(unittest.TestCase):
    def test_regionless_response_does_not_authorize(self):
        safe=sanitize_precollection(original_proof())
        proof=safe["apply_region_correspondence"]
        self.assertEqual(proof["classification"],
                         "SERVER_MATCH_BUT_URL_REGION_MISSING")
        self.assertFalse(proof["authorizes_listings"])
        self.assertFalse(proof["releases_region_mismatch"])

    def test_contradictory_server_region_not_masked_by_ui(self):
        raw=original_proof()
        raw["dynamic_loader_server_filters"]["region"]="OTHER"
        self.assertEqual(
            classify_apply_region_correspondence(raw)["classification"],
            "SERVER_REGION_CONFLICT")

    def test_url_or_transport_ambiguity_stays_unverified(self):
        raw=original_proof()
        raw["apply_search_request_diagnostics"]["observation"]="MULTIPLE_OBSERVED"
        self.assertEqual(
            classify_apply_region_correspondence(raw)["classification"],
            "UNVERIFIED")

    def test_page_url_expected_does_not_substitute_post_apply_ui(self):
        raw=original_proof()
        raw["filtered_url_diagnostics"]["fields"]["region"]="EXPECTED"
        raw["post_apply_region_header"]="UNOBSERVABLE"
        result=classify_apply_region_correspondence(raw)
        self.assertFalse(result["authorizes_listings"])


if __name__ == "__main__":
    unittest.main()
