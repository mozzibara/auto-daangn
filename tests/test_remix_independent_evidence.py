# -*- coding: utf-8 -*-
"""RED/GREEN synthetic tests: independent post-Apply browser Remix _data."""
from __future__ import annotations

import json
import unittest
from copy import deepcopy

from app_v5.precollection_filter_gate import (
    inspect_dynamic_filtered_response_details, sanitize_precollection,
)
from app_v5.remix_independent_evidence import independent_remix_evidence


def model(filters=None, *, region=2292, category=1, available=True,
          extra_model=False):
    # Never inspect article content: sentinel data must not leak.
    def payload(r, c, a):
        return {
            "searchRegion": {"id": r},
            "currentFilters": {
                "regionId": r, "categoryId": c, "onlyOnSale": a,
                **(filters if filters is not None else {"price": "__50000"})
            },
            "buySellArticles": [{
                "seller": "PRIVATE_SELLER_DO_NOT_EXPORT",
                "title": "PRIVATE_LISTING_DO_NOT_EXPORT",
                "url": "https://private.invalid/secret",
            }],
        }
    entries = [payload(region, category, available)]
    if extra_model:
        entries.append(payload(region, category, available))
    return json.dumps({"route": entries}, ensure_ascii=False).encode()


def proof(body=None):
    states, shape, echo = inspect_dynamic_filtered_response_details(
        body if body is not None else model())
    fq = {"shape": "FIRST_PARTY_SEARCH",
          "fields": {"region": "MISSING", "keyword": "EXPECTED",
                     "category": "EXPECTED", "price_max": "EXPECTED",
                     "available": "EXPECTED"},
          "unexpected_keys": 1}
    return {
        "region_gate_confirmed": True,
        "ui_selected_before_apply": True,
        "filter_apply_returned": True,
        "apply_request_listener_armed": True,
        "filter_transport_diagnostics": {
            "search_requests": 1, "search_responses": 1,
            "search_response_200": 1, "search_request_failures": 0,
            "search_response_restricted": 0,
        },
        "apply_search_request_diagnostics": {
            "observation": "ONE_OBSERVED",
            "method": "GET", "transport": "FETCH_OR_XHR",
            "outcome": "HTTP_200",
            "request_extra_query_family": "OTHER_REMIX_DATA_ID",
            "response_extra_query_family": "OTHER_REMIX_DATA_ID",
            "request_data_route_family": "OTHER_ROUTES_NAMESPACE",
            "response_data_route_family": "OTHER_ROUTES_NAMESPACE",
            "request_url": fq,
            "response_url": deepcopy(fq),
        },
        "dynamic_loader_metadata_mode": True,
        "dynamic_loader_metadata_count": 1,
        "dynamic_loader_metadata_status": "ONE_PARSED",
        "dynamic_loader_server_filters": states,
        "dynamic_loader_price_shape": shape,
        "dynamic_loader_price_echo": echo,
        "filtered_url_matches": False,
        "status": "BLOCKED_FILTER_URL",
        "strict_filter_evidence": False,
        "private_token": "DO_NOT_EXPORT_SECRET",
    }


