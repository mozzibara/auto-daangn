# -*- coding: utf-8 -*-
"""Synthetic private policy binding contract."""
import base64
import json
import unittest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
from app_v5.item_area_policy import ALLOWED
from app_v5.sealed_import import validate_manifest
from daangn_secure_links_v4_34 import (
    make_private_shortlist, seal_manifest, unseal_manifest, markdown_manifest,
)


def inputs():
    tag, token = "a" * 20, "b" * 20
    unique = {"dedup_complete": True, "unique_candidate_count": 1,
              "unique_candidates": [{
                  "listing_run_hmac": tag, "observations": [
                      {"context": "cheonan_a", "source_rank": 0}],
                  "observation_count": 1, "price_krw": 20000,
                  "status": "UNIQUE_RECOMMENDATION_CANDIDATE_READY_FOR_REVIEW",
                  "category": "디지털기기", "display_sale_status": "판매 가능 추정",
                  "item_area_token": token}]}
    sink = [{"context": "cheonan_a", "source_rank": 0,
             "listing_run_hmac": tag, "price_krw": 20000,
             "url": "https://www.daangn.com/kr/buy-sell/test-abcdefghijkl/",
             "title": "가상 저장장치", "title_status": "PRIMARY_H1_VERIFIED",
             "item_area_key": "test_a", "item_area_status": ALLOWED,
             "item_area_token": token}]
    return unique, sink


class BoundPrivatePolicyTests(unittest.TestCase):
    def policy(self):
        return (
            dict(key="test_a", city="서울특별시", borough="동작구",
                 district="가상동", region_id="900001"),
            dict(key="test_b", city="아산시", borough=None,
                 district="가상면", region_id="900002"),
        )

    def bound_manifest(self):
        return make_private_shortlist(*inputs(), area_policy=self.policy())

    def test_explicit_policy_bound_to_private_manifest_and_rendering(self):
        manifest = self.bound_manifest()
        self.assertRegex(manifest["item_area_policy_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(manifest["items"][0]["item_area_display"],
                         "서울특별시 동작구 가상동")
        self.assertEqual(len(validate_manifest(
            manifest, area_policy=tuple(reversed(self.policy())))[0]), 1)
        self.assertIn("서울특별시 동작구 가상동",
                      markdown_manifest(manifest, area_policy=self.policy()))
        with self.assertRaises(ValueError):
            validate_manifest(manifest)
        with self.assertRaises(ValueError):
            markdown_manifest(manifest)

    def test_changed_or_missing_policy_binding_rejected(self):
        manifest = self.bound_manifest()
        changed = tuple(dict(row, region_id="900003") if row["key"] == "test_a"
                        else row for row in self.policy())
        with self.assertRaises(ValueError):
            validate_manifest(manifest, area_policy=changed)
        del manifest["item_area_policy_sha256"]
        with self.assertRaises(ValueError):
            validate_manifest(manifest, area_policy=self.policy())

    def test_bound_policy_requires_item_location_and_no_null_label(self):
        manifest = self.bound_manifest()
        del manifest["items"][0]["item_area_key"]
        del manifest["items"][0]["item_area_display"]
        with self.assertRaises(ValueError):
            validate_manifest(manifest, area_policy=self.policy())
        unique, sink = inputs()
        unique["unique_candidates"][0].pop("item_area_token")
        for field in ("item_area_token", "item_area_key", "item_area_status"):
            sink[0].pop(field)
        with self.assertRaises(ValueError):
            make_private_shortlist(unique, sink, area_policy=self.policy())
        legacy = make_private_shortlist(unique, sink)
        legacy["items"][0]["item_area_key"] = "unknown_key"
        legacy["items"][0]["item_area_display"] = None
        with self.assertRaises(ValueError):
            validate_manifest(legacy)

    def test_policy_digest_is_inside_ciphertext_not_envelope_metadata(self):
        manifest = self.bound_manifest()
        key = X25519PrivateKey.generate()
        public = base64.b64encode(key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        envelope = seal_manifest(manifest, public)
        self.assertNotIn("item_area_policy_sha256", envelope)
        self.assertNotIn(manifest["item_area_policy_sha256"], json.dumps(envelope))
        private = key.private_bytes(serialization.Encoding.Raw,
                                    serialization.PrivateFormat.Raw,
                                    serialization.NoEncryption())
        decrypted = unseal_manifest(envelope, private)
        self.assertEqual(len(validate_manifest(
            decrypted, area_policy=self.policy())[0]), 1)


if __name__ == "__main__":
    unittest.main()
