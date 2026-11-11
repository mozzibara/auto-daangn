"""v4.4 fail-closed gate, historical regression, and privacy tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daangn_v4_4_gate as g
import daangn_browser_v4_4 as cli


def article(i):
    return f"https://www.daangn.com/kr/buy-sell/a-test-hard-drive-{i:012d}/"


def sample(region, context, step, phase, first=1, count=50, valid=True):
    return g._record(version="4.4", run="unit", context=context, sequence=context,
                     step=step, region=region, phase=phase,
                     urls=[article(i) for i in range(first, first + count)],
                     dom=[article(i) for i in range(first, first + min(8, count))],
                     verified=valid, collector="boot_loader")


class TestURLs(unittest.TestCase):
    def test_listing_ids(self):
        self.assertEqual(g.stable_article_id(article(1)), "000000000001")
        self.assertEqual(g.stable_article_id(article(4)+"?ref=sample"), "000000000004")

    def test_reject_untrusted_host(self):
        self.assertIsNone(g.stable_article_id("https://daangn.com.evil.org/kr/buy-sell/x-123456789abc/"))
        self.assertIsNone(g.stable_article_id("https://www.daangn.com.evil.org/kr/buy-sell/x-123456789abc/"))
        self.assertIsNone(g.stable_article_id("https://www.daangn.com/kr/search/buy-sell/?q=HDD"))
        self.assertIsNone(g.stable_article_id("http://www.daangn.com/kr/buy-sell/x-123456789abc/"))
        self.assertIsNone(g.stable_article_id("https://www.daangn.com/kr/buy-sell/x-fakeid/"))
        self.assertIsNone(g.stable_article_id("javascript:alert(1)"))

    def test_hash_stability_query_change(self):
        base = article(45)
        self.assertEqual(g.hashed_listing_ids([base]), g.hashed_listing_ids([base+"?foo=bar"]))
        self.assertEqual(len(g.hashed_listing_ids([base,base])), 1)
        self.assertEqual(len(g.hashed_listing_ids(["not a listing"])), 0)

    def test_jaccard_sets(self):
        self.assertEqual(g.jaccard(["a", "b"], ["a", "b"]), 1.0)
        self.assertEqual(g.jaccard(["a"], ["b"]), 0.0)
        self.assertIsNone(g.jaccard([], []))


class TestGate(unittest.TestCase):
    def go(self, *samples):
        return g.apply_gate({"run":"unit", "version":"4.4", "samples":list(samples)})

    def test_exact_cold_collision_quarantines_both(self):
        a = sample("sadang", "x", 1, "cold_first")
        b = sample("cheonan", "y", 1, "cold_first")
        x = self.go(a,b)
        self.assertEqual(len(x["collisions"]), 1)
        self.assertTrue(all(d["verdict"] == "QUARANTINED_CROSS_REGION_IDENTICAL_COLD_SET" for d in x["decisions"]))

    def test_near_duplicate_cold_is_quarantined(self):
        a = sample("sadang", "x", 1, "cold_first", 0, 250)
        b = sample("cheonan", "y", 1, "cold_first", 1, 250)
        x = self.go(a,b)
        self.assertEqual(x["counts"]["QUARANTINED_CROSS_REGION_NEAR_DUPLICATE_COLD_SET"], 2)
        self.assertEqual(len(x["near_collisions"]), 1)

    def test_histogram_drift_optional(self):
        self.assertEqual(g.weighted_histogram_jaccard({"A":3,"B":1},{"A":3,"B":1}),1.0)
        self.assertEqual(g.weighted_histogram_jaccard({"A":3},{"B":3}),0.0)
        self.assertIsNone(g.weighted_histogram_jaccard({},{}))

    def test_not_quarantine_simply_249_items(self):
        a = sample("sadang", "x", 1, "cold_first", 0, 249)
        b = sample("cheonan", "y", 1, "cold_first", 500, 249)
        x = self.go(a,b)
        self.assertEqual(len(x["collisions"]), 0)
        self.assertTrue(all(d["verdict"] == "UNVERIFIED_COLD_FIRST" for d in x["decisions"]))

    def test_cold_repeat_outlier(self):
        cold = sample("asan", "c", 1, "cold_first", 0, 50)
        repeat = sample("asan", "c", 2, "same_url_repeat", 600, 50)
        x = self.go(cold,repeat)
        self.assertEqual(x["decisions"][0]["verdict"],"QUARANTINED_COLD_OR_SWITCH_OUTLIER")
        self.assertNotEqual(x["decisions"][1]["verdict"],"LIMITED_ACCEPT_REGIONAL_LISTING_SET")

    def test_switched_first_outlier(self):
        s = sample("cheonan", "x", 3, "region_switch_first", 2)
        r = sample("cheonan", "x", 4, "switched_url_repeat", 1000)
        x = self.go(s,r)
        self.assertEqual(x["decisions"][0]["verdict"],"QUARANTINED_COLD_OR_SWITCH_OUTLIER")

    def test_valid_same_context_not_enough(self):
        a = sample("sadang", "a", 1, "cold_first", 0)
        b = sample("sadang", "a", 2, "same_url_repeat", 0)
        x = self.go(a,b)
        self.assertEqual(x["decisions"][1]["verdict"], "UNVERIFIED_INDEPENDENT_CORROBORATION_MISSING")

    def test_accepted_only_with_independent_same_region_and_cross_different(self):
        a = sample("sadang", "a", 2, "same_url_repeat", 0)
        b = sample("sadang", "b", 4, "switched_url_repeat", 0)
        c = sample("cheonan", "c", 2, "same_url_repeat", 700)
        d = sample("cheonan", "d", 4, "switched_url_repeat", 700)
        x = self.go(a,b,c,d)
        self.assertEqual(x["counts"].get("LIMITED_ACCEPT_REGIONAL_LISTING_SET"), 4)
        self.assertTrue(all(x["decisions"][i]["allowed_for_price_analysis"] for i in range(4)))
        self.assertTrue(all(not d["verified_geographic_coverage"] for d in x["decisions"]))

    def test_repeat_same_across_regions_must_be_quarantined(self):
        a = sample("sadang", "a", 2, "same_url_repeat")
        b = sample("sadang", "b", 4, "switched_url_repeat")
        c = sample("cheonan", "c", 2, "same_url_repeat")
        d = sample("cheonan", "d", 4, "switched_url_repeat")
        x = self.go(a,b,c,d)
        self.assertEqual(x["counts"].get("QUARANTINED_CROSS_REGION_REPEAT_COLLISION"), 4)

    def test_single_region_no_approval(self):
        a = sample("sadang", "a", 2, "same_url_repeat")
        b = sample("sadang", "b", 4, "switched_url_repeat")
        x = self.go(a,b)
        self.assertTrue(all(d["verdict"] == "UNVERIFIED_CROSS_REGION_CONTROL_MISSING" for d in x["decisions"]))

    def test_invalid_dom_subset_or_region_rejected(self):
        a = sample("sadang", "a", 1, "cold_first")
        a["valid"] = False
        self.assertEqual(self.go(a)["decisions"][0]["verdict"], "QUARANTINED_INVALID_EVIDENCE")

    def test_invalid_missing_items(self):
        a = sample("sadang", "a", 1, "cold_first",valid=False)
        self.assertEqual(self.go(a)["decisions"][0]["verdict"], "QUARANTINED_INVALID_EVIDENCE")

    def test_no_false_collision_on_small_sets(self):
        a = sample("sadang", "a", 1, "cold_first",0,2)
        b = sample("cheonan", "b", 1, "cold_first",0,2)
        self.assertEqual(len(self.go(a,b)["collisions"]),0)

    def test_bad_signature_quarantines(self):
        a = sample("asan", "a", 2, "same_url_repeat")
        x = cli.gate_with_known({"samples":[a],"run":"x","version":"4.4"}, {a["set_sha256"]})
        self.assertEqual(x["decisions"][0]["verdict"], "QUARANTINED_HISTORICAL_CROSS_REGION_SIGNATURE")

    def test_partial_run_is_fail_closed(self):
        a=sample("sadang","a",2,"same_url_repeat",0)
        b=sample("sadang","b",4,"switched_url_repeat",0)
        c=sample("cheonan","c",2,"same_url_repeat",500)
        d=sample("cheonan","d",4,"switched_url_repeat",500)
        run={"run":"partial","version":"4.4","keyword":"HDD","samples":[a,b,c,d]}
        with tempfile.TemporaryDirectory() as temp:
            args=type("Args",(),{"output_dir":Path(temp)})()
            result=cli.emit_outputs(args, run, mode="live", status="STOP_ACCESS_RESTRICTED")
            self.assertEqual(sum(x["allowed_for_price_analysis"] for x in result["decisions"]),0)
            data=json.loads((Path(temp)/"daangn_browser_v4_4_limited_accept.json").read_text(encoding="utf-8"))
            self.assertEqual(data["samples"], [])

    def test_only_allowed_samples_export_public_urls(self):
        a = sample("sadang", "a", 2, "same_url_repeat", 0)
        b = sample("sadang", "b", 4, "switched_url_repeat", 0)
        c = sample("cheonan", "c", 2, "same_url_repeat", 500)
        d = sample("cheonan", "d", 4, "switched_url_repeat", 500)
        samples=[a,b,c,d]
        run={"run":"unit", "version":"4.4", "keyword":"HDD", "samples":samples}
        urls={x["sample_id"]:[article(1),
              "https://daangn.com.evil.org/kr/buy-sell/bad-123456789abc/"] for x in samples}
        with tempfile.TemporaryDirectory() as temp:
            args=type("Args",(),{"output_dir":Path(temp)})()
            cli.emit_outputs(args,run,mode="live",status="CAPTURED_COMPLETE",public_urls_by_sample=urls)
            result=json.loads((Path(temp)/"daangn_browser_v4_4_limited_accept.json").read_text(encoding="utf-8"))
            self.assertEqual(len(result["samples"]),4)
            self.assertTrue(all(x["public_listing_urls"]==[article(1)] for x in result["samples"]))
            self.assertNotIn("evil.org",json.dumps(result))

    def test_no_cookie_or_raw_url_persisted(self):
        s=sample("sadang","a",2,"same_url_repeat",0)
        s["client_state"]={"cookie_count_before":0,"cookie_count_after":10,"cookie_pair_sent":8}
        x=g.safe_compact_report({"run":"unit", "version":"4.4","samples":[s]}, self.go(s))
        blob=json.dumps(x)
        self.assertNotIn("https://",blob)
        self.assertNotIn("cookie_value",blob)
        self.assertNotIn("raw_cookie",blob)


# The original private repository also tested historic run-to-run matching
# against evidence/reference_runs.json. That file contains run-scoped listing
# fingerprints and must not become a public CI fixture. The synthetic
# collision/outlier/independent-replication cases above cover the algorithm
# without importing historical user observations.


if __name__=="__main__":
    unittest.main()
