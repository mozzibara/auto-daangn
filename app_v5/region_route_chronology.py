# -*- coding: utf-8 -*-
"""Capture search Routes only when their GET requests START after real UI click.

Existing v4.6 response hook does not know if the underlying request began
before the region option click. A response received later is not necessarily
post-click evidence. This layer buffers browser events in RAM until the
trusted DOM click timestamp is observed; it sends eligible response objects
to the existing safe, bounded v4.6 model collector. No new network requests.
"""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import daangn_v4_1_core as core

_RESULT = frozenset((
    "NO_TRUSTED_CLICK_EPOCH", "NO_POSTCLICK_REQUEST",
    "POSTCLICK_REQUEST_OBSERVED",
))


def _search_request(request) -> bool:
    try:
        p = urlsplit(request.url)
        return (p.scheme == "https" and p.hostname == "www.daangn.com"
                and p.port is None and p.path == core.SEARCH_PATH
                and parse_qs(p.query).get("q") == ["HDD"]
                and request.resource_type in ("xhr", "fetch")
                and request.method == "GET")
    except (ValueError, AttributeError, TypeError):
        return False


def sanitize_request_chronology(value) -> dict:
    src = value if type(value) is dict else {}
    state = src.get("state")
    return {
        "state": state if type(state) is str and state in _RESULT
                 else "NO_TRUSTED_CLICK_EPOCH",
        **{key: (src[key] if type(src.get(key)) is int
                 and 0 <= src[key] <= 20 else -1) for key in (
                     "requests_started_before",
                     "requests_started_after",
                     "responses_without_matching_request",
                     "eligible_response_count",
                 )},
        "authorizes_listings": False,
    }


class RegionPostclickRequests:
    """Chronology-only wrapper around the existing v4.6 Network consumer.

    The watcher attaches *before* region typing, capturing request start
    timestamps. It never treats an unattributed (pre-listener) response as
    post-click. Responses received before the click epoch becomes available
    remain in a bounded short-lived RAM queue, and are then filtered using
    request start time, not response completion time.
    """

    def __init__(self, delegate, *, clock=None):
        self.delegate = delegate
        self.clock = clock or time.time
        self.starts = {}
        self.pending = []
        self.click_epoch_ms = None
        self.requests_started_before = 0
        self.requests_started_after = 0
        self.responses_without_matching_request = 0
        self.eligible_response_count = 0

    def on_request(self, request):
        if not _search_request(request):
            return
        if len(self.starts) >= 24:
            return
        # We keep Request handles only in RAM, never print, hash or persist
        # their URLs, headers or ids. Time is excluded from public reports.
        self.starts[request] = int(self.clock() * 1000)

    def _pass_response(self, response, started):
        if self.click_epoch_ms is None:
            if len(self.pending) < 20:
                self.pending.append((response, started))
            return
        if started < self.click_epoch_ms:
            self.requests_started_before = min(20, self.requests_started_before + 1)
            return
        self.requests_started_after = min(20, self.requests_started_after + 1)
        self.eligible_response_count = min(20, self.eligible_response_count + 1)
        self.delegate.hook(response)

    def on_response(self, response):
        try:
            req = response.request
            if not _search_request(req):
                return
            started = self.starts.pop(req, None)
            if started is None:
                self.responses_without_matching_request = min(
                    20, self.responses_without_matching_request + 1)
                return
            self._pass_response(response, started)
        except (ValueError, AttributeError, TypeError):
            pass

    def mark_click(self, click_epoch_ms):
        """Take only an actual in-page trusted CLICK_TARGET timestamp."""
        if (type(click_epoch_ms) is int
                and 1_000_000_000_000 <= click_epoch_ms <= 9_999_999_999_999):
            self.click_epoch_ms = click_epoch_ms
        for response, started in self.pending:
            if self.click_epoch_ms is not None:
                self._pass_response(response, started)
        self.pending.clear()

    async def drain(self):
        await self.delegate.drain()

    @property
    def events(self):
        return self.delegate.events

    @property
    def search_fetch_responses(self):
        return self.delegate.search_fetch_responses

    def export(self):
        state = ("NO_TRUSTED_CLICK_EPOCH" if self.click_epoch_ms is None
                 else "POSTCLICK_REQUEST_OBSERVED"
                 if self.eligible_response_count else "NO_POSTCLICK_REQUEST")
        return sanitize_request_chronology({
            "state": state,
            "requests_started_before": self.requests_started_before,
            "requests_started_after": self.requests_started_after,
            "responses_without_matching_request":
                self.responses_without_matching_request,
            "eligible_response_count": self.eligible_response_count,
        })
