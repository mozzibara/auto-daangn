# -*- coding: utf-8 -*-
"""Synthetic URI evidence: no marketplace access, redirects or listing leakage."""
from __future__ import annotations

import unittest

import daangn_v4_1_core as core
from daangn_full_route_v4_14 import classify_baseline_region_urls


class InitialRegionURLProofTests(unittest.TestCase):
    def setUp(self):
        self.requested = core.search_url("HDD", core.BY_KEY["cheonan"])

    def test_matching_initial_region(self):
        proof = classify_baseline_region_urls(
            self.requested, self.requested, self.requested, "2292")
        for stage in ("requested", "response", "rendered"):
            self.assertEqual(proof[stage]["region"], "EXPECTED")
            self.assertEqual(proof[stage]["keyword"], "EXPECTED")
            self.assertEqual(proof[stage]["path"], "EXPECTED")
        self.assertFalse(proof["response_changed_from_request"])
        self.assertFalse(proof["rendered_changed_from_response"])
        self.assertNotIn("불당동", repr(proof))
        self.assertNotIn("https://", repr(proof))

    def test_http_redirect_strips_region(self):
        redirected = "https://www.daangn.com/kr/search/buy-sell/?q=HDD"
        proof = classify_baseline_region_urls(
            self.requested, redirected, redirected, "2292")
        self.assertEqual(proof["requested"]["region"], "EXPECTED")
        self.assertEqual(proof["response"]["region"], "MISSING")
        self.assertEqual(proof["rendered"]["region_parameter"], "MISSING")
        self.assertTrue(proof["response_changed_from_request"])

    def test_client_side_removes_region(self):
        rendered = "https://www.daangn.com/kr/search/buy-sell/?q=HDD"
        proof = classify_baseline_region_urls(
            self.requested, self.requested, rendered, "2292")
        self.assertEqual(proof["response"]["region"], "EXPECTED")
        self.assertEqual(proof["rendered"]["region"], "MISSING")
        self.assertTrue(proof["rendered_changed_from_response"])

    def test_wrong_region_and_unexpected_host(self):
        other = core.search_url("HDD", core.BY_KEY["asan"])
        proof = classify_baseline_region_urls(
            self.requested, other, other, "2292")
        self.assertEqual(proof["rendered"]["region"], "OTHER")
        bad = "https://invalid.example/hidden-secret?in=배방읍-2333&q=HDD"
        proof = classify_baseline_region_urls(
            self.requested, bad, bad, "2292")
        self.assertEqual(proof["rendered"]["host"], "OTHER")
        self.assertEqual(proof["rendered"]["path"], "OTHER")
        self.assertNotIn("hidden-secret", repr(proof))
        self.assertNotIn("invalid.example", repr(proof))


if __name__ == "__main__":
    unittest.main()
