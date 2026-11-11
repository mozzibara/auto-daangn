# -*- coding: utf-8 -*-
"""Offline first-party, UI-triggered search JSON fixture (no web requests)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import unittest

import daangn_browser_v4_6 as v46
from daangn_full_route_v4_14 import RouteBodies
from daangn_network_flow_v4_11 import NetworkRecorder


SEARCH = ("https://www.daangn.com/kr/search/buy-sell/"
          "?q=HDD&category_id=1&only_on_sale=true&price=__50000")
ARTICLE = "https://www.daangn.com/kr/buy-sell/test-disk-123456789abc/"


def payload():
    return json.dumps({
        "state": {"loaderData": {
            "routes/kr.search.buy-sell._index": {
                "searchRegion": {"id": 2292, "name": "불당동"},
                "currentFilters": {"regionId": 2292, "search": "HDD",
                                   "categoryId": 1, "maxPrice": 50000,
                                   "onlyOnSale": True},
                "buySellArticles": [{"href": ARTICLE, "price": 45000,
                                     "categoryId": 1, "isSoldOut": False}],
            }
        }}
    }).encode("utf-8")


class FakeRequest:
    resource_type = "fetch"

    def __init__(self, url):
        self.url = url


class FakeResponse:
    def __init__(self, url, body, content_type="application/json"):
        self.url = url
        self.body_bytes = body
        self.status = 200
        self.request = FakeRequest(url)
        self.headers = {
            "content-type": content_type,
            "content-length": str(len(body)),
        }

    async def body(self):
        return self.body_bytes


class SearchResponseVariants(unittest.IsolatedAsyncioTestCase):
    async def test_first_party_search_json_without_legacy_data_route(self):
        # The URL is an observed-style variant; it is NOT fetched by this test.
        variant = SEARCH + "&_data=routes%2Fsome-other-search-route"
        body = payload()
        r = FakeResponse(variant, body)
        net = v46.Network()
        passive = RouteBodies()
        observer = NetworkRecorder()
        observer.phase = "FILTER_APPLY"
        observer.on_request(r.request)
        net.hook(r)
        passive.on_response(r)
        observer.on_response(r)
        await net.drain()
        await passive.drain()
        await observer.drain()
        self.assertEqual(net.search_fetch_responses, 1)
        self.assertEqual(net.old_remix_route_responses, 0)
        self.assertEqual(net.other_search_json_responses, 1)
        self.assertEqual(len(net.events), 1)
        self.assertEqual(len(passive.events), 1)
        self.assertEqual(net.events[0]["digest"],
                         hashlib.sha256(body).hexdigest())
        self.assertEqual(passive.events[0]["digest"],
                         net.events[0]["digest"])
        self.assertEqual(len(observer.events), 1)
        self.assertEqual(observer.events[0]["kind"], "SEARCH_DOCUMENT")
        self.assertEqual(observer.events[0]["body_sha256"],
                         net.events[0]["digest"])
        self.assertEqual(str(net.events[0]["model"]["region_id"]), "2292")
        self.assertEqual(str(net.events[0]["model"]["filter_region_id"]),
                         "2292")

    async def test_wrong_host_and_html_are_never_accepted(self):
        for url, ctype in [
            (SEARCH.replace("www.daangn.com", "evil.example"),
             "application/json"),
            (SEARCH, "text/html"),
        ]:
            with self.subTest(url=url, ctype=ctype):
                net = v46.Network()
                passive = RouteBodies()
                r = FakeResponse(url, payload(), ctype)
                net.hook(r)
                passive.on_response(r)
                await net.drain()
                await passive.drain()
                self.assertEqual(len(net.events), 0)
                self.assertEqual(len(passive.events), 0)


if __name__ == "__main__":
    unittest.main()
