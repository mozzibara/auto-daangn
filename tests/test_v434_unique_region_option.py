# -*- coding: utf-8 -*-
"""Purely synthetic Playwright locator fakes: no browser or network."""
from __future__ import annotations

import unittest

import daangn_v4_1_core as core


class FakeLocator:
    def __init__(self, count=1, visible=True):
        self.n = count
        self.visible = visible
        self.clicks = 0
        self.fills = 0

    @property
    def first(self):
        return self

    def filter(self, **kwargs):
        return self

    async def count(self):
        return self.n

    async def click(self, **kwargs):
        self.clicks += 1

    async def fill(self, text, **kwargs):
        self.fills += 1

    async def is_visible(self):
        return self.visible

    async def evaluate(self, *args):
        return {"option_metadata": "OBSERVED", "option_city_hint": True,
                "option_exact_term": False, "option_data_id": "MISSING",
                "option_tag": "BUTTON", "option_role": "OPTION",
                "option_parent": "LISTBOX", "option_aria_selected": "FALSE"}


class FakePage:
    url = "https://www.daangn.com/kr/search/buy-sell/?q=HDD"

    def __init__(self, matching_count, visible=True):
        self.region_button = FakeLocator()
        self.input = FakeLocator()
        self.option = FakeLocator(matching_count, visible)

    def get_by_role(self, role, name):
        return self.region_button

    def locator(self, selector):
        return self.input if "input[placeholder" in selector else self.option

    async def wait_for_timeout(self, value):
        return None


class RegionSelectorUniquenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_visible_region_option_may_be_clicked(self):
        p = FakePage(1)
        result = await core.ui_select_region(p, core.BY_KEY["cheonan"])
        self.assertTrue(result["clicked_region_button"])
        self.assertTrue(result["unique_region_option"])
        self.assertTrue(result["selected_suggestion"])
        self.assertEqual(p.option.clicks, 1)
        self.assertEqual(result["option_tag"], "BUTTON")
        self.assertEqual(result["option_role"], "OPTION")
        self.assertEqual(result["option_parent"], "LISTBOX")
        self.assertEqual(result["option_aria_selected"], "FALSE")

    async def test_resolver_listener_arms_before_search_input_fill(self):
        p = FakePage(1)
        observed = []
        result = await core.ui_select_region(
            p, core.BY_KEY["cheonan"],
            on_before_search=lambda: observed.append(p.input.fills),
            on_before_select=lambda: observed.append(p.option.clicks))
        self.assertTrue(result["selected_suggestion"])
        self.assertEqual(observed, [0, 0])
        self.assertEqual(p.input.fills, 1)
        self.assertEqual(p.option.clicks, 1)

    async def test_listener_arms_only_at_unique_option_click(self):
        p = FakePage(1)
        armed = []
        result = await core.ui_select_region(
            p, core.BY_KEY["cheonan"],
            on_before_select=lambda: armed.append(p.option.clicks))
        self.assertTrue(result["selected_suggestion"])
        self.assertEqual(armed, [0])
        self.assertEqual(p.option.clicks, 1)

    async def test_async_navigation_witness_runs_on_either_side_of_exact_click(self):
        p = FakePage(1)
        calls = []

        async def before():
            calls.append(("BEFORE_CLICK", p.option.clicks))

        async def after():
            calls.append(("AFTER_CLICK", p.option.clicks))

        result = await core.ui_select_region(
            p, core.BY_KEY["cheonan"],
            on_before_select=before, on_after_select=after)
        self.assertTrue(result["selected_suggestion"])
        self.assertEqual(calls, [("BEFORE_CLICK", 0), ("AFTER_CLICK", 1)])

    async def test_passive_option_witness_receives_actual_locator_before_click(self):
        p = FakePage(1)
        order = []

        async def arm_option(locator):
            order.append(("OPTION_ARMED", locator is p.option, p.option.clicks))

        async def before():
            order.append(("BEFORE", True, p.option.clicks))

        async def after():
            order.append(("AFTER", True, p.option.clicks))

        result = await core.ui_select_region(
            p, core.BY_KEY["cheonan"],
            on_option_witness=arm_option,
            on_before_select=before,
            on_after_select=after)
        self.assertTrue(result["selected_suggestion"])
        self.assertEqual(order, [
            ("OPTION_ARMED", True, 0),
            ("BEFORE", True, 0),
            ("AFTER", True, 1),
        ])

    async def test_ambiguous_option_never_arms_dom_event_witness(self):
        p = FakePage(2)
        calls = []
        result = await core.ui_select_region(
            p, core.BY_KEY["cheonan"],
            on_option_witness=lambda loc: calls.append("ARMED"))
        self.assertFalse(result["selected_suggestion"])
        self.assertEqual(calls, [])

    async def test_ambiguous_option_never_samples_post_click_ui(self):
        p = FakePage(2)
        calls = []

        async def after():
            calls.append("AFTER_CLICK")

        result = await core.ui_select_region(
            p, core.BY_KEY["cheonan"], on_after_select=after)
        self.assertFalse(result["selected_suggestion"])
        self.assertEqual(calls, [])

    async def test_ambiguous_region_option_never_arms_listener(self):
        p = FakePage(2)
        armed = []
        result = await core.ui_select_region(
            p, core.BY_KEY["cheonan"],
            on_before_select=lambda: armed.append("armed"))
        self.assertFalse(result["selected_suggestion"])
        self.assertEqual(armed, [])

    async def test_multiple_matching_region_options_never_get_clicked(self):
        p = FakePage(2)
        result = await core.ui_select_region(p, core.BY_KEY["cheonan"])
        self.assertFalse(result["unique_region_option"])
        self.assertFalse(result["selected_suggestion"])
        self.assertEqual(result["error"], "ambiguous_region_options")
        self.assertEqual(p.option.clicks, 0)

    async def test_hidden_or_missing_region_option_fails_closed(self):
        for n, visible in [(0, True), (1, False)]:
            with self.subTest(n=n, visible=visible):
                p = FakePage(n, visible)
                result = await core.ui_select_region(
                    p, core.BY_KEY["cheonan"])
                self.assertFalse(result["selected_suggestion"])
                self.assertEqual(p.option.clicks, 0)


if __name__ == "__main__":
    unittest.main()
