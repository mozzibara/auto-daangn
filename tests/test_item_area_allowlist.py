# -*- coding: utf-8 -*-
"""Synthetic region allowlist, exact-identity propagation and sealed privacy."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from app_v5.item_area_policy import (
    SCHEMA, load_allowlist, classify_area, configured_label,
    ALLOWED, OUTSIDE, UNKNOWN)
from app_v5.buy_now_policy import (
    PRESENT, NO_MARKER, LOCAL_RETAIN, OUTSIDE as BUY_OUTSIDE, HOLD,
    assess_configured_district)
from daangn_full_route_v4_14 import enhance_observed_fields
from daangn_detail_crosscheck_v4_20 import pick_samples
from daangn_state_controls_v4_23 import project_v428_diagnosis
from app_v5.sealed_import import validate_manifest
from daangn_secure_links_v4_34 import markdown_manifest

URL = "https://www.daangn.com/kr/buy-sell/test-abcdefghijkl/"


class AllowlistConfigTests(unittest.TestCase):
    def test_repository_default_is_explicit_not_city_wide(self):
        areas = load_allowlist()
        self.assertEqual({a["key"] for a in areas},
                         {"cheonan_buldang", "asan_baebang"})
        self.assertEqual(configured_label("cheonan_buldang"), "천안시 불당동")
        self.assertEqual(configured_label("asan_baebang"), "아산시 배방읍")
        self.assertIsNone(configured_label("private_or_unknown"))

    def test_custom_dong_eup_myeon_with_explicit_city(self):
        policy = self._read({
            "schema": SCHEMA, "allowed_areas": [
                {"key": "cheonan_dujeong", "city": "천안시",
                 "district": "두정동", "region_id": None},
                {"key": "asan_tangjeong", "city": "아산시",
                 "district": "탕정면", "region_id": None},
            ]
        })
        self.assertEqual(classify_area(
            {"name": "두정동", "city": {"name": "천안시"}}, policy)["status"],
            ALLOWED)
        self.assertEqual(classify_area(
            {"name": "탕정면", "municipality": "아산시"}, policy)["area_key"],
            "asan_tangjeong")
        self.assertEqual(classify_area(
            {"name": "두정동"}, policy)["status"], UNKNOWN)
        self.assertEqual(classify_area(
            {"name": "두정동", "city": "아산시"}, policy)["status"], OUTSIDE)

    def _read(self, data):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "areas.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return load_allowlist(path)

    def test_invalid_or_ambiguous_config_rejected(self):
        valid = {"schema": SCHEMA, "allowed_areas": [
            {"key": "cheonan_buldang", "city": "천안시",
             "district": "불당동", "region_id": "2292"}]}
        invalid = []
        dup = copy.deepcopy(valid)
        dup["allowed_areas"].append(dict(dup["allowed_areas"][0],key="other_key"))
        invalid.append(dup)
        for field, value in (
            ("city","천안시 전체"), ("district","천안시"),
            ("district","불당*"), ("region_id",True),
            ("region_id","000bad"), ("key","../../../private")
        ):
            obj=copy.deepcopy(valid)
            obj["allowed_areas"][0][field]=value
            invalid.append(obj)
        empty = copy.deepcopy(valid)
        empty["allowed_areas"]=[]
        invalid.append(empty)
        extra=copy.deepcopy(valid)
        extra["ignored"] = "no"
        invalid.append(extra)
        for idx,case in enumerate(invalid):
            with self.subTest(idx=idx), self.assertRaises(ValueError):
                self._read(case)


class ItemLocalityTests(unittest.TestCase):
    def setUp(self):
        self.areas=load_allowlist()

    def test_configured_area_both_cities_even_from_other_search_context(self):
        self.assertEqual(classify_area(
            {"id":2292,"name":"불당동"},self.areas)["area_key"],
            "cheonan_buldang")
        self.assertEqual(classify_area(
            {"id":"2333","name":"배방읍","city":{"name":"아산시"}},
            self.areas)["area_key"], "asan_baebang")

    def test_unapproved_districts_and_wrong_cities(self):
        self.assertEqual(classify_area(
            {"name":"두정동","city":{"name":"천안시"}},self.areas)["status"],
            OUTSIDE)
        self.assertEqual(classify_area(
            {"name":"불당동","city":"평택시"},self.areas)["status"],
            OUTSIDE)

    def test_missing_fields_are_not_guesstimated(self):
        for bad in (None, "", "천안시 불당동",
                    {"name":"불당동"}, {"id":2293}, {"city":"천안시"},
                    {"id":True,"city":"천안시","name":"불당동"},
                    {"id":2292,"name":"배방읍"},
                    {"id":2292,"city":"아산시","name":"불당동"},
                    {"id":9999,"city":"천안시","name":"불당동"},
                    {"id":9999,"name":"불당동"},
                    {"region":{"id":2292},"searchRegion":{"id":2292}},
                    {"id":2292,"city":"천안시","cityName":"아산시"}):
            with self.subTest(region=bad):
                self.assertEqual(classify_area(bad,self.areas)["status"],
                                 UNKNOWN)

    def test_order_matched_route_and_no_raw_region_leak(self):
        raw={"buySellArticles":[{"href":URL,"region":{
            "id":2333,"name":"배방읍","city":{"name":"아산시"}},
            "price":12000,"categoryId":None,"isSoldOut":None}],
            "searchRegion":{"id":2292}, "currentFilters":{"regionId":2292}}
        model={"articles":[{"href":URL,"price":12000,
                             "categoryId":None,"isSoldOut":None}]}
        result,shape=enhance_observed_fields(
            json.dumps(raw,ensure_ascii=False),model,
            expected_region={"id":"2292"},allowed_areas=self.areas,
            area_secret=b'0123456789abcdef0123456789abcdef')
        self.assertEqual(result["articles"][0]["item_area_status"],ALLOWED)
        self.assertEqual(result["articles"][0]["item_area_key"],"asan_baebang")
        self.assertEqual(shape["item_area_counts"][ALLOWED],1)
        self.assertNotIn("배방읍", json.dumps(result,ensure_ascii=False))
        self.assertNotIn("아산시", json.dumps(shape,ensure_ascii=False))
        samples=pick_samples(result,b"test_secret_32_bytes_for_digest_xxxx")
        self.assertEqual(len(samples),1)
        self.assertEqual(samples[0]["item_area_key"],"asan_baebang")
        self.assertRegex(samples[0]["item_area_token"],r'^[a-f0-9]{20}
        projected=project_v428_diagnosis({
            "source_rank":samples[0]["rank"],
            "same_listing_identity":True,
            "page_status":"HTTP_200_IDENTITY_MATCH",
            "v432_route_price_item_identity":True,
            "item_area_status":samples[0]["item_area_status"],
            "item_area_key":samples[0]["item_area_key"],
            "item_area_token":samples[0]["item_area_token"],
        })
        self.assertEqual(projected["item_area_status"],ALLOWED)
        self.assertEqual(projected["item_area_token"],samples[0]["item_area_token"])
        self.assertNotIn("item_area_key",projected)

    def test_wrong_article_identity_stops_area_projection(self):
        raw={"buySellArticles":[{"href":URL,"region":{"id":2292}}]}
        result,shape=enhance_observed_fields(
            json.dumps(raw),{"articles":[{"href":"/different"}]},
            allowed_areas=self.areas)
        self.assertIsNone(result)
        self.assertEqual(shape["status"],"MODEL_RAW_ROW_ORDER_MISMATCH")
        projected=project_v428_diagnosis({
            "source_rank":0, "same_listing_identity":False,
            "page_status":"HTTP_200_IDENTITY_MATCH",
            "v432_route_price_item_identity":True,
            "item_area_status":ALLOWED,"item_area_key":"cheonan_buldang",
            "item_area_token":"0"*20})
        self.assertEqual(projected["item_area_status"],UNKNOWN)
        self.assertIsNone(projected["item_area_token"])

    def test_buy_now_and_ordinary_share_same_district_gate(self):
        for buy_now in (PRESENT,NO_MARKER):
            self.assertEqual(assess_configured_district(
                buy_now,ALLOWED,"cheonan_buldang")["decision"],
                LOCAL_RETAIN if buy_now==PRESENT else
                "ORDINARY_ITEM_NOT_EXCLUDED")
            self.assertEqual(assess_configured_district(
                buy_now,UNKNOWN,None)["decision"],HOLD)
            self.assertEqual(assess_configured_district(
                buy_now,OUTSIDE,None)["decision"],BUY_OUTSIDE)
        self.assertEqual(assess_configured_district(
            PRESENT,ALLOWED,"nonexistent")["decision"],HOLD)


class PrivateManifestTests(unittest.TestCase):
    def manifest(self):
        return {
            "version":"4.34", "capture_scoped_only":True,
            "created_utc":"2026-11-12T01:00:00+00:00",
            "clickable_unique_count":1,
            "unlinked_title_quarantine_count":0,
            "source_run_unique_candidates":1,
            "items":[{
                "title":"가상 저장장치", "url":URL,
                "price_krw":20000, "category":"디지털기기",
                "availability":"판매 가능 추정","observation_count":1,
                "full_recommendation_approved":False,
                "seller_confirmed_available":False,
                "captured_from_current_primary_h1":True,
                "item_area_key":"cheonan_buldang",
                "item_area_display":"천안시 불당동",
            }], "unlinked_groups":[],
            "manual_current_price_and_status_recheck_required":True,
            "full_recommendations_approved":0
        }

    def test_private_manifest_location_accepted_and_rendered(self):
        self.assertEqual(len(validate_manifest(self.manifest())[0]),1)
        report=markdown_manifest(self.manifest())
        self.assertIn("천안시 불당동",report)
        self.assertIn("등록 동·읍·면",report)

    def test_tampered_or_unknown_location_rejected(self):
        for key,value in (("item_area_display","비밀주소"),
                          ("item_area_key","private_override")):
            m=self.manifest()
            m["items"][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_manifest(m)
        m=self.manifest()
        del m["items"][0]["item_area_key"]
        with self.assertRaises(ValueError):
            validate_manifest(m)

    def test_legacy_manifest_without_district_still_validates(self):
        m=self.manifest()
        del m["items"][0]["item_area_key"]
        del m["items"][0]["item_area_display"]
        self.assertEqual(len(validate_manifest(m)[0]),1)


if __name__ == "__main__":
    unittest.main()
)
        projected=project_v428_diagnosis({
            "source_rank":samples[0]["rank"],
            "same_listing_identity":True,
            "page_status":"HTTP_200_IDENTITY_MATCH",
            "v432_route_price_item_identity":True,
            "item_area_status":samples[0]["item_area_status"],
            "item_area_key":samples[0]["item_area_key"],
        })
        self.assertEqual(projected["item_area_key"],"asan_baebang")

    def test_wrong_article_identity_stops_area_projection(self):
        raw={"buySellArticles":[{"href":URL,"region":{"id":2292}}]}
        result,shape=enhance_observed_fields(
            json.dumps(raw),{"articles":[{"href":"/different"}]},
            allowed_areas=self.areas)
        self.assertIsNone(result)
        self.assertEqual(shape["status"],"MODEL_RAW_ROW_ORDER_MISMATCH")
        projected=project_v428_diagnosis({
            "source_rank":0, "same_listing_identity":False,
            "page_status":"HTTP_200_IDENTITY_MATCH",
            "v432_route_price_item_identity":True,
            "item_area_status":ALLOWED,"item_area_key":"cheonan_buldang"})
        self.assertEqual(projected["item_area_status"],UNKNOWN)
        self.assertIsNone(projected["item_area_key"])

    def test_buy_now_and_ordinary_share_same_district_gate(self):
        for buy_now in (PRESENT,NO_MARKER):
            self.assertEqual(assess_configured_district(
                buy_now,ALLOWED,"cheonan_buldang")["decision"],
                LOCAL_RETAIN if buy_now==PRESENT else
                "ORDINARY_ITEM_NOT_EXCLUDED")
            self.assertEqual(assess_configured_district(
                buy_now,UNKNOWN,None)["decision"],HOLD)
            self.assertEqual(assess_configured_district(
                buy_now,OUTSIDE,None)["decision"],BUY_OUTSIDE)
        self.assertEqual(assess_configured_district(
            PRESENT,ALLOWED,"nonexistent")["decision"],HOLD)


class PrivateManifestTests(unittest.TestCase):
    def manifest(self):
        return {
            "version":"4.34", "capture_scoped_only":True,
            "created_utc":"2026-11-12T01:00:00+00:00",
            "clickable_unique_count":1,
            "unlinked_title_quarantine_count":0,
            "source_run_unique_candidates":1,
            "items":[{
                "title":"가상 저장장치", "url":URL,
                "price_krw":20000, "category":"디지털기기",
                "availability":"판매 가능 추정","observation_count":1,
                "full_recommendation_approved":False,
                "seller_confirmed_available":False,
                "captured_from_current_primary_h1":True,
                "item_area_key":"cheonan_buldang",
                "item_area_display":"천안시 불당동",
            }], "unlinked_groups":[],
            "manual_current_price_and_status_recheck_required":True,
            "full_recommendations_approved":0
        }

    def test_private_manifest_location_accepted_and_rendered(self):
        self.assertEqual(len(validate_manifest(self.manifest())[0]),1)
        report=markdown_manifest(self.manifest())
        self.assertIn("천안시 불당동",report)
        self.assertIn("등록 동·읍·면",report)

    def test_tampered_or_unknown_location_rejected(self):
        for key,value in (("item_area_display","비밀주소"),
                          ("item_area_key","private_override")):
            m=self.manifest()
            m["items"][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_manifest(m)
        m=self.manifest()
        del m["items"][0]["item_area_key"]
        with self.assertRaises(ValueError):
            validate_manifest(m)

    def test_legacy_manifest_without_district_still_validates(self):
        m=self.manifest()
        del m["items"][0]["item_area_key"]
        del m["items"][0]["item_area_display"]
        self.assertEqual(len(validate_manifest(m)[0]),1)


if __name__ == "__main__":
    unittest.main()
