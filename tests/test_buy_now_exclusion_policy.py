# -*- coding: utf-8 -*-
"""Offline current-item buy-now exclusion and no-location-inference regressions."""
import json
import unittest
from unittest.mock import patch

from app_v5.buy_now_policy import (
    classify_source_buy_now, EXCLUDED, NO_MARKER, UNVERIFIED)
from daangn_for_sale_ui_v4_28 import COUNTERS, sanitize, UI_JS
from daangn_sale_filter_v4_31 import (
    assess_source, _valid_diag, PASS, BLOCK_BUY_NOW, UNKNOWN, PHASES)


def diag(*, labels=0, ctas=0, complete=True, status="NO_DIRECT_FOR_SALE_UI"):
    probe = {name: 0 for name in COUNTERS}
    probe.update(scan_complete=complete, primary_valid=True,
                 status=status, primary_buy_now_label=labels,
                 primary_purchase_cta=ctas)
    return {
        "role": "SOURCE", "dom_capture_status": "CAPTURED", "probe": probe,
        "phases": {name: {
            "same_document_url": True,
            "scan_complete": True,
            "primary_heading_visible": True,
            "ui": "NOT_OBSERVABLE",
            "primary_exact_tokens": 0,
            "primary_visible_exact_tokens": 0,
            "primary_nonvisible_exact_tokens": 0,
        } for name in PHASES},
    }


def model():
    return {
        "context_kind": "SOURCE",
        "primary_transaction_status": "NOT_OBSERVABLE",
        "identity_confirmed": True, "render_complete": True,
        "independent_evidence_tier": "METADATA_ONLY_NO_TRANSACTION_PROOF",
        "product_jsonld_exact_availability": "IN_STOCK",
        "product_jsonld_stock_class": "AVAILABLE",
    }


class BuyNowUiTests(unittest.TestCase):
    def test_visible_primary_labels_are_observed_in_ui_script(self):
        self.assertIn("primary_buy_now_label", COUNTERS)
        self.assertIn("바로구매", UI_JS)
        self.assertIn("related", UI_JS)
        self.assertIn("primary_purchase_cta", COUNTERS)

    def test_sanitization_accepts_only_bounded_count_no_raw_text(self):
        record = {name: 0 for name in COUNTERS}
        record.update(scan_complete=True, primary_valid=True,
                      primary_buy_now_label=1,
                      leaked_location="PRIVATE_ADDRESS", leaked_url="https://secret")
        safe = sanitize(record)
        self.assertEqual(safe["primary_buy_now_label"], 1)
        self.assertNotIn("PRIVATE", json.dumps(safe))
        self.assertNotIn("leaked", json.dumps(safe))

    def test_exact_label_or_purchase_button_excludes(self):
        for kw in (dict(labels=1), dict(ctas=1), dict(labels=2,ctas=2)):
            with self.subTest(kw=kw):
                result=classify_source_buy_now(diag(**kw))
                self.assertEqual(result["status"], EXCLUDED)
                self.assertTrue(result["buy_now_detected"])
                self.assertFalse(result["buyer_choice_eligible"])
                self.assertFalse(result["item_location_verified"])

    def test_missing_or_incomplete_evidence_is_not_a_pass(self):
        for source in (None, {}, diag(complete=False),
                       {"role": "SOURCE", "dom_capture_status": "CAPTURED",
                        "probe": {"primary_valid": True,
                                  "scan_complete": True,
                                  "primary_purchase_cta": 0}}):
            result=classify_source_buy_now(source)
            self.assertEqual(result["status"], UNVERIFIED)
            self.assertFalse(result["buyer_choice_eligible"])

    def test_visible_absence_does_not_establish_actual_location(self):
        result=classify_source_buy_now(diag())
        self.assertEqual(result["status"], NO_MARKER)
        self.assertTrue(result["buyer_choice_eligible"])
        self.assertFalse(result["item_location_verified"])
        self.assertFalse(result["absence_is_location_proof"])
        self.assertFalse(result["search_region_gate_overridden"])
        self.assertFalse(result["authorizes_listings"])

    def test_malicious_noninteger_counter_is_not_allowed(self):
        d=diag()
        d["probe"]["primary_buy_now_label"]=True
        self.assertEqual(classify_source_buy_now(d)["status"],UNVERIFIED)
        d["probe"]["primary_buy_now_label"]="SECRET_ADDRESS"
        self.assertEqual(classify_source_buy_now(d)["status"],UNVERIFIED)


class V431IntegrationTests(unittest.TestCase):
    def test_complete_no_marker_can_pass_existing_sale_gate(self):
        self.assertTrue(_valid_diag(diag()))
        with patch("daangn_sale_filter_v4_31.clean_record", return_value=model()):
            result=assess_source({},diagnostic=diag())
        self.assertEqual(result["sale_filter_status"], PASS)
        self.assertTrue(result["sale_filter_eligible"])
        self.assertFalse(result["full_recommendation_approved"])

    def test_buy_now_is_blocked_before_stock_sale_candidate(self):
        with patch("daangn_sale_filter_v4_31.clean_record", return_value=model()):
            for case in (diag(labels=1),diag(ctas=1)):
                item=assess_source({},diagnostic=case)
                self.assertEqual(item["sale_filter_status"], BLOCK_BUY_NOW)
                self.assertFalse(item["sale_filter_eligible"])
                self.assertFalse(item["full_recommendation_approved"])

    def test_legacy_missing_marker_fails_closed(self):
        d=diag()
        del d["probe"]["primary_buy_now_label"]
        self.assertFalse(_valid_diag(d))
        with patch("daangn_sale_filter_v4_31.clean_record", return_value=model()):
            result=assess_source({},diagnostic=d)
        self.assertEqual(result["sale_filter_status"],UNKNOWN)
        self.assertFalse(result["sale_filter_eligible"])


if __name__ == "__main__":
    unittest.main()
