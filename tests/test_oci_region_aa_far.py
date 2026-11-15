# -*- coding: utf-8 -*-
"""Contract for independent Buldang A/A and distant Seoul control, offline only."""
import json
import unittest

from daangn_v4_1_core import BY_KEY
from app_v5.region_ab_sample import sample_region_articles
from app_v5.region_aa_far import RegionAAFarSession

SECRET = b"K" * 32
OK = {"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC", "route_status":"ONE_FRESH"}


def payload(key, labels, *, mismatch=False):
    rid = int(BY_KEY[key]["id"])
    node = {
        "searchRegion":{"id": rid},
        "currentFilters":{"regionId": 99999 if mismatch else rid},
        "buySellArticles":[
            {"href":f"/kr/buy-sell/{item}-abcdefghijkl/",
             "region":{"name":"SECRET_NEIGHBORHOOD"},
             "seller":"SECRET_SELLER", "title":"SECRET_TITLE"}
            for item in labels
        ],
    }
    return json.dumps({"loader":node}, ensure_ascii=False).encode()


def sample(key, items, *, mismatch=False):
    return sample_region_articles(payload(key,items,mismatch=mismatch),
                                  BY_KEY[key], SECRET,
                                  distant_control=(key=="sadang"))


class AAAndDistantTests(unittest.TestCase):
    def session(self, a, remote, a2, *, far_verified=True):
        s=RegionAAFarSession(secret=SECRET)
        s.accept("a1", sample("cheonan",a), verified=True)
        s.accept("far",sample("sadang",remote),verified=far_verified)
        s.accept("a2",sample("cheonan",a2),verified=True)
        return s.report({"a1":OK, "far":OK if far_verified else {},
                         "a2":OK})

    def test_aa_noise_and_far_clear_difference(self):
        r=self.session(["a","b","c"],["x","y","z"],["a","b","d"])
        self.assertEqual(r["status"],"OBSERVED")
        self.assertEqual(r["pairs"]["aa"]["overlap"],2)
        self.assertEqual(r["pairs"]["aa"]["symmetric_difference"],2)
        self.assertEqual(r["pairs"]["aa"]["jaccard"],0.5)
        self.assertEqual(r["pairs"]["a1_far"]["symmetric_difference"],6)
        self.assertEqual(r["pairs"]["a2_far"]["symmetric_difference"],6)
        self.assertEqual(r["contrast"]["verdict"],"FAR_EXCEEDS_OBSERVED_AA_DRIFT")
        self.assertEqual(r["contrast"]["aa_drift_count"],2)
        self.assertEqual(r["contrast"]["far_min_difference"],6)
        self.assertTrue(r["contrast"]["server_region_ids_distinct"])
        self.assertFalse(r["contrast"]["backend_geographic_scope_proven"])
        self.assertFalse(r["authorizes_listings"])
        data=json.dumps(r,ensure_ascii=False)
        for token in ("SECRET_","/kr/buy-sell/","abcdefghijkl", "2292", "334", "KKKK"):
            self.assertNotIn(token,data)

    def test_far_within_aa_noise_is_not_causal(self):
        r=self.session(["a","b","c"],["a","b","d"],["a","b","d"])
        self.assertEqual(r["contrast"]["verdict"],"FAR_WITHIN_OBSERVED_AA_DRIFT")
        self.assertFalse(r["contrast"]["backend_geographic_scope_proven"])

    def test_exact_same_sets_have_zero_baseline(self):
        r=self.session(["a","b"],["a","b"],["a","b"])
        self.assertEqual(r["pairs"]["aa"]["jaccard"],1.0)
        self.assertEqual(r["contrast"]["verdict"],"FAR_WITHIN_OBSERVED_AA_DRIFT")

    def test_far_failure_does_not_erase_valid_aa_baseline(self):
        r=self.session(["a","b","c"],["x"],["a","b","d"],
                       far_verified=False)
        self.assertEqual(r["status"],"INCOMPLETE")
        self.assertEqual(r["pairs"]["aa"]["symmetric_difference"],2)
        self.assertEqual(r["pairs"]["a1_far"]["symmetric_difference"],-1)
        self.assertEqual(r["contrast"]["verdict"],"INDETERMINATE")
        self.assertFalse(r["contrast"]["server_region_ids_distinct"])

    def test_mismatched_server_far_never_authorizes_set_comparison(self):
        s=RegionAAFarSession(secret=SECRET)
        s.accept("a1",sample("cheonan",["a"]),verified=True)
        bad=sample("sadang",["s"],mismatch=True)
        self.assertEqual(bad["summary"]["status"],"SERVER_REGION_CONFLICT")
        s.accept("far",bad,verified=True)
        s.accept("a2",sample("cheonan",["a"]),verified=True)
        result=s.report({"a1":OK,"far":OK,"a2":OK})
        self.assertEqual(result["pairs"]["aa"]["overlap"],1)
        self.assertEqual(result["contrast"]["verdict"],"INDETERMINATE")

    def test_invalid_or_duplicate_identity_fail_closed(self):
        s=RegionAAFarSession(secret=SECRET)
        s.accept("a1",sample("cheonan",["a","a"]),verified=True)
        s.accept("far",sample("sadang",["s"]),verified=True)
        s.accept("a2",sample("cheonan",["a"]),verified=True)
        result=s.report({"a1":OK,"far":OK,"a2":OK})
        self.assertEqual(result["pairs"]["aa"]["overlap"],-1)
        self.assertEqual(result["contrast"]["verdict"],"INDETERMINATE")

    def test_sadang_only_allowed_with_explicit_region_probe_flag(self):
        self.assertEqual(sample_region_articles(
            payload("sadang",["x"]),BY_KEY["sadang"],SECRET)["summary"]["status"],
                         "UNOBSERVABLE")
        self.assertEqual(sample_region_articles(
            payload("sadang",["x"]),BY_KEY["sadang"],SECRET,
            distant_control=True)["summary"]["status"],"COMPLETE")

    def test_reject_duplicate_arms_and_invalid_secrets(self):
        with self.assertRaises(ValueError):
            RegionAAFarSession(secret=b"bad")
        s=RegionAAFarSession(secret=SECRET)
        with self.assertRaises(ValueError):
            s.accept("unexpected",{},verified=True)
        s.accept("a1", sample("cheonan",["a"]),verified=True)
        with self.assertRaises(ValueError):
            s.accept("a1", sample("cheonan",["b"]),verified=True)


if __name__=="__main__":
    unittest.main()
