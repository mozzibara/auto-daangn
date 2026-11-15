# -*- coding: utf-8 -*-
"""No-site tests for three-arm owner gate and browser stage sequencing."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app_v5.region_ab_sample import sample_region_articles
from daangn_v4_1_core import BY_KEY
from ops.oci.region_aa_far import run, _APPROVAL


class DummyChrome:
    async def launch(self, **kwargs):
        return SimpleNamespace(close=self.close)
    async def close(self):
        return None


class DummyPW:
    async def __aenter__(self):
        return SimpleNamespace(chromium=DummyChrome())
    async def __aexit__(self, *args):
        return None


def sample_payload(region, suffix):
    rid = BY_KEY[region]["id"]
    return json.dumps({
        "data": {
            "searchRegion":{"id":rid},
            "currentFilters":{"regionId":rid},
            "buySellArticles":[{
                "href":f"/kr/buy-sell/{suffix}-abcdef123456/",
                "region":{"name":"NEIGHBORHOOD_SECRET"},
                "seller":"SELLER_SECRET"}
            ],
        },
    }).encode()


class OwnerGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_unapproved_does_not_even_check_environment(self):
        invoked=[]
        def bad(*args,**kwargs):
            invoked.append(True)
            raise RuntimeError("MUST_NOT_RUN")
        r=await run(live=True,headed=True,approval="BAD",
                    directory_check=bad,robots=bad,picker_robots=bad)
        self.assertEqual(r["status"],"OWNER_APPROVAL_REQUIRED")
        self.assertEqual(invoked,[])
        self.assertFalse(r["authorizes_listings"])

    async def test_distant_robots_failure_blocks_before_browser(self):
        terms=[]
        def picker(term):
            terms.append(term)
            return {"allowed": term=="불당동"}
        r=await run(live=True,headed=True,approval=_APPROVAL,
                    directory_check=lambda:True,robots=lambda:True,
                    picker_robots=picker)
        self.assertEqual(r["status"],"ROBOTS_NOT_ALLOWED")
        self.assertEqual(terms,["불당동","사당제3동"])

    async def test_three_separate_ui_arms_without_manual_route_fetch(self):
        seen=[]
        async def fake_region(browser,mode,*,region_key,region_ab_session,
                              region_diagnostic_arm_key,**kwargs):
            seen.append((region_diagnostic_arm_key,region_key,mode))
            region_ab_session.accept(
                region_diagnostic_arm_key,
                sample_region_articles(
                    sample_payload(region_key,region_diagnostic_arm_key),
                    BY_KEY[region_key], region_ab_session.secret,
                    distant_control=region_key=="sadang"),
                verified=True)
            return {"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
                    "route_status":"ONE_FRESH"}
        with patch("playwright.async_api.async_playwright",return_value=DummyPW()),patch(
            "ops.oci.region_aa_far.one_public_region",new=fake_region):
            r=await run(live=True,headed=True,approval=_APPROVAL,
                        directory_check=lambda:True,robots=lambda:True,
                        picker_robots=lambda _:{"allowed":True})
        self.assertEqual(seen,[("a1","cheonan","FILL"),("far","sadang","FILL"),
                               ("a2","cheonan","FILL")])
        self.assertEqual(r["status"],"OBSERVED")
        self.assertEqual(r["pairs"]["aa"]["symmetric_difference"],2)
        self.assertFalse(r["authorizes_listings"])
        self.assertFalse(r["collection_started"])

    async def test_far_header_failure_does_not_erase_aa_baseline(self):
        seen=[]
        async def fake_region(browser,mode,*,region_key,region_ab_session,
                              region_diagnostic_arm_key,**kwargs):
            seen.append(region_diagnostic_arm_key)
            if region_diagnostic_arm_key == "far":
                region_ab_session.accept("far",None,verified=False)
                return {"status":"REGION_HEADER_ACTION_EXCEPTION",
                        "route_status":"NONE_FRESH"}
            region_ab_session.accept(
                region_diagnostic_arm_key,
                sample_region_articles(
                    sample_payload(region_key,region_diagnostic_arm_key),
                    BY_KEY[region_key],region_ab_session.secret),
                verified=True)
            return {"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
                    "route_status":"ONE_FRESH"}
        with patch("playwright.async_api.async_playwright",return_value=DummyPW()),patch(
            "ops.oci.region_aa_far.one_public_region",new=fake_region):
            r=await run(live=True,headed=True,approval=_APPROVAL,
                        directory_check=lambda:True,robots=lambda:True,
                        picker_robots=lambda _:{"allowed":True})
        self.assertEqual(seen,["a1","far","a2"])
        self.assertEqual(r["pairs"]["aa"]["symmetric_difference"],2)
        self.assertEqual(r["contrast"]["verdict"],"INDETERMINATE")

    async def test_access_restricted_prevents_third_arm(self):
        seen=[]
        async def fake_region(browser,mode,*,region_key,region_diagnostic_arm_key,
                              region_ab_session,**kwargs):
            seen.append(region_diagnostic_arm_key)
            region_ab_session.accept(region_diagnostic_arm_key,None,verified=False)
            return {"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC"
                    if region_diagnostic_arm_key=="a1" else "ACCESS_RESTRICTED",
                    "route_status":"NONE_FRESH"}
        with patch("playwright.async_api.async_playwright",return_value=DummyPW()),patch(
            "ops.oci.region_aa_far.one_public_region",new=fake_region):
            r=await run(live=True,headed=True,approval=_APPROVAL,
                        directory_check=lambda:True,robots=lambda:True,
                        picker_robots=lambda _:{"allowed":True})
        self.assertEqual(seen,["a1","far"])
        self.assertEqual(r["status"],"INCOMPLETE")
        self.assertFalse(r["contrast"]["causal_region_filter_proven"])


if __name__=="__main__":
    unittest.main()
