# -*- coding: utf-8 -*-
"""Strictly read-only, short-lived DOM event witness for the exact clicked region candidate.

The page-side observer never exports DOM text, outerHTML, URLs, IDs, attributes'
unknown values, event targets, cookies, React state, or customer/listing data.
Its outcome is diagnostic ONLY: it must not relax the verified_region gate.
"""
from __future__ import annotations

_ATTR_ENUMS = {
    "role": {"OPTION", "BUTTON", "MISSING", "OTHER"},
    "parent": {"DIALOG", "LISTBOX", "OTHER"},
    "tag": {"BUTTON", "OTHER"},
    "haspopup": {"DIALOG", "LISTBOX", "MENU", "TRUE", "FALSE", "MISSING", "OTHER"},
    "expanded": {"TRUE", "FALSE", "MISSING", "OTHER"},
    "button_type": {"BUTTON", "SUBMIT", "RESET", "MISSING", "OTHER"},
    "data_state": {"OPEN", "CLOSED", "ACTIVE", "INACTIVE", "CHECKED", "UNCHECKED", "MISSING", "OTHER"},
    "aria_disabled": {"TRUE", "FALSE", "MISSING", "OTHER"},
    "tab_focus": {"FOCUSABLE", "NOT_FOCUSABLE", "UNOBSERVABLE"},
    "aria_label_relation": {"TARGET", "CITY", "OTHER", "MISSING"},
}
_SNAP_ENUMS = {
    "click_trusted": {"YES", "NO", "UNKNOWN"},
    "default_prevented": {"YES", "NO", "UNKNOWN"},
    "target_connected": {"YES", "NO", "UNKNOWN"},
    "dialog_connected": {"YES", "NO", "UNKNOWN"},
    "dialog_visible": {"YES", "NO", "UNKNOWN"},
    "focus": {"OPTION", "INSIDE_DIALOG", "OUTSIDE_DIALOG", "NONE", "UNKNOWN"},
    "expanded": _ATTR_ENUMS["expanded"],
    "event_target": {"BUTTON", "DESCENDANT", "OTHER", "UNKNOWN"},
    "document_bubble": {"YES", "NO", "UNKNOWN"},
}
_COUNTS = ("child_mutations", "attribute_mutations", "added_buttons",
           "added_dialogs", "added_inputs")
_EVENTS = ("POINTER_DOWN", "POINTER_UP", "CLICK_TARGET", "CLICK_DOCUMENT")
_OUTCOMES = {
    "NOT_OBSERVABLE", "CLICK_EVENT_NOT_SEEN", "COMMIT_CORROBORATED_DIAGNOSTIC",
    "SECOND_STAGE_SIGNAL", "CLICK_DELIVERED_NO_COMMIT",
    "EVENT_OBSERVED_OUTCOME_UNKNOWN",
}
_CHECKPOINTS = ("AFTER_CLICK", "AFTER_SETTLE")
_MAX_EVENTS = 8
_MAX_COUNT = 20

