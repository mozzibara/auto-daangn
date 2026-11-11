# -*- coding: utf-8 -*-
"""Passive, diagnostic-only witness for the real UI region-suggestion response.

It never sends a request. Numeric IDs remain only in RAM and cannot authorize
listing collection or replace the historical configured region preset.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import parse_qs, urlsplit

_MAX_BODY = 128_000
_ID = re.compile(r"[0-9]{1,12}\Z")


def inspect_locations(payload, region: dict) -> dict:
    """Inspect known public resolver schema; keep only bounded in-memory IDs."""
    data = payload.get("data") if isinstance(payload, dict) else None
    obj = payload if isinstance(payload, dict) else {}
    locations = obj.get("locations")
    if not isinstance(locations, list) and isinstance(data, dict):
        locations = data.get("locations")
    if not isinstance(locations, list) or len(locations) > 100:
        return {"state": "SCHEMA_NOT_RECOGNIZED", "count": 0, "matches": []}
    matches = []
    for item in locations[:100]:
        if not isinstance(item, dict):
            continue
        parts = [item.get(k) for k in ("name", "name1", "name2", "name3")]
        names = [s.strip() for s in parts if isinstance(s, str) and len(s) <= 120]
        exact = any(s == region["term"] for s in names)
        city = any(region["label"] in s for s in names)
        raw_id = item.get("id")
        if exact and city and type(raw_id) in (str, int):
            rid = str(raw_id)
            if _ID.fullmatch(rid):
                matches.append(rid)
    return {
        "state": "OBSERVED",
        "count": min(len(locations), 20),
        "matches": matches[:3],
    }


class RegionSuggestionObserver:
    """Observes only browser-generated first-party region keyword JSON."""
    def __init__(self, region: dict):
        self.region = region
        self.events = []
        self.tasks = set()
        self.responses = 0
        self.blocked = False

    def on_response(self, response):
        try:
            u = urlsplit(response.url)
            if (u.scheme != "https" or u.hostname != "www.daangn.com"
                    or u.path != "/kr/api/v1/regions/keyword"
                    or response.request.resource_type not in ("xhr", "fetch")):
                return
            if parse_qs(u.query).get("keyword") != [self.region["term"]]:
                return
            self.responses = min(self.responses + 1, 20)
            if response.status in (401, 403, 429):
                self.blocked = True
                return
            if response.status != 200:
                return
            if "json" not in str(response.headers.get("content-type", "")).lower():
                return
            length = response.headers.get("content-length", "")
            if length.isdecimal() and int(length) > _MAX_BODY:
                return
            if len(self.tasks) + len(self.events) >= 4:
                return

            async def receive():
                try:
                    raw = await asyncio.wait_for(response.body(), timeout=10)
                    if len(raw) > _MAX_BODY:
                        return
                    self.events.append(inspect_locations(json.loads(raw), self.region))
                except (ValueError, UnicodeError, TypeError, asyncio.TimeoutError):
                    self.events.append({"state": "SCHEMA_NOT_RECOGNIZED",
                                        "count": 0, "matches": []})
                except Exception:
                    pass

            task = asyncio.create_task(receive())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except (ValueError, TypeError, AttributeError):
            return

    async def drain(self):
        if self.tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*list(self.tasks), return_exceptions=True),
                    timeout=11)
            except asyncio.TimeoutError:
                pass


def classify_suggestion_identity(region: dict, resolver_events: list,
                                 search_events: list) -> dict:
    """Compare a unique known API candidate with post-click search IDs in RAM."""
    events = resolver_events if isinstance(resolver_events, list) else []
    after = search_events if isinstance(search_events, list) else []
    outcome = {
        "state": "NO_RESOLVER_RESPONSE",
        "api_location_count": 0,
        "exact_city_term_candidate_count": 0,
        "preset_id_matches_candidate": False,
        "candidate_matches_post_click_search_ids": False,
        "post_click_name_matches_target": False,
    }
    if len(events) > 1:
        outcome["state"] = "AMBIGUOUS_RESOLVER_RESPONSES"
        return outcome
    if not events:
        return outcome
    event = events[0] if isinstance(events[0], dict) else {}
    outcome["api_location_count"] = (
        event.get("count") if type(event.get("count")) is int
        and 0 <= event["count"] <= 20 else 0)
    matches = event.get("matches") or []
    outcome["exact_city_term_candidate_count"] = min(len(matches), 3)
    if event.get("state") != "OBSERVED":
        outcome["state"] = "RESOLVER_SCHEMA_UNKNOWN"
    elif len(matches) == 0:
        outcome["state"] = "NO_EXACT_CITY_TERM_MATCH"
    elif len(matches) > 1:
        outcome["state"] = "AMBIGUOUS_CITY_TERM_MATCH"
    elif len(after) != 1:
        outcome["state"] = "POST_CLICK_SEARCH_NOT_UNIQUE"
    else:
        candidate_id = matches[0]
        outcome["state"] = "UNIQUE_API_CANDIDATE_CORRELATED"
        outcome["preset_id_matches_candidate"] = (
            candidate_id == str(region["id"]))
        model = after[0].get("model") if isinstance(after[0], dict) else {}
        model = model if isinstance(model, dict) else {}
        outcome["candidate_matches_post_click_search_ids"] = (
            str(model.get("region_id")) == candidate_id
            and str(model.get("filter_region_id")) == candidate_id)
        name = model.get("search_region_name")
        outcome["post_click_name_matches_target"] = (
            isinstance(name, str) and
            (name.strip() == region["term"] or region["term"] in name))
    return outcome


_RESOLVER_STATES = frozenset({
    "NO_RESOLVER_RESPONSE", "AMBIGUOUS_RESOLVER_RESPONSES",
    "RESOLVER_SCHEMA_UNKNOWN", "NO_EXACT_CITY_TERM_MATCH",
    "AMBIGUOUS_CITY_TERM_MATCH", "POST_CLICK_SEARCH_NOT_UNIQUE",
    "UNIQUE_API_CANDIDATE_CORRELATED",
})


def sanitize_suggestion_identity(value) -> dict:
    src = value if type(value) is dict else {}
    state = src.get("state")
    count_keys = ("api_location_count", "exact_city_term_candidate_count")
    flags = ("preset_id_matches_candidate",
             "candidate_matches_post_click_search_ids",
             "post_click_name_matches_target")
    return {
        "state": state if type(state) is str and state in _RESOLVER_STATES
                 else "UNKNOWN",
        **{k: src[k] if type(src.get(k)) is int and
           0 <= src[k] <= 20 else -1 for k in count_keys},
        **{k: src.get(k) is True for k in flags},
    }
