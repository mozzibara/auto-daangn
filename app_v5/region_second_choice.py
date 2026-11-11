# -*- coding: utf-8 -*-
"""One verified second-stage public location action via standard keyboard Enter.

Pointer activation on the remounted native BUTTON failed in live #33 despite
a READY identity guard. A keyboard Enter is a normal accessible activation,
not a synthetic JS click/force action. Native click receipt and server Route
are separate witnesses. No arbitrary page data ever crosses the boundary.
"""
from __future__ import annotations

import asyncio
from app_v5.region_button_inventory import (
    RegionButtonInventory, _SAMPLE_JS,
)

_GUARDS = frozenset((
    "READY", "DETACHED", "WRONG_DIALOG", "WRONG_TAG", "ORIGINAL_NODE",
    "NOT_INTERACTABLE", "NOT_EXACT_TARGET_CITY", "NOT_UNIQUE",
    "NO_NEW_CANDIDATE_LIST", "UNOBSERVABLE",
))
_STATES = frozenset((
    "NOT_ATTEMPTED", "CLICKED", "KEYBOARD_ACTIVATED",
    "KEY_SENT_NO_NATIVE_CLICK", "CANDIDATE_NOT_UNIQUE", "GUARD_REJECTED",
    "INVENTORY_NOT_ARMED", "ELEMENT_MISSING", "CLICK_FAILED",
    "FOLLOWUP_NOT_STABLE",
))
_EVENT = frozenset(("YES", "NO", "UNKNOWN"))
_STABILITY = frozenset(("NOT_RUN", "STABLE", "GUARD_CHANGED",
                        "DOM_UNSTABLE", "SNAPSHOT_MISSING",
                        "MUTATION_OVERFLOW", "UNKNOWN"))
_ERROR = frozenset(("NONE", "TIMEOUT", "PLAYWRIGHT_ERROR", "OTHER"))
_CHECK_JS = r"""(el, meta) => {
  const key=Symbol.for('auto_daangn_button_inventory_v1');
  return document[key]?.checkFollowup?.(el,meta) || 'UNOBSERVABLE';
}"""
_ARM_NATIVE_JS = r"""el => {
  const key=Symbol.for('auto_daangn_second_native_click_v1');
  try{document[key]?.stop?.();}catch(_){}
  const count={received:false,trusted:false};
  const onClick=e=>{
    if(e.target===el||el.contains(e.target)){
      count.received=true;
      count.trusted=e.isTrusted;
    }
  };
  el.addEventListener('click',onClick,{capture:true,passive:true});
  document[key]={
    snapshot(){return {received:count.received,trusted:count.trusted};},
    stop(){el.removeEventListener('click',onClick,true);delete document[key];}
  };
  return true;
}"""
_NATIVE_SNAPSHOT_JS = r"""() => {
  const key=Symbol.for('auto_daangn_second_native_click_v1');
  return document[key]?.snapshot?.()||null;
}"""
_STOP_NATIVE_JS = r"""() => {
  const key=Symbol.for('auto_daangn_second_native_click_v1');
  try{document[key]?.stop?.();}catch(_){}
  return true;
}"""


def sanitize_second_choice(value) -> dict:
    obj = value if type(value) is dict else {}
    state = obj.get("state")
    guard = obj.get("guard")
    e = obj.get("error_type")
    received = obj.get("native_click_received")
    trusted = obj.get("native_click_trusted")
    return {
        "state": state if type(state) is str and state in _STATES
                 else "NOT_ATTEMPTED",
        "guard": guard if type(guard) is str and guard in _GUARDS
                 else "UNOBSERVABLE",
        "activation_mode": (
            "KEYBOARD_ENTER" if obj.get("activation_mode") == "KEYBOARD_ENTER"
            else "NONE"),
        "native_click_received": (
            received if type(received) is str and received in _EVENT
            else "UNKNOWN"),
        "native_click_trusted": (
            trusted if type(trusted) is str and trusted in _EVENT else "UNKNOWN"),
        "error_type": e if type(e) is str and e in _ERROR else "OTHER",
        "stability_state": (
            obj["stability_state"] if type(obj.get("stability_state")) is str
            and obj["stability_state"] in _STABILITY else "UNKNOWN"),
        "stability_samples": (
            obj["stability_samples"] if type(obj.get("stability_samples")) is int
            and 0 <= obj["stability_samples"] <= 6 else -1),
        "click_attempted": obj.get("click_attempted") is True,
        "click_completed": obj.get("click_completed") is True,
        "authorizes_listings": False,
    }


