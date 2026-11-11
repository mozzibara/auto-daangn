# -*- coding: utf-8 -*-
"""Privacy-safe navigation / visible-UI witness around a *real* locality click.

Diagnostic only. Does NOT authorize locality, listings or access controls.
All observations are fixed enums, booleans and capped counters; raw URLs,
HTML, region IDs, cookies, page state and listing content are never retained.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from daangn_v4_1_core import SEARCH_PATH
from app_v5.region_option_events import sanitize_option_event

_CHECKPOINTS = ("BEFORE_CLICK", "AFTER_CLICK", "AFTER_SETTLE")
_URL_VALUES = frozenset(("EXPECTED", "OTHER", "MISSING", "INVALID"))
_CONTROL = frozenset(("TARGET_VISIBLE", "OTHER_VISIBLE", "NOT_VISIBLE",
                     "AMBIGUOUS", "UNOBSERVABLE"))
_DIALOG = frozenset(("OPEN", "CLOSED", "UNOBSERVABLE"))
_CONFIRM = frozenset(("VISIBLE", "NOT_VISIBLE", "AMBIGUOUS", "UNOBSERVABLE"))
_INPUT = frozenset(("EXPECTED", "OTHER", "MISSING", "UNOBSERVABLE"))
_DIALOG_HEADING = frozenset(("PICK_NEIGHBORHOOD", "PICK_REGION", "SEARCH",
                            "TARGET", "OTHER", "MISSING", "UNOBSERVABLE"))
_DIALOG_FOCUS = frozenset(("INPUT", "BUTTON", "OTHER", "OUTSIDE",
                          "NONE", "UNOBSERVABLE"))
_ARIA_MODAL = frozenset(("TRUE", "FALSE", "MISSING", "OTHER", "UNOBSERVABLE"))
_DIALOG_SCOPE = frozenset(("TARGET_CANDIDATE","REGION_SEARCH_INPUT",
                           "MOST_INTERACTIVE","AMBIGUOUS","NONE","UNOBSERVABLE"))
_DIALOG_TRANSITIONS = frozenset((
    "NEW_DIALOG_WITH_CHANGED_CONTROLS", "REPLACED_DIALOG_UNCLASSIFIED",
    "SAME_DIALOG_REMAINS", "DIALOG_CLOSED", "NOT_OBSERVABLE",
))
_EVENT = frozenset(("SEARCH_FETCH", "DOCUMENT_REQUEST", "MAIN_FRAME_NAVIGATED"))
_MAX_EVENTS = 12

# This JS returns *only* fixed semantic classes and capped counts.
# Never return DOM strings, hrefs, storage, cookies, raw location or React state.
_CHECK_UI_JS = r"""meta => {
  const seen = e => {
    try {
      const s=getComputedStyle(e);
      return !!e.getClientRects().length && s.display!=='none' &&
             s.visibility!=='hidden';
    } catch (_) {return false;}
  };
  const controls=[...document.querySelectorAll('button[aria-label]')]
    .filter(e => seen(e) &&
      (e.getAttribute('aria-label')||'').includes('지역 선택')).slice(0,20);
  const target=controls.filter(e =>
    (e.getAttribute('aria-label')||'').includes(meta.term));
  const controlsState=controls.length>1?'AMBIGUOUS':
    controls.length===0?'NOT_VISIBLE':
    target.length===1?'TARGET_VISIBLE':'OTHER_VISIBLE';
  // Some React dialog wrappers have no own CSS box, so visible children
  // do NOT imply getClientRects() on the wrapper itself. Prefer the exact
  // candidate's nearest dialog ancestor, never the document's first dialog.
  const allDialogs=[...document.querySelectorAll('[role="dialog"]')].slice(0,60);
  const lists=[...document.querySelectorAll('[role="listbox"]')]
    .filter(seen).slice(0,20);
  const inputSearch=e => {
    const p=e.getAttribute('placeholder')||'';
    return /지역|동네|검색/.test(p) || e.type==='search';
  };
  const candidates=allDialogs.map(d => {
    const buttons=[...d.querySelectorAll('button,[role="button"]')]
      .filter(seen).slice(0,100);
    const inputs=[...d.querySelectorAll('input,[role="combobox"]')]
      .filter(seen).slice(0,100);
    const regionInputs=inputs.filter(inputSearch);
    const targetButtons=buttons.filter(e=>
      (e.textContent||'').includes(meta.term));
    return {dialog:d,buttons,inputs,regionInputs,targetButtons,
            count:buttons.length+inputs.length,
            visible:seen(d)||buttons.length>0||inputs.length>0};
  }).filter(item=>item.visible);
  const byTarget=candidates.filter(item=>item.targetButtons.length>0);
  const byRegion=candidates.filter(item=>item.regionInputs.length>0);
  let chosen=null, dialogScope='NONE';
  if(byTarget.length===1) {
    chosen=byTarget[0]; dialogScope='TARGET_CANDIDATE';
  } else if(byTarget.length>1) {
    dialogScope='AMBIGUOUS';
  } else if(byRegion.length===1) {
    chosen=byRegion[0]; dialogScope='REGION_SEARCH_INPUT';
  } else if(byRegion.length>1) {
    dialogScope='AMBIGUOUS';
  } else if(candidates.length) {
    const max=Math.max(...candidates.map(x=>x.count));
    const rich=candidates.filter(x=>x.count===max);
    if(max>0 && rich.length===1) {
      chosen=rich[0]; dialogScope='MOST_INTERACTIVE';
    } else {
      dialogScope='AMBIGUOUS';
    }
  }
  const dialogs=candidates.map(x=>x.dialog);
  const dlg=chosen?.dialog||null;
  const dlgButtons=chosen?.buttons||[];
  const dlgInputs=chosen?.inputs||[];
  const searchInputs=chosen?.regionInputs||[];
  const optionButtons=chosen?.targetButtons||[];
  // Exact action-label existence only; do not export any label text.
  const actionButtons=dlgButtons.filter(e => {
      const t=(e.textContent||'').replace(/\s+/g,' ').trim();
      const a=(e.getAttribute('aria-label')||'').trim();
      return /^(확인|완료|적용|선택|설정|다음|이 동네로 설정|선택하기)$/.test(t) ||
             /^(확인|완료|적용|선택|설정|다음)$/.test(a);
    }).slice(0,20);
  const inputs=[...document.querySelectorAll(
    'input[placeholder*="지역"],input[placeholder*="동네"],[role="dialog"] input')]
    .filter(seen).slice(0,20);
  const typed=inputs.filter(e => e.value===meta.term);
  const heading=dlg?[...dlg.querySelectorAll('h1,h2,h3,[role="heading"]')]
    .filter(seen).slice(0,12):[];
  const headingText=(heading[0]?.textContent||'').replace(/\s+/g,' ').trim();
  const headingKind=!heading.length?'MISSING':
    headingText.includes(meta.term)?'TARGET':
    /동네/.test(headingText) && /선택|설정|추가/.test(headingText)?'PICK_NEIGHBORHOOD':
    /지역/.test(headingText) && /선택|설정/.test(headingText)?'PICK_REGION':
    /검색/.test(headingText)?'SEARCH':'OTHER';
  const focus=docFocus => {
    if (!dlg) return 'UNOBSERVABLE';
    if (!docFocus || docFocus===document.body) return 'NONE';
    if (!dlg.contains(docFocus)) return 'OUTSIDE';
    if (docFocus.matches('input,[role="combobox"]')) return 'INPUT';
    if (docFocus.matches('button,[role="button"]')) return 'BUTTON';
    return 'OTHER';
  };
  const dlgModal=dlg?.getAttribute('aria-modal');
  const modal=dlgModal===null?'MISSING':
    dlgModal==='true'?'TRUE':dlgModal==='false'?'FALSE':'OTHER';
  const back=dlgButtons.some(e =>
    /^(뒤로|이전|돌아가기)$/.test((e.textContent||'').replace(/\s+/g,' ').trim()) ||
    /^(뒤로|이전|돌아가기)$/.test(e.getAttribute('aria-label')||''));
  const selectable=dlg?[...dlg.querySelectorAll(
    '[role="option"],[role="radio"],[role="checkbox"],input[type="checkbox"],input[type="radio"]')]
    .filter(seen).length:0;
  const selected=dlg?[...dlg.querySelectorAll(
    '[aria-selected="true"],[aria-pressed="true"],input:checked')]
    .filter(seen).length:0;
  return {
    control:controlsState,
    dialog:dialogs.length?'OPEN':'CLOSED',
    listbox:lists.length?'OPEN':'CLOSED',
    confirm_action:actionButtons.length===0?'NOT_VISIBLE':
      actionButtons.length===1?'VISIBLE':'AMBIGUOUS',
    input:inputs.length===0?'MISSING':
      typed.length===1?'EXPECTED':'OTHER',
    visible_controls:Math.min(controls.length,20),
    visible_dialogs:Math.min(dialogs.length,20),
    visible_listboxes:Math.min(lists.length,20),
    visible_confirm_actions:Math.min(actionButtons.length,20),
    visible_inputs:Math.min(inputs.length,20),
    dialog_scope:dialogScope,
    dialog_heading:headingKind,
    dialog_focus:focus(document.activeElement),
    dialog_aria_modal:modal,
    dialog_has_labelledby:!!dlg?.getAttribute('aria-labelledby'),
    dialog_has_back_action:back,
    dialog_has_selected_control:!!dlg?.querySelector('[aria-selected="true"],[aria-pressed="true"]'),
    dialog_buttons:Math.min(dlgButtons.length,20),
    dialog_target_buttons:Math.min(optionButtons.length,20),
    dialog_search_inputs:Math.min(searchInputs.length,20),
    dialog_selectables:Math.min(selectable,20),
    dialog_selected_controls:Math.min(selected,20)
  };
}"""


def classify_browser_url(raw: str, region: dict) -> dict:
    """Explicit query is *not* server locality proof; never echo the URL."""
    result = {"host": "INVALID", "path": "INVALID",
              "region": "INVALID", "keyword": "INVALID"}
    try:
        u = urlsplit(raw)
        if (u.scheme != "https" or u.hostname != "www.daangn.com"
                or u.port is not None or u.username is not None):
            return result
        result["host"] = "EXPECTED"
        result["path"] = "EXPECTED" if u.path == SEARCH_PATH else "OTHER"
        p = parse_qs(u.query, keep_blank_values=True)
        q = p.get("q", [])
        result["keyword"] = ("EXPECTED" if q == ["HDD"] else
                             "MISSING" if not q else "OTHER")
        slugs = p.get("in", [])
        result["region"] = ("MISSING" if not slugs else
                            "EXPECTED" if slugs == [region["slug"]] else
                            "OTHER" if len(slugs) == 1 else "INVALID")
        return result
    except (TypeError, ValueError, AttributeError):
        return result


def _safe_checkpoint(value) -> dict:
    obj = value if type(value) is dict else {}
    url = obj.get("url")
    if type(url) is not dict:
        url = {"region": obj.get("url_region"),
               "path": obj.get("url_path"),
               "keyword": obj.get("url_keyword")}
    result = {
        "control": obj.get("control") if type(obj.get("control")) is str
                   and obj["control"] in _CONTROL else "UNOBSERVABLE",
        "dialog": obj.get("dialog") if type(obj.get("dialog")) is str
                  and obj["dialog"] in _DIALOG else "UNOBSERVABLE",
        "listbox": obj.get("listbox") if type(obj.get("listbox")) is str
                   and obj["listbox"] in _DIALOG else "UNOBSERVABLE",
        "confirm_action": obj.get("confirm_action")
                          if type(obj.get("confirm_action")) is str
                          and obj["confirm_action"] in _CONFIRM
                          else "UNOBSERVABLE",
        "input": obj.get("input") if type(obj.get("input")) is str
                 and obj["input"] in _INPUT else "UNOBSERVABLE",
        "dialog_scope": obj.get("dialog_scope")
                        if type(obj.get("dialog_scope")) is str
                        and obj["dialog_scope"] in _DIALOG_SCOPE
                        else "UNOBSERVABLE",
        "dialog_heading": obj.get("dialog_heading")
                          if type(obj.get("dialog_heading")) is str
                          and obj["dialog_heading"] in _DIALOG_HEADING
                          else "UNOBSERVABLE",
        "dialog_focus": obj.get("dialog_focus")
                        if type(obj.get("dialog_focus")) is str
                        and obj["dialog_focus"] in _DIALOG_FOCUS
                        else "UNOBSERVABLE",
        "dialog_aria_modal": obj.get("dialog_aria_modal")
                             if type(obj.get("dialog_aria_modal")) is str
                             and obj["dialog_aria_modal"] in _ARIA_MODAL
                             else "UNOBSERVABLE",
        "dialog_has_labelledby": obj.get("dialog_has_labelledby") is True,
        "dialog_has_back_action": obj.get("dialog_has_back_action") is True,
        "dialog_has_selected_control": obj.get("dialog_has_selected_control") is True,
        "url_region": url.get("region") if type(url.get("region")) is str
                      and url["region"] in _URL_VALUES else "INVALID",
        "url_path": url.get("path") if type(url.get("path")) is str
                    and url["path"] in ("EXPECTED", "OTHER", "INVALID")
                    else "INVALID",
        "url_keyword": url.get("keyword") if type(url.get("keyword")) is str
                       and url["keyword"] in ("EXPECTED", "OTHER", "MISSING", "INVALID")
                       else "INVALID",
    }
    for field in ("visible_controls", "visible_dialogs", "visible_listboxes",
                  "visible_confirm_actions", "visible_inputs",
                  "dialog_buttons", "dialog_target_buttons", "dialog_search_inputs",
                  "dialog_selectables", "dialog_selected_controls"):
        val = obj.get(field)
        result[field] = val if type(val) is int and 0 <= val <= 20 else -1
    return result


def classify_commit_trace(trace, *, post_click_region: str = "MISSING") -> str:
    """Make a *diagnostic* hypothesis, never a promotion decision."""
    row = trace if type(trace) is dict else {}
    checkpoints = row.get("checkpoints")
    checkpoints = checkpoints if type(checkpoints) is dict else {}
    after = checkpoints.get("AFTER_CLICK")
    after = after if type(after) is dict else {}
    settled = checkpoints.get("AFTER_SETTLE")
    settled = settled if type(settled) is dict else {}
    first = after.get("control")
    final = settled.get("control")
    if first == "TARGET_VISIBLE" and final == "OTHER_VISIBLE":
        return "VISIBLE_TARGET_REVERTED_TO_OTHER"
    if first == "TARGET_VISIBLE" and final == "NOT_VISIBLE":
        return "VISIBLE_TARGET_LOST"
    if final == "TARGET_VISIBLE" and post_click_region == "OTHER":
        return "UI_TARGET_SERVER_OTHER"
    if final == "TARGET_VISIBLE":
        return "UI_TARGET_VISIBLE_DIAGNOSTIC_ONLY"
    if final == "OTHER_VISIBLE" and post_click_region == "OTHER":
        return "UI_OTHER_AND_SERVER_OTHER"
    if final == "NOT_VISIBLE" and post_click_region == "OTHER":
        return "NO_VISIBLE_COMMIT_SERVER_OTHER"
    if final in ("OTHER_VISIBLE", "NOT_VISIBLE"):
        return "TARGET_CONTROL_NOT_CONFIRMED"
    return "NOT_OBSERVABLE"


_COMMIT_CLASSES = frozenset((
    "VISIBLE_TARGET_REVERTED_TO_OTHER", "VISIBLE_TARGET_LOST",
    "UI_TARGET_SERVER_OTHER", "UI_TARGET_VISIBLE_DIAGNOSTIC_ONLY",
    "UI_OTHER_AND_SERVER_OTHER", "NO_VISIBLE_COMMIT_SERVER_OTHER",
    "TARGET_CONTROL_NOT_CONFIRMED", "NOT_OBSERVABLE",
))


def classify_dialog_stage_transition(value) -> str:
    """Structural stage evidence only; replacement != proof of another step."""
    obj = value if type(value) is dict else {}
    checkpoints = obj.get("checkpoints")
    checkpoints = checkpoints if type(checkpoints) is dict else {}
    before = checkpoints.get("BEFORE_CLICK")
    before = before if type(before) is dict else {}
    after = checkpoints.get("AFTER_SETTLE")
    after = after if type(after) is dict else {}
    event = obj.get("option_event")
    event = event if type(event) is dict else {}
    event_checkpoints = event.get("checkpoints")
    event_checkpoints = event_checkpoints if type(event_checkpoints) is dict else {}
    exact = event_checkpoints.get("AFTER_SETTLE")
    exact = exact if type(exact) is dict else {}
    old = exact.get("dialog_connected")
    opened = after.get("dialog")
    if old == "NO" and opened == "OPEN":
        search_before = before.get("dialog_search_inputs")
        search_after = after.get("dialog_search_inputs")
        after_buttons = after.get("dialog_buttons")
        heading_before = before.get("dialog_heading")
        heading_after = after.get("dialog_heading")
        headings_changed = (
            heading_before in _DIALOG_HEADING and heading_after in _DIALOG_HEADING
            and heading_before not in ("MISSING", "UNOBSERVABLE")
            and heading_after not in ("MISSING", "UNOBSERVABLE")
            and heading_before != heading_after)
        controls_changed = (
            type(search_before) is int and type(search_after) is int
            and type(after_buttons) is int and search_before > 0
            and search_after == 0 and after_buttons > 0)
        return ("NEW_DIALOG_WITH_CHANGED_CONTROLS"
                if headings_changed or controls_changed
                else "REPLACED_DIALOG_UNCLASSIFIED")
    if old == "YES" and opened == "OPEN":
        return "SAME_DIALOG_REMAINS"
    if opened == "CLOSED":
        return "DIALOG_CLOSED"
    return "NOT_OBSERVABLE"


def sanitize_navigation_trace(value) -> dict:
    """Second boundary sanitizer; arbitrary webpage fields cannot escape."""
    source = value if type(value) is dict else {}
    snapshots = source.get("checkpoints")
    snapshots = snapshots if type(snapshots) is dict else {}
    raw_events = source.get("events")
    raw_events = raw_events if type(raw_events) is list else []
    events = []
    for event in raw_events[:_MAX_EVENTS]:
        if type(event) is not dict:
            continue
        kind = event.get("kind")
        if type(kind) is not str or kind not in _EVENT:
            continue
        url = event.get("url")
        if type(url) is not dict:
            url = {"region": event.get("url_region"),
                   "path": event.get("url_path"),
                   "keyword": event.get("url_keyword")}
        events.append({"kind": kind,
                       "url_region": url.get("region") if type(url.get("region")) is str
                       and url["region"] in _URL_VALUES else "INVALID",
                       "url_path": url.get("path") if type(url.get("path")) is str
                       and url["path"] in ("EXPECTED", "OTHER", "INVALID")
                       else "INVALID",
                       "url_keyword": url.get("keyword") if type(url.get("keyword")) is str
                       and url["keyword"] in ("EXPECTED", "OTHER", "MISSING", "INVALID")
                       else "INVALID"})
    count = source.get("event_count")
    dropped = source.get("overflow")
    status = source.get("commit_class")
    return {
        "checkpoints": {
            stage: _safe_checkpoint(snapshots.get(stage)) for stage in _CHECKPOINTS
        },
        "events": events,
        "event_count": count if type(count) is int and 0 <= count <= _MAX_EVENTS else -1,
        "overflow": dropped is True,
        "commit_class": status if type(status) is str and status in _COMMIT_CLASSES
                        else "NOT_OBSERVABLE",
        "option_event": sanitize_option_event(source.get("option_event")),
        "dialog_transition": (
            source.get("dialog_transition")
            if type(source.get("dialog_transition")) is str
            and source["dialog_transition"] in _DIALOG_TRANSITIONS
            else "NOT_OBSERVABLE"),
        "authorizes_listings": False,
    }


class RegionNavigationTrace:
    """Passive listener + three read-only checkpoint snapshots."""
    def __init__(self, region: dict):
        self.region = region
        self.events = []
        self.overflow = False
        self.checkpoints = {}
        self._armed_page = None

    def _record(self, kind, url):
        if len(self.events) >= _MAX_EVENTS:
            self.overflow = True
            return
        self.events.append({"kind": kind,
                            "url": classify_browser_url(url, self.region)})

    def _request(self, request):
        try:
            u = urlsplit(request.url)
            if u.scheme != "https" or u.hostname != "www.daangn.com":
                return
            if u.path != SEARCH_PATH:
                return
            if request.resource_type in ("xhr", "fetch"):
                self._record("SEARCH_FETCH", request.url)
            elif request.is_navigation_request():
                self._record("DOCUMENT_REQUEST", request.url)
        except (TypeError, AttributeError, ValueError):
            pass

    def _navigated(self, frame):
        try:
            if self._armed_page is not None and frame == self._armed_page.main_frame:
                self._record("MAIN_FRAME_NAVIGATED", frame.url)
        except (TypeError, AttributeError, ValueError):
            pass

    def arm(self, page):
        if self._armed_page is not None:
            return
        self._armed_page = page
        page.on("request", self._request)
        page.on("framenavigated", self._navigated)

    def stop(self):
        page = self._armed_page
        self._armed_page = None
        if page is not None:
            page.remove_listener("request", self._request)
            page.remove_listener("framenavigated", self._navigated)

    async def checkpoint(self, page, stage: str):
        if stage not in _CHECKPOINTS:
            return
        data = {}
        try:
            data = await page.evaluate(_CHECK_UI_JS,
                                       {"term": self.region["term"]})
        except Exception:
            pass
        data = data if type(data) is dict else {}
        # URLs are immediately classified and discarded in memory.
        data["url"] = classify_browser_url(page.url, self.region)
        self.checkpoints[stage] = _safe_checkpoint(data)

    def export(self, *, post_click_region="MISSING"):
        raw = {"checkpoints": self.checkpoints, "events": self.events,
               "event_count": len(self.events), "overflow": self.overflow}
        raw["commit_class"] = classify_commit_trace(
            raw, post_click_region=post_click_region)
        return sanitize_navigation_trace(raw)
