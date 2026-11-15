# -*- coding: utf-8 -*-
"""Offline native Playwright click-navigation wait research; no web requests."""
from __future__ import annotations

import inspect
import json
import unittest

from daangn_v4_1_core import BY_KEY, ui_select_region
from ops.oci.precollection import (
    _APPROVAL, _NAV_WAIT_APPROVAL, run, main,
)
from scripts.chrome_stable_input_compare import one_public_region


class ClickTarget:
    def __init__(self, *, option=False):
        self.option = option
        self.calls = []
    @property
    def first(self):
        return self
    def filter(self, **kw):
        return self
    async def click(self, **kwargs):
        self.calls.append(kwargs)
    async def count(self):
        return 1
    async def is_visible(self):
        return True
    async def evaluate(self, js, metadata):
        return {
            "option_metadata": "OBSERVED",
            "option_city_hint": True,
            "option_exact_term": False,
            "option_data_id": "EXPECTED",
            "option_tag": "BUTTON",
            "option_role": "OPTION",
            "option_parent": "DIALOG",
            "option_aria_selected": "MISSING",
        }


class RegionText:
    def __init__(self):
        self.value = ""
    @property
    def first(self):
        return self
    async def count(self):
        return 1
    async def fill(self, value, **kwargs):
        self.value = value
    async def input_value(self):
        return self.value


class Page:
    url = "https://www.daangn.com/kr/search/buy-sell/?q=HDD"
    def __init__(self):
        self.header = ClickTarget()
        self.option = ClickTarget(option=True)
        self.text = RegionText()
    def get_by_role(self, *a, **kw):
        return self.header
    def locator(self, query):
        return self.text if query.startswith('input[') else self.option
    async def wait_for_timeout(self, ms):
        pass


class SingleClickVariantTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_no_wait_only_changes_navigation_witness_wait(self):
        page = Page()
        row = await ui_select_region(
            page, BY_KEY["cheonan"], click_navigation_wait="NO_WAIT_AFTER")
        self.assertTrue(row["selected_suggestion"])
        self.assertTrue(row["option_city_hint"])
        self.assertEqual(row["click_navigation_wait"], "NO_WAIT_AFTER")
        self.assertEqual(page.header.calls, [{"timeout": 5000, "no_wait_after": True}])
        self.assertEqual(page.option.calls, [{"timeout": 5000, "no_wait_after": True}])
        self.assertEqual(page.text.value, BY_KEY["cheonan"]["term"])

    async def test_default_unchanged_no_navigation_opt_out(self):
        page = Page()
        row = await ui_select_region(page, BY_KEY["cheonan"])
        self.assertTrue(row["selected_suggestion"])
        self.assertEqual(page.header.calls, [{"timeout": 5000}])
        self.assertEqual(page.option.calls, [{"timeout": 5000}])
        self.assertEqual(row["click_navigation_wait"], "DEFAULT")

    async def test_unknown_mode_does_not_click_or_type(self):
        page = Page()
        row = await ui_select_region(
            page, BY_KEY["cheonan"], click_navigation_wait="FORCE")
        self.assertEqual(row["error"], "unsupported_click_navigation_wait")
        self.assertFalse(page.header.calls)
        self.assertFalse(page.option.calls)
        self.assertEqual(page.text.value, "")

    async def test_approval_is_mutually_exclusive_and_denies_old_token(self):
        calls = []
        async def diag():
            calls.append(True)
            return {"status": "REGION_NOT_COMMITTED",
                    "cookie": "PRIVATE_SECRET",
                    "selected_ui": "OTHER"}
        args = dict(live=True, headed=True, no_wait_region_click=True,
                    robots=lambda: True,
                    picker_robots=lambda term: {"allowed": True},
                    directory_check=lambda: True, diagnostic=diag)
        denied = await run(approve=_APPROVAL, **args)
        self.assertEqual(denied["status"], "OWNER_APPROVAL_REQUIRED")
        self.assertEqual(len(calls), 0)

        mutually = await run(
            approve=_NAV_WAIT_APPROVAL, passive_dynamic_loader=True, **args)
        self.assertEqual(mutually["status"], "OWNER_APPROVAL_REQUIRED")
        self.assertEqual(len(calls), 0)

        allowed = await run(approve=_NAV_WAIT_APPROVAL, **args)
        self.assertEqual(len(calls), 1)
        self.assertEqual(allowed["region_click_navigation_wait"], "NO_WAIT_AFTER")
        self.assertEqual(allowed["status"], "STOP_REGION_NOT_VERIFIED")
        self.assertFalse(allowed["collection_started"])
        self.assertFalse(allowed["authorizes_listings"])
        self.assertNotIn("PRIVATE_SECRET", json.dumps(allowed))

    async def test_offline_cli_refuses_ownerless_flag(self):
        self.assertEqual(main(["--no-wait-region-click"]), 2)

    async def test_existing_region_witness_called_with_mode(self):
        source = inspect.getsource(one_public_region)
        self.assertIn("click_navigation_wait=click_navigation_wait", source)
        self.assertIn('status == "TARGET_REGION_CONFIRMED_DIAGNOSTIC"', source)


if __name__ == "__main__":
    unittest.main()