# Only the supplied, unique visible candidate button receives listeners.
# The only document listener observes bubbling of clicks *inside that button*.
# These passive listeners and the MutationObserver never alter website events.
_INSTALL_JS = r"""(el, meta) => {
  const key = Symbol.for('auto_daangn_region_option_witness_v1');
  try { document[key]?.stop?.(); } catch (_) {}
  const doc = document;
  const dialog = el.closest('[role="dialog"]');
  const cap = n => Math.min(20, n + 1);
  const classify = (v, allowed) => !v ? 'MISSING' :
    allowed.includes(v.toLowerCase()) ? v.toUpperCase() : 'OTHER';
  const attributes = {
    tag: el.tagName === 'BUTTON' ? 'BUTTON' : 'OTHER',
    parent: el.closest('[role="listbox"]') ? 'LISTBOX' :
            dialog ? 'DIALOG' : 'OTHER',
    role: classify(el.getAttribute('role'), ['option','button']),
    haspopup: classify(el.getAttribute('aria-haspopup'),
                         ['dialog','listbox','menu','true','false']),
    expanded: classify(el.getAttribute('aria-expanded'), ['true','false']),
    button_type: classify(el.getAttribute('type'), ['button','submit','reset']),
    data_state: classify(el.getAttribute('data-state'),
             ['open','closed','active','inactive','checked','unchecked']),
    aria_disabled: classify(el.getAttribute('aria-disabled'), ['true','false']),
    tab_focus: typeof el.tabIndex === 'number' ?
               (el.tabIndex >= 0 ? 'FOCUSABLE' : 'NOT_FOCUSABLE') :
               'UNOBSERVABLE',
    has_aria_controls: !!el.getAttribute('aria-controls'),
    has_aria_describedby: !!el.getAttribute('aria-describedby'),
    inside_form: !!el.closest('form'),
    native_disabled: !!el.disabled,
    aria_label_relation: (() => {
      const label = el.getAttribute('aria-label') || '';
      return !label ? 'MISSING' : label.includes(meta.term) ? 'TARGET' :
             label.includes(meta.city) ? 'CITY' : 'OTHER';
    })()
  };
  // In-page wall clock timestamp is used ONLY inside the current live
  // request chronology witness; never exported in diagnostic snapshots.
  const seen = {events: [], click_trusted:'UNKNOWN', click_epoch_ms:0,
                default_prevented:'UNKNOWN', event_target:'UNKNOWN',
                document_bubble:'UNKNOWN',
                child_mutations:0, attribute_mutations:0,
                added_buttons:0, added_dialogs:0, added_inputs:0};
  const emit = value => {
    if (seen.events.length < 8) seen.events.push(value);
  };
  const onDown = e => {
    if (el.contains(e.target)) emit('POINTER_DOWN');
  };
  const onUp = e => {
    if (el.contains(e.target)) emit('POINTER_UP');
  };
  const onTargetClick = e => {
    if (!el.contains(e.target)) return;
    emit('CLICK_TARGET');
    seen.click_trusted = e.isTrusted ? 'YES' : 'NO';
    if(e.isTrusted && !seen.click_epoch_ms) seen.click_epoch_ms = Date.now();
    seen.event_target = e.target === el ? 'BUTTON' : 'DESCENDANT';
    seen.default_prevented = e.defaultPrevented ? 'YES' : 'NO';
    queueMicrotask(() => {
      seen.default_prevented = e.defaultPrevented ? 'YES' : 'NO';
    });
  };
  const onDocClick = e => {
    if (!el.contains(e.target)) return;
    emit('CLICK_DOCUMENT');
    seen.document_bubble = 'YES';
    seen.default_prevented = e.defaultPrevented ? 'YES' : 'NO';
  };
  el.addEventListener('pointerdown', onDown, {capture:true, passive:true});
  el.addEventListener('pointerup', onUp, {capture:true, passive:true});
  el.addEventListener('click', onTargetClick, {capture:true, passive:true});
  doc.addEventListener('click', onDocClick, {passive:true});
  const root = dialog || el.parentElement;
  const observer = new MutationObserver(records => {
    for (const record of records.slice(0,100)) {
      if (record.type === 'attributes') {
        seen.attribute_mutations = cap(seen.attribute_mutations);
      } else if (record.type === 'childList') {
        seen.child_mutations = cap(seen.child_mutations);
        for (const node of [...record.addedNodes].slice(0,20)) {
          if (node.nodeType !== 1) continue;
          const count = selector => {
            let n = node.matches?.(selector) ? 1 : 0;
            n += node.querySelectorAll?.(selector)?.length || 0;
            return Math.min(20, n);
          };
          seen.added_buttons = Math.min(20, seen.added_buttons +
                                        count('button,[role="button"]'));
          seen.added_dialogs = Math.min(20, seen.added_dialogs +
                                        count('[role="dialog"]'));
          seen.added_inputs = Math.min(20, seen.added_inputs +
                                       count('input,[role="combobox"]'));
        }
      }
    }
  });
  if (root) observer.observe(root, {subtree:true, childList:true,
    attributes:true,
    attributeFilter:['class','hidden','disabled','aria-expanded','aria-selected',
                     'aria-hidden','aria-checked','data-state']});
  const connected = node => !node ? 'UNKNOWN' : node.isConnected ? 'YES' : 'NO';
  const visible = node => {
    if (!node) return 'UNKNOWN';
    if (!node.isConnected) return 'NO';
    try {
      const s = getComputedStyle(node);
      return node.getClientRects().length && s.visibility !== 'hidden' &&
             s.display !== 'none' ? 'YES' : 'NO';
    } catch (_) {return 'UNKNOWN';}
  };
  const focusState = () => {
    const focused=doc.activeElement;
    if (!focused || focused === doc.body) return 'NONE';
    if (focused === el || el.contains(focused)) return 'OPTION';
    if (dialog && dialog.contains(focused)) return 'INSIDE_DIALOG';
    return 'OUTSIDE_DIALOG';
  };
  doc[key] = {
    snapshot() {
      return {
        ...seen,
        target_connected: connected(el),
        dialog_connected: connected(dialog),
        dialog_visible: visible(dialog),
        focus: focusState(),
        expanded: classify(el.getAttribute('aria-expanded'), ['true','false']),
      };
    },
    stop() {
      observer.disconnect();
      el.removeEventListener('pointerdown', onDown, true);
      el.removeEventListener('pointerup', onUp, true);
      el.removeEventListener('click', onTargetClick, true);
      doc.removeEventListener('click', onDocClick);
      delete doc[key];
    }
  };
  return attributes;
}"""