async def attempt_second_choice(page, region: dict,
                                inventory: RegionButtonInventory,
                                *, on_before_click=None,
                                on_after_click=None,
                                stable_interval_seconds=0.16) -> dict:
    """One accessible Enter on a unique, visible, freshly mounted native button.

    Retain a single anchored Playwright ElementHandle from the identity
    probe through activation; a detached/react-replaced handle cannot be
    silently retargeted. A native event witness is read-only and bounded.
    """
    result = {
        "state": "NOT_ATTEMPTED", "guard": "UNOBSERVABLE",
        "activation_mode": "NONE", "native_click_received": "UNKNOWN",
        "native_click_trusted": "UNKNOWN", "error_type": "NONE",
        "click_attempted": False, "click_completed": False,
        "stability_state": "NOT_RUN", "stability_samples": 0,
    }
    if not inventory.armed:
        result["state"] = "INVENTORY_NOT_ARMED"
        return sanitize_second_choice(result)
    handle = None
    witness_armed = False
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
        result["guard"] = (
            state if type(state) is str and state in _GUARDS else "UNOBSERVABLE")
        if result["guard"] != "READY":
            result["state"] = "GUARD_REJECTED"
            return sanitize_second_choice(result)
        # Check the same ElementHandle across a bounded quiet interval.
        # The candidate must remain in the original dialog with one new
        # target-city node and unchanged visible-button inventory AND
        # mutation revision. DOM remounts invalidate this specific handle.
        previous = None
        consecutive = 0
        result["stability_state"] = "DOM_UNSTABLE"
        for _ in range(6):
            await asyncio.sleep(stable_interval_seconds)
            current_guard = await handle.evaluate(
                _CHECK_JS, {"term": region["term"], "city": region["label"]})
            if current_guard != "READY":
                result["guard"] = (
                    current_guard if type(current_guard) is str
                    and current_guard in _GUARDS else "UNOBSERVABLE")
                result["stability_state"] = "GUARD_CHANGED"
                result["state"] = "FOLLOWUP_NOT_STABLE"
                return sanitize_second_choice(result)
            snap = await page.evaluate(_SAMPLE_JS)
            if type(snap) is not dict:
                result["stability_state"] = "SNAPSHOT_MISSING"
                result["state"] = "FOLLOWUP_NOT_STABLE"
                return sanitize_second_choice(result)
            rev = snap.get("mutation_version")
            if type(rev) is not int or not 0 <= rev <= 1000:
                result["stability_state"] = "SNAPSHOT_MISSING"
                result["state"] = "FOLLOWUP_NOT_STABLE"
                return sanitize_second_choice(result)
            if rev == 1000:
                result["stability_state"] = "MUTATION_OVERFLOW"
                result["state"] = "FOLLOWUP_NOT_STABLE"
                return sanitize_second_choice(result)
            fields = ("visible_buttons","new_dom_buttons",
                      "new_target_buttons","new_region_like_buttons",
                      "visible_target_buttons")
            vals = [snap.get(k) for k in fields]
            if (snap.get("scope") != "ORIGINAL_ONLY"
                    or any(type(v) is not int or v < 0 for v in vals)
                    or vals[0] < 3 or vals[1] < 2 or vals[2] != 1
                    or vals[3] < 2 or vals[4] != 1):
                result["stability_state"] = "DOM_UNSTABLE"
                previous = None
                consecutive = 0
                continue
            marker = tuple(vals) + (rev,)
            consecutive = consecutive+1 if marker == previous else 1
            previous = marker
            result["stability_samples"] = consecutive
            if consecutive >= 3:
                result["stability_state"] = "STABLE"
                break
        if result["stability_state"] != "STABLE":
            result["state"] = "FOLLOWUP_NOT_STABLE"
            return sanitize_second_choice(result)
        witness_armed = await handle.evaluate(_ARM_NATIVE_JS) is True
        if on_before_click is not None:
            await on_before_click()
        result["click_attempted"] = True
        result["activation_mode"] = "KEYBOARD_ENTER"
        try:
            # Standard keyboard/button activation, never JS dispatchEvent,
            # force-click, hidden element or manually constructed request.
            await handle.press("Enter", timeout=1300)
            result["click_completed"] = True
        except Exception as exc:
            kind = type(exc).__name__
            result["error_type"] = (
                "TIMEOUT" if kind == "TimeoutError" else
                "PLAYWRIGHT_ERROR" if kind == "Error" else "OTHER")
        if witness_armed:
            try:
                event = await page.evaluate(_NATIVE_SNAPSHOT_JS)
                if type(event) is dict:
                    result["native_click_received"] = (
                        "YES" if event.get("received") is True else "NO")
                    result["native_click_trusted"] = (
                        "YES" if event.get("trusted") is True else "NO")
            except Exception:
                pass
        if not result["click_completed"]:
            result["state"] = "CLICK_FAILED"
            return sanitize_second_choice(result)
        result["state"] = ("KEYBOARD_ACTIVATED"
                           if result["native_click_received"] == "YES"
                           else "KEY_SENT_NO_NATIVE_CLICK")
        if on_after_click is not None:
            await on_after_click()
        return sanitize_second_choice(result)
    except Exception:
        result["state"] = "CLICK_FAILED"
        result["error_type"] = "OTHER"
        return sanitize_second_choice(result)
    finally:
        if witness_armed:
            try:
                await page.evaluate(_STOP_NATIVE_JS)
            except Exception:
                pass
        if handle is not None:
            try:
                await handle.dispose()
            except Exception:
                pass
