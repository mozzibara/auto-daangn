# -*- coding: utf-8 -*-
"""Offline request-before-response chronology and strict provenance tests."""
import unittest

from app_v5.region_route_chronology import (
    RegionPostclickRequests, sanitize_request_chronology,
)
from app_v5.region_navigation import sanitize_navigation_trace
from app_v5.region_option_events import RegionOptionEventWitness
from daangn_v4_1_core import BY_KEY

REGION = BY_KEY["cheonan"]


class FakeRequest:
    def __init__(self, url="https://www.daangn.com/kr/search/buy-sell/?q=HDD",
                 *, method="GET", resource_type="fetch"):
        self.url=url
        self.method=method
        self.resource_type=resource_type


class FakeResponse:
    def __init__(self, req):
        self.request=req


class FakeDelegate:
    def __init__(self):
        self.received=[]
        self.events=[]
        self.search_fetch_responses=0

    def hook(self, response):
        self.received.append(response)
        self.search_fetch_responses += 1
        self.events.append({"model": {"region_id": "OTHER"},
                            "status": 200})

    async def drain(self):
        return None


class ChronologyTests(unittest.IsolatedAsyncioTestCase):
    async def test_older_request_finishing_after_click_never_passes(self):
        times=iter((.900, 1.001))
        delegate=FakeDelegate()
        gate=RegionPostclickRequests(delegate,clock=lambda:next(times))
        old=FakeRequest()
        fresh=FakeRequest()
        gate.on_request(old)    # request started before click
        gate.on_request(fresh)  # request started after click
        gate.on_response(FakeResponse(old))     # response after: still old
        gate.on_response(FakeResponse(fresh))   # response after: fresh
        self.assertFalse(delegate.received)
        gate.mark_click(1000_000_000_000)  # no valid wall-time relative to fake
        self.assertFalse(delegate.received)
        # Fake epoch from real calendar range; test proper relative order.
        epoch=1_800_000_000_000
        ticks=iter((epoch-100,epoch+1))
        delegate=FakeDelegate()
        gate=RegionPostclickRequests(delegate,clock=lambda:next(ticks)/1000)
        old=FakeRequest()
        fresh=FakeRequest()
        gate.on_request(old)
        gate.on_request(fresh)
        old_resp=FakeResponse(old)
        new_resp=FakeResponse(fresh)
        gate.on_response(old_resp)
        gate.on_response(new_resp)
        gate.mark_click(epoch)
        self.assertEqual(delegate.received,[new_resp])
        self.assertEqual(gate.events,delegate.events)
        self.assertEqual(gate.search_fetch_responses,1)
        self.assertEqual(gate.export()["state"],"POSTCLICK_REQUEST_OBSERVED")
        self.assertEqual(gate.export()["requests_started_before"],1)
        self.assertEqual(gate.export()["eligible_response_count"],1)
        await gate.drain()

    async def test_response_without_first_party_request_provenance_is_ignored(self):
        d=FakeDelegate()
        gate=RegionPostclickRequests(d,clock=lambda:1_800_000_000)
        response=FakeResponse(FakeRequest())
        gate.on_response(response)
        gate.mark_click(1_800_000_000_000)
        self.assertEqual(d.received,[])
        self.assertEqual(gate.export()["responses_without_matching_request"],1)
        self.assertEqual(gate.export()["state"],"NO_POSTCLICK_REQUEST")

    async def test_no_trusted_click_epoch_blocks_every_request(self):
        d=FakeDelegate()
        gate=RegionPostclickRequests(d,clock=lambda:1_800_000_000)
        req=FakeRequest()
        gate.on_request(req)
        gate.on_response(FakeResponse(req))
        gate.mark_click(None)
        self.assertEqual(gate.export()["state"],"NO_TRUSTED_CLICK_EPOCH")
        self.assertEqual(d.received,[])
        self.assertFalse(gate.export()["authorizes_listings"])

    async def test_offsite_post_document_and_unexpected_keyword_not_inspected(self):
        d=FakeDelegate()
        gate=RegionPostclickRequests(d,clock=lambda:1_800_000_001)
        for req in (
            FakeRequest("https://evil.example/kr/search/buy-sell/?q=HDD"),
            FakeRequest("https://www.daangn.com/kr/buy-sell/SECRET"),
            FakeRequest("https://www.daangn.com/kr/search/buy-sell/?q=SSD"),
            FakeRequest(method="POST"),
            FakeRequest(resource_type="document"),
        ):
            gate.on_request(req)
            gate.on_response(FakeResponse(req))
        gate.mark_click(1_800_000_000_000)
        self.assertFalse(d.received)
        self.assertEqual(gate.export()["eligible_response_count"],0)

    async def test_real_epoch_reader_only_in_memory(self):
        target=RegionOptionEventWitness(REGION)

        class FakePage:
            async def evaluate(self, script):
                if "click_epoch_ms" in script:
                    return 1_800_000_000_000
                return None

        self.assertEqual(await target.trusted_click_epoch_ms(FakePage()),
                         1_800_000_000_000)
        self.assertNotIn("1800000000000",str(target.export()))

    def test_double_redaction_is_idempotent(self):
        src={"request_chronology":{
            "state":"POSTCLICK_REQUEST_OBSERVED",
            "requests_started_before":2,
            "requests_started_after":1,
            "responses_without_matching_request":0,
            "eligible_response_count":1,
            "click_epoch_ms":1_800_000_000_000,
            "private_url":"https://private.example/secret",
            "authorizes_listings":True,
        }}
        first=sanitize_navigation_trace(src)
        second=sanitize_navigation_trace(first)
        self.assertEqual(first,second)
        self.assertEqual(first["request_chronology"]["state"],
                         "POSTCLICK_REQUEST_OBSERVED")
        self.assertFalse(first["request_chronology"]["authorizes_listings"])
        self.assertNotIn("1800000000000",str(first))
        self.assertNotIn("private.example",str(first))
        wrong=sanitize_request_chronology({
            "state":"SECRET","eligible_response_count":9999,
            "private_id":"MY_PRIVATE_REGION"})
        self.assertEqual(wrong["state"],"NO_TRUSTED_CLICK_EPOCH")
        self.assertEqual(wrong["eligible_response_count"],-1)


if __name__=="__main__":
    unittest.main()
