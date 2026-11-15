"""Bounded item-region field shape and controlled reverse-order pilot."""
import json
import unittest
from unittest.mock import patch
from app_v5.region_ab_sample import sample_region_articles
from daangn_v4_1_core import BY_KEY
from ops.oci.region_ab import run


def body():
    model={
        "searchRegion":{"id":2292},
        "currentFilters":{"regionId":2292},
        "buySellArticles":[
            {"href":"/kr/buy-sell/p-abc123456789/","region":{"name":"불당동"}},
            {"href":"/kr/buy-sell/q-abc123456789/","region":{"name":"배방읍"}},
            {"href":"/kr/buy-sell/r-abc123456789/","region":{"id":2292}},
            {"href":"/kr/buy-sell/s-abc123456789/"}
        ],
    }
    return json.dumps({"route":model},ensure_ascii=False).encode()


class ShapeTests(unittest.TestCase):
    def test_item_name_only_matches_are_reported_not_promoted_to_verified(self):
        result=sample_region_articles(body(),BY_KEY["cheonan"],b"Z"*32)
        sample=result["summary"]
        self.assertEqual(sample["status"],"COMPLETE")
        self.assertEqual(sample["rows"],4)
        self.assertEqual(sample["local_exact"],1)
        self.assertEqual(sample["unverified"],3)
        self.assertEqual(sample["region_object_rows"],3)
        self.assertEqual(sample["region_name_only_rows"],2)
        self.assertEqual(sample["region_name_only_target_rows"],1)
        self.assertEqual(sample["region_name_only_other_rows"],1)
        self.assertEqual(sample["region_id_rows"],1)
        self.assertEqual(sample["region_city_rows"],0)
        self.assertNotIn("배방읍",json.dumps(sample,ensure_ascii=False))
        self.assertNotIn("불당동",json.dumps(sample,ensure_ascii=False))


class ReverseOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_approval_denies_reverse(self):
        value=await run(live=True,headed=True,
                        approval="I_APPROVE_OCI_REGION_AB_SAMPLE_V1",
                        reverse_order=True,directory_check=lambda:True,
                        robots=lambda:True,picker_robots=lambda _:{"allowed":True})
        self.assertEqual(value["status"],"OWNER_APPROVAL_REQUIRED")

    async def test_as an_first_uses_same_existing_browser_action(self):
        # Fake only the browser transport, not the owner/robots gates.
        from types import SimpleNamespace
        order=[]
        class Chrome:
            async def launch(self,**kwargs):
                return SimpleNamespace(close=self.close)
            async def close(self):
                return None
        class PW:
            async def __aenter__(self):
                return SimpleNamespace(chromium=Chrome())
            async def __aexit__(self,*args):
                return None
        async def fake_region(browser,mode,**kw):
            order.append(kw["region_key"])
            return {"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
                    "route_status":"ONE_FRESH"}
        with patch("playwright.async_api.async_playwright",return_value=PW()), patch(
            "ops.oci.region_ab.one_public_region",new=fake_region
        ):
            result=await run(
                live=True,headed=True,reverse_order=True,
                approval="I_APPROVE_OCI_REGION_BA_SHAPE_V1",
                directory_check=lambda:True,robots=lambda:True,
                picker_robots=lambda _:{"allowed":True})
        self.assertEqual(order,["asan","cheonan"])
        self.assertEqual(result["execution_order"],"ASAN_FIRST")
        self.assertFalse(result["authorizes_listings"])


if __name__=="__main__":
    unittest.main()
