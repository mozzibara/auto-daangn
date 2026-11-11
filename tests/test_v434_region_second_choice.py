# -*- coding: utf-8 -*-
"""Synthetic-only, safe keyboard alternative on exactly one remounted button."""
import unittest

from app_v5.region_second_choice import (
    attempt_second_choice, sanitize_second_choice,
)
from app_v5.region_navigation import sanitize_navigation_trace
from daangn_v4_1_core import BY_KEY

REGION=BY_KEY["cheonan"]


class FakeInventory:
    def __init__(self,armed=True):
        self.armed=armed


class FakeHandle:
    def __init__(self,guard="READY",*,press_raises=False):
        self.guard=guard
        self.press_raises=press_raises
        self.presses=0
        self.disposed=False
        self.args=None
        self.native_armed=False

    async def evaluate(self,script,arg=None):
        if "checkFollowup" in script:
            self.args=arg
            return self.guard
        if "addEventListener" in script:
            self.native_armed=True
            return True
        raise AssertionError("unexpected page JS")

    async def press(self,key,**kwargs):
        self.presses+=1
        assert key=="Enter"
        if self.press_raises:
            raise RuntimeError("secret vendor user data not printable")

    async def dispose(self):
        self.disposed=True


class FakeLocator:
    def __init__(self,count=1,handle=None):
        self.n=count
        self.handle=handle or FakeHandle()
        self.filters=[]

    def filter(self,**kwargs):
        self.filters.append(kwargs)
        return self

    @property
    def first(self):
        return self

    async def count(self):
        return self.n

    async def element_handle(self,**kwargs):
        return self.handle


class FakePage:
    def __init__(self,count=1,handle=None):
        self.loc=FakeLocator(count=count,handle=handle)
        self.selector=None
        self.stopped=False

    def locator(self,query):
        self.selector=query
        return self.loc

    async def evaluate(self,script):
        if "snapshot?.()" in script:
            h=self.loc.handle
            return {"received":h.presses>0 and not h.press_raises,
                    "trusted":h.presses>0 and not h.press_raises}
        if "stop" in script:
            self.stopped=True
            return True
        raise AssertionError("unexpected evaluate")


class SecondChoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_verified_target_button_activated_with_native_enter(self):
        page=FakePage()
        order=[]
        async def before():
            order.append(("BEFORE",page.loc.handle.presses))
        async def after():
            order.append(("AFTER",page.loc.handle.presses))
        value=await attempt_second_choice(page,REGION,FakeInventory(),
                                          on_before_click=before,
                                          on_after_click=after)
        self.assertEqual(value["state"],"KEYBOARD_ACTIVATED")
        self.assertEqual(value["activation_mode"],"KEYBOARD_ENTER")
        self.assertEqual(value["native_click_received"],"YES")
        self.assertEqual(value["native_click_trusted"],"YES")
        self.assertTrue(value["click_attempted"])
        self.assertTrue(value["click_completed"])
        self.assertFalse(value["authorizes_listings"])
        self.assertEqual(page.selector,'[role="dialog"] button')
        self.assertEqual(page.loc.handle.args["term"],REGION["term"])
        self.assertEqual(page.loc.handle.args["city"],REGION["label"])
        self.assertEqual(page.loc.handle.presses,1)
        self.assertTrue(page.loc.handle.disposed)
        self.assertTrue(page.stopped)
        self.assertEqual(order,[("BEFORE",0),("AFTER",1)])

    async def test_disabled_old_hidden_mismatched_or_ambiguous_never_activated(self):
        for code in ("DETACHED","WRONG_DIALOG","WRONG_TAG",
                     "ORIGINAL_NODE","NOT_INTERACTABLE",
                     "NOT_EXACT_TARGET_CITY","NOT_UNIQUE",
                     "NO_NEW_CANDIDATE_LIST","UNOBSERVABLE"):
            with self.subTest(guard=code):
                target=FakeHandle(code)
                value=await attempt_second_choice(
                    FakePage(handle=target),REGION,FakeInventory())
                self.assertEqual(value["state"],"GUARD_REJECTED")
                self.assertEqual(value["guard"],code)
                self.assertEqual(target.presses,0)
                self.assertTrue(target.disposed)

    async def test_ambiguous_or_missing_initial_inventory_fails_closed(self):
        target=FakeHandle()
        row=await attempt_second_choice(
            FakePage(count=2,handle=target),REGION,FakeInventory())
        self.assertEqual(row["state"],"CANDIDATE_NOT_UNIQUE")
        self.assertEqual(target.presses,0)
        row=await attempt_second_choice(
            FakePage(handle=target),REGION,FakeInventory(armed=False))
        self.assertEqual(row["state"],"INVENTORY_NOT_ARMED")
        self.assertEqual(target.presses,0)

    async def test_keyboard_press_failure_is_classified_without_text(self):
        target=FakeHandle(press_raises=True)
        page=FakePage(handle=target)
        row=await attempt_second_choice(page,REGION,FakeInventory())
        self.assertEqual(row["state"],"CLICK_FAILED")
        self.assertEqual(row["error_type"],"OTHER")
        self.assertEqual(row["activation_mode"],"KEYBOARD_ENTER")
        self.assertTrue(row["click_attempted"])
        self.assertFalse(row["click_completed"])
        self.assertEqual(row["native_click_received"],"NO")
        self.assertTrue(target.disposed)
        self.assertTrue(page.stopped)
        self.assertNotIn("vendor",str(row))

    def test_double_sanitization_strips_unknown_event_metadata_and_urls(self):
        raw={"second_choice":{
            "state":"KEYBOARD_ACTIVATED","guard":"READY",
            "activation_mode":"KEYBOARD_ENTER",
            "native_click_received":"YES",
            "native_click_trusted":"YES",
            "error_type":"NONE",
            "click_attempted":True,"click_completed":True,
            "owner_secret":"https://private.example/secret",
            "authorizes_listings":True,
        }}
        first=sanitize_navigation_trace(raw)
        second=sanitize_navigation_trace(first)
        self.assertEqual(first,second)
        item=second["second_choice"]
        self.assertEqual(item["state"],"KEYBOARD_ACTIVATED")
        self.assertFalse(item["authorizes_listings"])
        self.assertNotIn("private.example",str(second))
        x=sanitize_second_choice({"state":"PRIVATE_USER_REGION",
                                  "guard":"https://private.example",
                                  "native_click_received":"secret"})
        self.assertEqual(x["state"],"NOT_ATTEMPTED")
        self.assertEqual(x["guard"],"UNOBSERVABLE")
        self.assertEqual(x["native_click_received"],"UNKNOWN")


if __name__=="__main__":
    unittest.main()
