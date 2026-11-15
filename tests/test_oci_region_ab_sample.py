"""Synthetic-only privacy and completeness contracts for two-region comparison."""
import json
import unittest

from app_v5.region_ab_sample import RegionABSession, sample_region_articles
from daangn_v4_1_core import BY_KEY


def payload(region_id, items, *, filter_id=None, duplicate=False):
    node = {
        "searchRegion": {"id": region_id},
        "currentFilters": {"regionId": region_id if filter_id is None else filter_id},
        "buySellArticles": items,
    }
    return json.dumps({"loader":[node,node] if duplicate else [node]},
                      ensure_ascii=False).encode("utf-8")


def item(url, region):
    return {"href": "/kr/buy-sell/" + url + "-abcdef1234/",
            "region": region,
            "seller": "SECRET_SELLER", "title": "SECRET_TITLE"}


class RegionSampleTests(unittest.TestCase):
    def setUp(self):
        self.salt=b"S"*32
        self.cheonan=BY_KEY["cheonan"]
        self.asan=BY_KEY["asan"]

    def test_same_item_region_is_not_search_region_and_ids_not_exported(self):
        rows=[
            item("one", {"id":2292,"name":"불당동","city":{"name":"천안시"}}),
            item("two", {"id":2333,"name":"배방읍","city":{"name":"아산시"}}),
            item("three", {"name":"두정동"}),
        ]
        result=sample_region_articles(payload(2292,rows),self.cheonan,self.salt)
        self.assertEqual(result["summary"]["status"],"COMPLETE")
        self.assertEqual(result["summary"]["rows"],3)
        self.assertEqual(result["summary"]["local_exact"],1)
        self.assertEqual(result["summary"]["outside_city"],1)
        self.assertEqual(result["summary"]["unverified"],1)
        self.assertEqual(result["summary"]["identity_coverage"],"COMPLETE")
        text=json.dumps(result["summary"],ensure_ascii=False)
        for sensitive in ("SECRET","2292","2333","천안","아산","불당","/kr/"):
            self.assertNotIn(sensitive,text)

    def test_server_region_conflict_blocks_sample(self):
        sample=sample_region_articles(payload(2292,[item("one",{"id":2292})],
                                                   filter_id=2333),
                                      self.cheonan,self.salt)
        self.assertEqual(sample["summary"]["status"],"SERVER_REGION_CONFLICT")
        self.assertEqual(sample["tokens"],frozenset())

    def test_invalid_duplicate_and_bad_identity_fail_closed(self):
        valid=item("one",{"id":2292})
        duplicate=sample_region_articles(payload(2292,[valid,valid]),
                                         self.cheonan,self.salt)
        self.assertEqual(duplicate["summary"]["identity_coverage"],"INCOMPLETE")
        self.assertEqual(sample_region_articles(
            payload(2292,[valid],duplicate=True),self.cheonan,self.salt)[
                "summary"]["status"],"AMBIGUOUS_MODEL")
        self.assertEqual(sample_region_articles(
            payload(2292,[{"href":"https://private.invalid/SECRET","region":{"id":2292}}]),
            self.cheonan,self.salt)["summary"]["identity_coverage"],
            "INCOMPLETE")
        self.assertEqual(sample_region_articles(b"SECRET",self.cheonan,self.salt)[
            "summary"]["status"],"UNOBSERVABLE")

    def test_bounded_and_absent_location(self):
        rows=[item("i"+str(i),{}) for i in range(651)]
        v=sample_region_articles(payload(2292,rows),self.cheonan,self.salt)
        self.assertEqual(v["summary"]["status"],"TOO_MANY_ROWS")
        v=sample_region_articles(payload(2292,[item("one",{})]),
                                 self.cheonan,self.salt)
        self.assertEqual(v["summary"]["unverified"],1)
        self.assertEqual(v["summary"]["location_coverage"],"NONE")

    def test_two_fresh_arms_report_aggregate_only_and_detect_overlap(self):
        session=RegionABSession(secret=self.salt)
        a=sample_region_articles(payload(2292,[
            item("one",{"id":2292}),item("common",{"id":2292})]),
            self.cheonan,self.salt)
        b=sample_region_articles(payload(2333,[
            item("two",{"id":2333}),item("common",{"id":2292})]),
            self.asan,self.salt)
        session.accept("cheonan",a,verified=True)
        session.accept("asan",b,verified=True)
        result=session.summarize({"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
                                  "route_status":"ONE_FRESH"},
                                 {"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
                                  "route_status":"ONE_FRESH"})
        self.assertEqual(result["comparison"]["overlap"],1)
        self.assertEqual(result["comparison"]["left_only"],1)
        self.assertEqual(result["comparison"]["right_only"],1)
        self.assertEqual(result["comparison"]["verdict"],"PARTIAL_OVERLAP")
        self.assertTrue(result["comparison"]["response_region_ids_distinct"])
        self.assertFalse(result["authorizes_listings"])
        text=json.dumps(result)
        for secret in ("SECRET","abcdef1234","/kr/buy-sell","S"*32):
            self.assertNotIn(secret,text)

    def test_partial_identity_or_unverified_arm_not_promoted(self):
        session=RegionABSession(secret=self.salt)
        a=sample_region_articles(payload(2292,[item("one",{"id":2292})]),
                                 self.cheonan,self.salt)
        b=sample_region_articles(payload(2333,[{"region":{"id":2333}}]),
                                 self.asan,self.salt)
        session.accept("cheonan",a,verified=True)
        session.accept("asan",b,verified=True)
        result=session.summarize({"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
                                  "route_status":"ONE_FRESH"},
                                 {"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
                                  "route_status":"ONE_FRESH"})
        self.assertEqual(result["comparison"]["verdict"],"INDETERMINATE")
        self.assertFalse(result["comparison"]["full_result_set_proven"])
        self.assertFalse(result["authorizes_listings"])

    def test_only_known_regions_and_secret_allowed(self):
        for region in ({"id":"2292"},BY_KEY["sadang"],None):
            with self.subTest(region=region):
                self.assertEqual(sample_region_articles(payload(2292,[]),
                         region,self.salt)["summary"]["status"],"UNOBSERVABLE")
        with self.assertRaises(ValueError):
            RegionABSession(secret=b"bad")


if __name__=="__main__":
    unittest.main()