class IndependentRemixContractTests(unittest.TestCase):
    def test_realistic_echo_only_is_not_backend_price_enforcement(self):
        row = sanitize_precollection(proof())
        result = row["remix_independent_evidence"]
        self.assertEqual(result["source_provenance"],
                         "SINGLE_BROWSER_REMIX_DATA_200")
        self.assertEqual(result["response_region_ids"], "EXPECTED")
        self.assertEqual(result["response_category"], "EXPECTED")
        self.assertEqual(result["response_available_only"], "EXPECTED")
        self.assertEqual(result["response_max_price_declaration"], "MISSING")
        self.assertEqual(result["response_price_evidence"],
                         "ENCODED_ECHO_ONLY_MATCH")
        self.assertFalse(result["price_cap_enforced"])
        self.assertFalse(result["authorizes_listings"])
        self.assertEqual(row["status"], "BLOCKED_FILTER_URL")
        self.assertFalse(row["strict_filter_evidence"])
        self.assertNotIn("PRIVATE_", json.dumps(row))
        self.assertNotIn("DO_NOT_EXPORT", json.dumps(row))

    def test_direct_max_match_is_declaration_not_causal_enforcement(self):
        row = sanitize_precollection(proof(model(
            {"maxPrice": 50000, "price": "__50000"})))
        result = row["remix_independent_evidence"]
        self.assertEqual(result["response_price_evidence"],
                         "DECLARED_MAX_MATCH_UNENFORCED")
        self.assertEqual(result["response_max_price_declaration"], "EXPECTED")
        self.assertFalse(result["price_cap_enforced"])
        self.assertFalse(result["releases_region_mismatch"])

    def test_nested_price_range_max_supported_but_not_enforced(self):
        row = sanitize_precollection(proof(model(
            {"priceRange": {"max": 50000}})))
        self.assertEqual(row["remix_independent_evidence"]["response_price_evidence"],
                         "DECLARED_MAX_MATCH_UNENFORCED")

    def test_declaration_vs_echo_conflict_fail_closed(self):
        row = sanitize_precollection(proof(model(
            {"maxPrice": 50000, "price": "__60000"})))
        v = row["remix_independent_evidence"]
        self.assertEqual(v["response_max_price_declaration"], "EXPECTED")
        self.assertEqual(v["response_price_evidence"],
                         "DECLARED_CONFLICTING_ECHO")
        self.assertIn("PRICE_MAX_DECLARATION_NOT_UNCONTRADICTED",
                      v["missing_independent_evidence"])

    def test_direct_max_wrong_and_same_echo_stays_wrong(self):
        row = sanitize_precollection(proof(model(
            {"maxPrice": 60000, "price": "__50000"})))
        self.assertEqual(row["remix_independent_evidence"]["response_price_evidence"],
                         "DECLARED_MAX_MISMATCH")

    def test_duplicate_max_sources_are_ambiguous(self):
        row = sanitize_precollection(proof(model(
            {"maxPrice": 50000, "priceRange": {"max": 50000}})))
        self.assertEqual(row["remix_independent_evidence"]["response_price_evidence"],
                         "AMBIGUOUS_DECLARATION")

    def test_region_and_category_disagree_independently(self):
        row = sanitize_precollection(proof(model(
            region=1000, category=7, available=False)))
        v = row["remix_independent_evidence"]
        self.assertEqual(v["response_region_ids"], "OTHER")
        self.assertEqual(v["response_category"], "OTHER")
        self.assertEqual(v["response_available_only"], "OTHER")
        self.assertIn("FILTERED_REGION_NOT_CONFIRMED",
                      v["missing_independent_evidence"])

    def test_multiple_search_models_are_not_promoted(self):
        row = sanitize_precollection(proof(model(extra_model=True)))
        self.assertEqual(row["remix_independent_evidence"]["response_region_ids"],
                         "MISSING")
        self.assertFalse(row["remix_independent_evidence"]["authorizes_listings"])

    def test_network_ambiguity_denies_all_favorable_body_fields(self):
        for change in (
            ("filter_transport_diagnostics", "search_requests", 2),
            ("filter_transport_diagnostics", "search_response_restricted", 1),
            ("apply_search_request_diagnostics", "outcome", "ACCESS_RESTRICTED"),
            ("apply_search_request_diagnostics", "transport", "DOCUMENT"),
            ("apply_search_request_diagnostics", "request_data_route_family",
             "NOT_ROUTES_NAMESPACE"),
            ("dynamic_loader_metadata_status", None, "ONE_UNREADABLE"),
            ("region_gate_confirmed", None, False),
            ("filter_apply_returned", None, False),
        ):
            with self.subTest(change=change):
                p = proof()
                key, sub, value = change
                if sub is None:
                    p[key] = value
                else:
                    p[key][sub] = value
                safe = sanitize_precollection(p)["remix_independent_evidence"]
                self.assertEqual(safe["source_provenance"], "UNVERIFIED")
                self.assertEqual(safe["response_region_ids"], "UNVERIFIED")
                self.assertEqual(safe["response_category"], "UNVERIFIED")
                self.assertEqual(safe["response_price_evidence"], "UNVERIFIED")

    def test_missing_body_and_malformed_values_do_not_raise_or_leak(self):
        for input_ in (None, [], "secret", {},
                       {"dynamic_loader_server_filters":
                        {"region": "SECRET_RAW_STRING", "price_max": 50000}},
                       {"apply_search_request_diagnostics": "PRIVATE_URL"}):
            with self.subTest(value=type(input_).__name__):
                result = independent_remix_evidence(input_)
                self.assertEqual(result["source_provenance"], "UNVERIFIED")
                self.assertFalse(result["authorizes_listings"])
                self.assertNotIn("SECRET_", json.dumps(result))
                self.assertNotIn("PRIVATE_URL", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