_SNAPSHOT_JS = r"""() => {
  const key=Symbol.for('auto_daangn_region_option_witness_v1');
  return document[key]?.snapshot?.() || null;
}"""

_CLICK_EPOCH_JS = r"""() => {
  const key=Symbol.for('auto_daangn_region_option_witness_v1');
  const witness=document[key]?.snapshot?.();
  const epoch=witness?.click_epoch_ms;
  return witness?.click_trusted==='YES' &&
         Number.isSafeInteger(epoch) && epoch >= 1000000000000 ?
         epoch : null;
}"""

_STOP_JS = r"""() => {
  const key=Symbol.for('auto_daangn_region_option_witness_v1');
  try { document[key]?.stop?.(); } catch (_) {}
  return true;
}"""


def sanitize_option_attributes(value) -> dict:
    src = value if type(value) is dict else {}
    output = {}
    for field, allowed in _ATTR_ENUMS.items():
        raw = src.get(field)
        output[field] = raw if type(raw) is str and raw in allowed else "UNOBSERVABLE"
    for field in ("has_aria_controls", "has_aria_describedby", "inside_form",
                  "native_disabled"):
        output[field] = src.get(field) is True
    return output


def sanitize_option_snapshot(value) -> dict:
    src = value if type(value) is dict else {}
    output = {}
    for field, allowed in _SNAP_ENUMS.items():
        raw = src.get(field)
        output[field] = raw if type(raw) is str and raw in allowed else "UNKNOWN"
    raw_events = src.get("events")
    raw_events = raw_events if type(raw_events) is list else []
    output["events"] = [v for v in raw_events[:_MAX_EVENTS]
                        if type(v) is str and v in _EVENTS]
    for field in _COUNTS:
        raw = src.get(field)
        output[field] = raw if type(raw) is int and 0 <= raw <= _MAX_COUNT else -1
    return output


def classify_option_purpose(observation, *, server_region="MISSING",
                            visible_control="UNOBSERVABLE") -> str:
    """Explain evidence only; no DOM signal alone proves finality."""
    obj = observation if type(observation) is dict else {}
    if obj.get("arm_state") != "ARMED":
        return "NOT_OBSERVABLE"
    stages = obj.get("checkpoints")
    stages = stages if type(stages) is dict else {}
    last = stages.get("AFTER_SETTLE")
    last = last if type(last) is dict else {}
    events = last.get("events")
    events = events if type(events) is list else []
    if not events or "CLICK_TARGET" not in events:
        return "CLICK_EVENT_NOT_SEEN"
    if server_region == "EXPECTED" and visible_control == "TARGET_VISIBLE":
        return "COMMIT_CORROBORATED_DIAGNOSTIC"
    attrs = obj.get("attributes")
    attrs = attrs if type(attrs) is dict else {}
    if (last.get("added_dialogs", 0) > 0 or
            (attrs.get("expanded") != "TRUE" and last.get("expanded") == "TRUE")):
        return "SECOND_STAGE_SIGNAL"
    if server_region == "OTHER" and visible_control in ("OTHER_VISIBLE", "NOT_VISIBLE"):
        return "CLICK_DELIVERED_NO_COMMIT"
    return "EVENT_OBSERVED_OUTCOME_UNKNOWN"


