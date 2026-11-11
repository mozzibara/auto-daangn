# -*- coding: utf-8 -*-
"""One bounded, owner-approved public UI follow-up on a verified remounted region.

A read-only browser check verifies the EXACT new DOM button before Playwright's
normal click. Never sends requests itself, bypasses UI, or treats click as proof.
"""
from __future__ import annotations

from app_v5.region_button_inventory import RegionButtonInventory

_GUARDS = frozenset((
    "READY", "DETACHED", "WRONG_DIALOG", "WRONG_TAG", "ORIGINAL_NODE",
    "NOT_INTERACTABLE", "NOT_EXACT_TARGET_CITY", "NOT_UNIQUE",
    "NO_NEW_CANDIDATE_LIST", "UNOBSERVABLE",
))
_STATES = frozenset((
    "NOT_ATTEMPTED", "CLICKED", "CANDIDATE_NOT_UNIQUE", "GUARD_REJECTED",
    "INVENTORY_NOT_ARMED", "ELEMENT_MISSING", "CLICK_FAILED",
))

_CHECK_JS = r"""(el, meta) => {
  const key=Symbol.for('auto_daangn_button_inventory_v1');
  return document[key]?.checkFollowup?.(el,meta) || 'UNOBSERVABLE';
}"""


def sanitize_second_choice(value) -> dict:
    obj = value if type(value) is dict else {}
    state = obj.get("state")
    guard = obj.get("guard")
    return {
        "state": state if type(state) is str and state in _STATES
                 else "NOT_ATTEMPTED",
        "guard": guard if type(guard) is str and guard in _GUARDS
                 else "UNOBSERVABLE",
        "click_attempted": obj.get("click_attempted") is True,
        "click_completed": obj.get("click_completed") is True,
        "authorizes_listings": False,
    }


async def attempt_second_choice(page, region: dict,
                                inventory: RegionButtonInventory,
                                *, on_before_click=None,
                                on_after_click=None) -> dict:
    """Only click a unique *new* target+city BUTTON in the original dialog.

    A single anchored Playwright ElementHandle is used for both the guard and
    the eventual click. If React detaches/replaces it, click fails closed.
    """
    result = {
        "state": "NOT_ATTEMPTED", "guard": "UNOBSERVABLE",
        "click_attempted": False, "click_completed": False,
    }
    if not inventory.armed:
        result["state"] = "INVENTORY_NOT_ARMED"
        return sanitize_second_choice(result)
    handle = None
    try:
        matching = page.locator('[role="dialog"] button').filter(
            has_text=region["term"])
        if await matching.count() != 1:
            result["state"] = "CANDIDATE_NOT_UNIQUE"
            return sanitize_second_choice(result)
        handle = await matching.first.element_handle(timeout=1000)
        if handle is None:
            result["state"] = "ELEMENT_MISSING"
            return sanitize_second_choice(result)
        state = await handle.evaluate(
            _CHECK_JS, {"term": region["term"], "city": region["label"]})
        result["guard"] = state if type(state) is str and state in _GUARDS else "UNOBSERVABLE"
        if result["guard"] != "READY":
            result["state"] = "GUARD_REJECTED"
            return sanitize_second_choice(result)
        if on_before_click is not None:
            await on_before_click()
        result["click_attempted"] = True
        await handle.click(timeout=3000)
        result["click_completed"] = True
        result["state"] = "CLICKED"
        if on_after_click is not None:
            await on_after_click()
        return sanitize_second_choice(result)
    except Exception:
        result["state"] = "CLICK_FAILED"
        return sanitize_second_choice(result)
    finally:
        if handle is not None:
            try:
                await handle.dispose()
            except Exception:
                pass
