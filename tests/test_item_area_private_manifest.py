# -*- coding: utf-8 -*-
"""No plaintext region leakage in public evidence or sealed shortlist."""
from __future__ import annotations

import base64
import json
import unittest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
from daangn_secure_links_v4_34 import (
    make_private_shortlist, seal_manifest, unseal_manifest)
from app_v5.item_area_policy import ALLOWED

URL="https://www.daangn.com/kr/buy-sell/test-abcdefghijkl/"
IDENTITY="a"*20
AREA_TOKEN="b"*20


def inputs():
    evaluation={
        "dedup_complete":True,
        "unique_candidate_count":1,
        "unique_candidates":[{
            "listing_run_hmac":IDENTITY,
            "observations":[{"context":"cheonan_a","source_rank":0}],
            "observation_count":1,
            "price_krw":20000,
            "status":"UNIQUE_RECOMMENDATION_CANDIDATE_READY_FOR_REVIEW",
            "category":"디지털기기",
            "display_sale_status":"판매 가능 추정",
            "item_area_token":AREA_TOKEN,
        }]
    }
    sink=[{
        "context":"cheonan_a", "source_rank":0,
        "listing_run_hmac":IDENTITY,"price_krw":20000,
        "url":URL,"title":"가상 저장장치",
        "title_status":"PRIMARY_H1_VERIFIED",
        "item_area_key":"cheonan_buldang",
        "item_area_status":ALLOWED,
        "item_area_token":AREA_TOKEN,
    }]
    return evaluation,sink


class PrivateLocalitySecurityTests(unittest.TestCase):
    def test_exact_district_only_inside_sealed_manifest(self):
        unique, sink=inputs()
        manifest=make_private_shortlist(unique,sink)
        self.assertEqual(manifest["clickable_unique_count"],1)
        self.assertEqual(manifest["items"][0]["item_area_display"],"천안시 불당동")
        self.assertEqual(manifest["items"][0]["item_area_key"],"cheonan_buldang")

        key=X25519PrivateKey.generate()
        public=base64.b64encode(key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw)).decode()
        envelope=seal_manifest(manifest,public)
        text=json.dumps(envelope,ensure_ascii=False)
        for secret in ("불당동","cheonan_buldang","가상 저장장치",URL):
            self.assertNotIn(secret,text)
        private=key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption())
        decrypted=unseal_manifest(envelope,private)
        self.assertEqual(decrypted["items"][0]["item_area_display"],
                         "천안시 불당동")

    def test_wrong_area_token_cannot_join_private_source(self):
        unique,sink=inputs()
        sink[0]["item_area_token"]="c"*20
        with self.assertRaisesRegex(ValueError,"PRIVATE_ITEM_AREA_IDENTITY_CONFLICT"):
            make_private_shortlist(unique,sink)

    def test_unknown_key_fails_and_cross_context_conflict_quarantines(self):
        unique,sink=inputs()
        sink[0]["item_area_key"]="not_a_configured_area"
        with self.assertRaisesRegex(ValueError,"PRIVATE_ITEM_AREA_IDENTITY_CONFLICT"):
            make_private_shortlist(unique,sink)
        unique,sink=inputs()
        unique["unique_candidates"][0]["observations"].append({
            "context":"cheonan_b","source_rank":32})
        unique["unique_candidates"][0]["observation_count"]=2
        other=dict(sink[0],context="cheonan_b",source_rank=32,
                   item_area_key="asan_baebang")
        sink.append(other)
        manifest=make_private_shortlist(unique,sink)
        self.assertEqual(manifest["clickable_unique_count"],0)
        self.assertEqual(manifest["unlinked_title_quarantine_count"],1)
        self.assertIn("CONFLICTING_ITEM_AREA_ACROSS_REPEATS",
                      manifest["unlinked_groups"][0]["reason_codes"])

    def test_legacy_manifest_without_location_still_supported(self):
        unique,sink=inputs()
        del unique["unique_candidates"][0]["item_area_token"]
        del sink[0]["item_area_key"]
        del sink[0]["item_area_status"]
        del sink[0]["item_area_token"]
        manifest=make_private_shortlist(unique,sink)
        self.assertNotIn("item_area_display",manifest["items"][0])


if __name__=="__main__":
    unittest.main()