def sanitize_option_event(value) -> dict:
    src = value if type(value) is dict else {}
    stages = src.get("checkpoints")
    stages = stages if type(stages) is dict else {}
    arm = src.get("arm_state")
    purpose = src.get("purpose")
    return {
        "arm_state": arm if type(arm) is str and arm in ("ARMED", "NOT_OBSERVABLE")
                     else "NOT_OBSERVABLE",
        "attributes": sanitize_option_attributes(src.get("attributes")),
        "checkpoints": {stage: sanitize_option_snapshot(stages.get(stage))
                        for stage in _CHECKPOINTS},
        "purpose": purpose if type(purpose) is str and purpose in _OUTCOMES
                   else "NOT_OBSERVABLE",
        "authorizes_listings": False,
    }


class RegionOptionEventWitness:
    """No requests, clicks or data persistence; only the existing exact click is observed."""

    def __init__(self, region: dict):
        self.region = region
        self._armed = False
        self.attributes = {}
        self.checkpoints = {}

    async def arm(self, locator):
        try:
            raw = await locator.evaluate(
                _INSTALL_JS, {"term": self.region["term"],
                              "city": self.region["label"]})
            self.attributes = sanitize_option_attributes(raw)
            self._armed = type(raw) is dict
        except Exception:
            self._armed = False

    async def checkpoint(self, page, stage: str):
        if stage not in _CHECKPOINTS:
            return
        try:
            raw = await page.evaluate(_SNAPSHOT_JS)
        except Exception:
            raw = None
        self.checkpoints[stage] = sanitize_option_snapshot(raw)

    async def trusted_click_epoch_ms(self, page):
        """In-memory chronology only; never part of the public export."""
        try:
            value = await page.evaluate(_CLICK_EPOCH_JS)
            return value if type(value) is int and (
                1_000_000_000_000 <= value <= 9_999_999_999_999) else None
        except Exception:
            return None

    async def stop(self, page):
        try:
            await page.evaluate(_STOP_JS)
        except Exception:
            pass

    def export(self, *, server_region="MISSING", visible_control="UNOBSERVABLE"):
        raw = {"arm_state": "ARMED" if self._armed else "NOT_OBSERVABLE",
               "attributes": self.attributes, "checkpoints": self.checkpoints}
        raw["purpose"] = classify_option_purpose(
            raw, server_region=server_region, visible_control=visible_control)
        return sanitize_option_event(raw)


async def verify_single_target_click_after_timeout(page, witness):
    """Passive strict proof that the already-armed *exact* option was clicked.

    A browser-emitted trusted pointerdown/up and a unique target click
    must all be observed on the same element. No JS events or second
    interactions are generated here. Page transition may close the dialog.
    """
    if witness._armed is not True:
        return False
    try:
        raw = await page.evaluate(_SNAPSHOT_JS)
        snapshot = sanitize_option_snapshot(raw)
        epoch = await witness.trusted_click_epoch_ms(page)
    except Exception:
        return False
    # No duplicate/replayed event and no userland synthetic click.
    return (
        snapshot["events"] == [
            "POINTER_DOWN", "POINTER_UP", "CLICK_TARGET", "CLICK_DOCUMENT"]
        and snapshot["click_trusted"] == "YES"
        and snapshot["document_bubble"] == "YES"
        and snapshot["event_target"] in ("BUTTON", "DESCENDANT")
        and type(epoch) is int and 1_000_000_000_000 <= epoch <=
        9_999_999_999_999
    )
