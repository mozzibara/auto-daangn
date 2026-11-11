# -*- coding: utf-8 -*-
"""Offline-only public region picker robots checks; no site traffic."""
from __future__ import annotations

import unittest

from scripts.run_live_checked import check_region_picker_robots


class FakeResponse:
    status = 200

    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, n):
        return self.body[:n]


class RegionPickerRobotsTests(unittest.TestCase):
    def test_region_endpoint_allowed_with_synthetic_robots(self):
        def get(req, timeout):
            self.assertEqual(timeout, 20)
            return FakeResponse(b"User-agent: *\nAllow: /\n")
        result = check_region_picker_robots("불당동", getter=get)
        self.assertEqual(result, {"allowed": True, "reason": "ALLOWED"})

    def test_denied_region_endpoint_fails_closed(self):
        def get(req, timeout):
            return FakeResponse(
                b"User-agent: *\nDisallow: /kr/api/v1/regions/keyword\n"
            )
        result = check_region_picker_robots("불당동", getter=get)
        self.assertEqual(result, {"allowed": False, "reason": "DISALLOWED"})

    def test_unknown_region_does_not_call_network(self):
        def unexpected(*args, **kwargs):
            raise AssertionError("must not reach network")
        result = check_region_picker_robots("기타 지역", getter=unexpected)
        self.assertEqual(result["reason"], "INVALID_REGION")

    def test_unavailable_robots_fails_closed(self):
        def unavailable(*args, **kwargs):
            raise OSError("private/untrusted detail")
        result = check_region_picker_robots("배방읍", getter=unavailable)
        self.assertEqual(result, {"allowed": False,
                                  "reason": "ROBOTS_UNAVAILABLE"})


if __name__ == "__main__":
    unittest.main()
