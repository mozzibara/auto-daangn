# -*- coding: utf-8 -*-
"""Offline regression for retained local Buy Now and item-specific locality."""
import json
import unittest
from unittest.mock import patch

from app_v5.buy_now_policy import (
    classify_source_buy_now, assess_local_buy_now,
    PRESENT, NO_MARKER, UNVERIFIED, LOCAL_RETAIN, HOLD, OUTSIDE)
from app_v5.listing_locality import (
    classify_item_region, LOCAL_EXACT, LOCAL_CITY, OUTSIDE_CITY,
    UNVERIFIED as LOCATION_UNVERIFIED)
from app_v5.item_area_policy import (
    ALLOWED as AREA_ALLOWED, OUTSIDE as AREA_OUTSIDE, UNKNOWN as AREA_UNKNOWN,
)
from daangn_for_sale_ui_v4_28 import COUNTERS, sanitize, UI_JS
from daangn_full_route_v4_14 import enhance_observed_fields
from daangn_state_controls_v4_23 import project_v428_diagnosis
from daangn_sale_filter_v4_31 import (
    assess_source, _valid_diag, PASS, BLOCK_OUTSIDE, HOLD_LOCALITY,
    UNKNOWN, PHASES)


def diag(*, labels=0, ctas=0, locality=LOCAL_EXACT,
         complete=True, status="NO_DIRECT_FOR_SALE_UI"):
    probe = {name: 0 for name in COUNTERS}
    probe.update(scan_complete=complete, primary_valid=True,
                 status=status, primary_buy_now_label=labels,
                 primary_purchase_cta=ctas)
    area=(AREA_ALLOWED if locality in (LOCAL_EXACT,LOCAL_CITY) else
          AREA_OUTSIDE if locality==OUTSIDE_CITY else AREA_UNKNOWN)
    return {
        "role": "SOURCE", "dom_capture_status": "CAPTURED",
        "probe": probe, "item_locality_status": locality,
        "item_area_status":area,
        "item_area_token":"a"*20 if area==AREA_ALLOWED else None,
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


def assess(d):
    with patch("daangn_sale_filter_v4_31.clean_record", return_value=model()):
        return assess_source({}, diagnostic=d)


class ItemRegionEvidenceTests(unittest.TestCase):
    TARGET = {"id": "2292", "term": "불당동", "label": "천안"}

    def test_exact_region_id_and_same_city(self):
        self.assertEqual(classify_item_region(
            {"id": 2292, "name": "불당동"}, self.TARGET), LOCAL_EXACT)
        self.assertEqual(classify_item_region(
            {"id": 99999, "name": "두정동",
             "city": {"name": "천안시"}}, self.TARGET), LOCAL_CITY)

    def test_different_neighborhood_id_alone_does_not_imply_remote(self):
        self.assertEqual(classify_item_region(
            {"id": 99999, "name": "두정동"}, self.TARGET),
            LOCATION_UNVERIFIED)

    def test_explicit_city_mismatch_and_contradiction(self):
        self.assertEqual(classify_item_region(
            {"id": 99999, "city": {"name": "아산시"}}, self.TARGET),
            OUTSIDE_CITY)
        self.assertEqual(classify_item_region(
            {"id": 2292, "city": "아산시"}, self.TARGET),
            LOCATION_UNVERIFIED)

    def test_never_use_free_form_address_title_or_query_location(self):
        self.assertEqual(classify_item_region(
            "천안시 불당동", self.TARGET), LOCATION_UNVERIFIED)
        self.assertEqual(classify_item_region(
            {"sellerAddress":"천안시 불당동",
             "searchRegion":{"id":"2292"}},self.TARGET),
            LOCATION_UNVERIFIED)
        self.assertEqual(classify_item_region(
            {"id": True, "name":"불당동"},self.TARGET),
            LOCATION_UNVERIFIED)

    def test_identical_route_row_locality_is_enum_only(self):
        href="https://www.daangn.com/kr/buy-sell/example-AbCdEf123456/"
        original={"buySellArticles":[{
            "href":href, "categoryId":1, "isSoldOut":False, "price":"10000",
            "region":{"id":2292, "city":{"name":"천안시"}}
        }], "searchRegion":{"id":"999"}}
        model_route={"articles":[{"href":href, "categoryId":1,
                                  "isSoldOut":False, "price":"10000"}]}
        result,shape=enhance_observed_fields(
            json.dumps(original, ensure_ascii=False).encode(), model_route,
            expected_region=self.TARGET)
        self.assertEqual(result["articles"][0]["item_locality_status"],
                         LOCAL_EXACT)
        self.assertEqual(shape["item_locality_counts"][LOCAL_EXACT],1)
        self.assertNotIn("천안", json.dumps(shape,ensure_ascii=False))
        self.assertNotIn("city", json.dumps(result,ensure_ascii=False))

    def test_route_item_order_mismatch_aborts(self):
        raw=json.dumps({"buySellArticles":[{"href":"/first",
                                            "region":{"id":2292}}]})
        model_route={"articles":[{"href":"/second"}]}
        result,shape=enhance_observed_fields(
            raw, model_route, expected_region=self.TARGET)
        self.assertIsNone(result)
        self.assertEqual(shape["status"],"MODEL_RAW_ROW_ORDER_MISMATCH")

    def test_locality_projects_only_after_exact_detail_identity(self):
        item={
            "source_rank":1,
            "same_listing_identity":True,
            "page_status":"HTTP_200_IDENTITY_MATCH",
            "v432_route_price_item_identity":True,
            "v435_route_item_locality_status":LOCAL_EXACT,
        }
        self.assertEqual(project_v428_diagnosis(item)["item_locality_status"],
                         LOCAL_EXACT)
        item["same_listing_identity"]=False
        self.assertEqual(project_v428_diagnosis(item)["item_locality_status"],
                         LOCATION_UNVERIFIED)


class BuyNowUiTests(unittest.TestCase):
    def test_visible_exact_buy_now_and_no_raw_text(self):
        self.assertIn("primary_buy_now_label", COUNTERS)
        self.assertIn("바로구매", UI_JS)
        record = {name: 0 for name in COUNTERS}
        record.update(scan_complete=True, primary_valid=True,
                      primary_buy_now_label=1,
                      leaked_location="PRIVATE_ADDRESS", leaked_url="https://secret")
        safe = sanitize(record)
        self.assertEqual(safe["primary_buy_now_label"], 1)
        self.assertNotIn("PRIVATE", json.dumps(safe))
        self.assertNotIn("leaked", json.dumps(safe))

    def test_buy_now_is_not_remote(self):
        self.assertEqual(classify_source_buy_now(diag(labels=1))["status"],
                         PRESENT)
        self.assertEqual(assess_local_buy_now(PRESENT, LOCAL_EXACT)["decision"],
                         LOCAL_RETAIN)
        self.assertEqual(assess_local_buy_now(PRESENT, LOCAL_CITY)["decision"],
                         LOCAL_RETAIN)

    def test_generic_purchase_cta_does_not_prove_buy_now(self):
        self.assertEqual(classify_source_buy_now(diag(ctas=1))["status"],
                         UNVERIFIED)

    def test_missing_evidence_is_not_location_proof(self):
        for d in (None, {}, diag(complete=False)):
            result=classify_source_buy_now(d)
            self.assertEqual(result["status"],UNVERIFIED)
        self.assertEqual(classify_source_buy_now(diag())["status"],
                         NO_MARKER)
        self.assertFalse(classify_source_buy_now(diag())["item_location_verified"])

    def test_bad_counts_and_invalid_location_are_quarantined(self):
        d=diag(labels=1)
        d["probe"]["primary_buy_now_label"]=True
        self.assertEqual(classify_source_buy_now(d)["status"],UNVERIFIED)
        self.assertEqual(assess_local_buy_now(PRESENT,"PRIVATE_ADDRESS")["decision"],
                         HOLD)


class V431IntegrationTests(unittest.TestCase):
    def test_local_buy_now_is_not_blanket_excluded(self):
        for location in (LOCAL_EXACT, LOCAL_CITY):
            d=diag(labels=1,locality=location)
            self.assertTrue(_valid_diag(d))
            result=assess(d)
            self.assertEqual(result["sale_filter_status"],PASS)
            self.assertTrue(result["sale_filter_eligible"])
            self.assertFalse(result["full_recommendation_approved"])

    def test_buy_now_remote_explicitly_blocked(self):
        result=assess(diag(labels=1,locality=OUTSIDE_CITY))
        self.assertEqual(result["sale_filter_status"],BLOCK_OUTSIDE)
        self.assertFalse(result["sale_filter_eligible"])

    def test_buy_now_unknown_location_is_held_not_excluded(self):
        result=assess(diag(labels=1,locality=LOCATION_UNVERIFIED))
        self.assertEqual(result["sale_filter_status"],HOLD_LOCALITY)
        self.assertFalse(result["sale_filter_eligible"])
        self.assertNotEqual(result["display_status"],"바로구매 제외")

    def test_non_buy_now_default_policy_remains(self):
        d=diag()
        self.assertTrue(_valid_diag(d))
        result=assess(d)
        self.assertEqual(result["sale_filter_status"],PASS)

    def test_even_ordinary_verified_remote_is_blocked(self):
        result=assess(diag(locality=OUTSIDE_CITY))
        self.assertEqual(result["sale_filter_status"],BLOCK_OUTSIDE)

    def test_legacy_missing_marker_fails_closed(self):
        d=diag()
        del d["probe"]["primary_buy_now_label"]
        self.assertFalse(_valid_diag(d))
        self.assertEqual(assess(d)["sale_filter_status"],HOLD_LOCALITY)

    def test_local_does_not_confirm_direct_trade_or_search_route(self):
        result=assess_local_buy_now(PRESENT,LOCAL_EXACT)
        self.assertFalse(result["direct_trade_confirmed"])
        self.assertFalse(result["search_region_gate_overridden"])
        self.assertFalse(result["authorizes_listings"])


if __name__ == "__main__":
    unittest.main()
