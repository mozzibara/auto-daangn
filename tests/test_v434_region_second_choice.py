# -*- coding: utf-8 -*-
"""Offline tests: second click only on one new, exact target+city DOM node."""
import unittest

from app_v5.region_second_choice import (
    attempt_second_choice, sanitize_second_choice,
)
from app_v5.region_navigation import sanitize_navigation_trace
from daangn_v4_1_core import BY_KEY

REGION = BY_KEY["cheonan"]


class FakeInventory:
    def __init__(self, armed=True):
        self.armed = armed


class FakeHandle:
    def __init__(self, guard="READY", *, click_raises=False):
        self.guard = guard
        self.click_raises = click_raises
        self.clicks = 0
        self.disposed = False
        self.args = None

    async def evaluate(self, script, arg):
        self.args = arg
        return self.guard

    async def click(self, **kwargs):
        self.clicks += 1
        if self.click_raises:
            raise RuntimeError("secret vendor user data not printable")

    async def dispose(self):
        self.disposed = True


class FakeLocator:
    def __init__(self, count=1, handle=None):
        self.n = count
        self.handle = handle or FakeHandle()
        self.filters = []

    def filter(self, **kwargs):
        self.filters.append(kwargs)
        return self

    @property
    def first(self):
        return self

    async def count(self):
        return self.n

    async def element_handle(self, **kwargs):
        return self.handle


class FakePage:
    def __init__(self, count=1, handle=None):
        self.loc = FakeLocator(count=count, handle=handle)
        self.selector = None

    def locator(self, query):
        self.selector = query
        return self.loc


class SecondChoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_new_target_button_is_clicked_once_in_normal_playwright(self):
        page = FakePage()
        actions = []

        async def before():
            actions.append(("BEFORE", page.loc.handle.clicks))

        async def after():
            actions.append(("AFTER", page.loc.handle.clicks))

        value = await attempt_second_choice(page, REGION, FakeInventory(),
                                            on_before_click=before,
                                            on_after_click=after)
        self.assertEqual(value["state"], "CLICKED")
        self.assertTrue(value["click_attempted"])
        self.assertTrue(value["click_completed"])
        self.assertFalse(value["authorizes_listings"])
        self.assertEqual(page.selector, '[role="dialog"] button')
        self.assertEqual(page.loc.handle.args["term"], REGION["term"])
        self.assertEqual(page.loc.handle.args["city"], REGION["label"])
        self.assertEqual(page.loc.handle.clicks, 1)
        self.assertTrue(page.loc.handle.disposed)
        self.assertEqual(actions, [("BEFORE", 0), ("AFTER", 1)])

    async def test_old_or_missing_or_wrong_city_node_never_clicked(self):
        for code in ("DETACHED", "WRONG_DIALOG", "WRONG_TAG",
                     "ORIGINAL_NODE", "NOT_INTERACTABLE",
                     "NOT_EXACT_TARGET_CITY", "NOT_UNIQUE",
                     "NO_NEW_CANDIDATE_LIST", "UNOBSERVABLE"):
            with self.subTest(guard=code):
                target = FakeHandle(code)
                value = await attempt_second_choice(
                    FakePage(handle=target), REGION, FakeInventory())
                self.assertEqual(value["state"], "GUARD_REJECTED")
                self.assertEqual(value["guard"], code)
                self.assertEqual(target.clicks, 0)
                self.assertTrue(target.disposed)

    async def test_ambiguous_second_target_never_clicked(self):
        target = FakeHandle()
        row = await attempt_second_choice(
            FakePage(count=2, handle=target), REGION, FakeInventory())
        self.assertEqual(row["state"], "CANDIDATE_NOT_UNIQUE")
        self.assertEqual(target.clicks, 0)

    async def test_absent_baseline_inventory_never_clicks(self):
        target = FakeHandle()
        row = await attempt_second_choice(
            FakePage(handle=target), REGION, FakeInventory(armed=False))
        self.assertEqual(row["state"], "INVENTORY_NOT_ARMED")
        self.assertEqual(target.clicks, 0)

    async def test_click_failure_does_not_mark_completed_or_leak_exception(self):
        target = FakeHandle(click_raises=True)
        row = await attempt_second_choice(
            FakePage(handle=target), REGION, FakeInventory())
        self.assertEqual(row["state"], "CLICK_FAILED")
        self.assertTrue(row["click_attempted"])
        self.assertFalse(row["click_completed"])
        self.assertTrue(target.disposed)
        self.assertNotIn("vendor", str(row))

    def test_double_sanitized_navigational_output_drops_private_data(self):
        raw = {"second_choice": {
            "state": "CLICKED", "guard": "READY",
            "click_attempted": True, "click_completed": True,
            "owner_secret": "https://private.example/secret",
            "authorizes_listings": True,
        }}
        a = sanitize_navigation_trace(raw)
        b = sanitize_navigation_trace(a)
        self.assertEqual(a, b)
        self.assertEqual(b["second_choice"]["guard"], "READY")
        self.assertFalse(b["second_choice"]["authorizes_listings"])
        self.assertNotIn("private.example", str(b))
        x = sanitize_second_choice({"state": "PRIVATE_USER_REGION",
                                    "guard": "https://private.example"})
        self.assertEqual(x["state"], "NOT_ATTEMPTED")
        self.assertEqual(x["guard"], "UNOBSERVABLE")


if __name__ == "__main__":
    unittest.main()
