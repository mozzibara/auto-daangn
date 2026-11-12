# -*- coding: utf-8 -*-
"""Passive phase diagnostics for delayed region picker and browser-generated API.

Never sends requests, clicks, types, modifies DOM or reads response bodies.
Only expected first-party region-keyword endpoint is classified. No raw URL,
query, region strings, cookies, HTML, request errors or seller data exported.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from app_v5.region_input_events import sample_region_focus

_STAGES = ("AFTER_PICKER_OPEN_500MS", "AFTER_CORE_RETURN", "AFTER_SETTLE_4200MS")
_COUNTS = ("inputs", "visible_inputs", "dialog_inputs",
           "visible_dialog_inputs", "region_buttons", "visible_dialogs")
_REQUEST_COUNTS = ("target_requests", "other_keyword_requests",
                   "missing_keyword_requests", "target_responses_200",
                   "target_responses_blocked", "target_responses_other",
                   "target_request_failures")
_API_STATUS = frozenset((
    "NO_TARGET_REQUEST", "REQUEST_WITHOUT_RESPONSE",
    "RESPONSE_200", "ACCESS_RESTRICTED", "RESPONSE_OTHER",
    "REQUEST_FAILED", "INCONCLUSIVE",
))
_PHASE_ERROR = frozenset((
    "NONE", "REGION_INPUT_NOT_FOUND", "REGION_INPUT_NOT_EMPTY",
    "REGION_SUGGESTION_NOT_READY", "REGION_OPTION_NOT_FOUND",
    "AMBIGUOUS_REGION_OPTIONS", "REGION_OPTION_NOT_VISIBLE",
    "REGION_OPTION_DISABLED", "UNSUPPORTED_INPUT_MODE",
    "UNSUPPORTED_ACTIVATION", "STEP_EXCEPTION", "OTHER_KNOWN_STEP",
))
_READINESS = frozenset((
    "NOT_RUN", "READY", "API_TIMEOUT", "API_BLOCKED", "API_NOT_UNIQUE",
    "API_ID_MISMATCH", "API_SCHEMA_UNKNOWN", "DOM_NOT_FOUND",
    "DOM_NOT_STABLE", "DOM_AMBIGUOUS", "DOM_PROBE_ERROR",
))
_FOCUS = frozenset(("REGION_INPUT", "DIALOG_OTHER", "OUTSIDE_DIALOG",
                    "BODY", "UNOBSERVABLE"))

# Same input selector as the first-party UI routine. This is a read only
# snapshot of shape/visibility. Do not inspect input.value or its placeholder.
_JS = r"""() => {
  const cap=n=>Number.isInteger(n)&&n>=0?Math.min(n,40):-1;
  const seen=e=>{try{
    const s=getComputedStyle(e);
    return e.isConnected&&!!e.getClientRects().length&&
       s.display!=='none'&&s.visibility!=='hidden';
  }catch(_){return false;}};
  const inputs=[...document.querySelectorAll(
    'input[placeholder*="지역"],input[placeholder*="동네"],'+
    '[role="dialog"] input,[role="combobox"]')].slice(0,100);
  const dialogs=[...document.querySelectorAll('[role="dialog"]')].slice(0,40);
  const buttons=[...document.querySelectorAll('button,[role="button"]')].slice(0,150);
  return {
    inputs:cap(inputs.length),
    visible_inputs:cap(inputs.filter(seen).length),
    dialog_inputs:cap(inputs.filter(e=>!!e.closest('[role="dialog"]')).length),
    visible_dialog_inputs:cap(inputs.filter(e=>seen(e)&&
      !!e.closest('[role="dialog"]')).length),
    visible_dialogs:cap(dialogs.filter(seen).length),
    region_buttons:cap(buttons.filter(e=>seen(e)&&(
      (e.getAttribute('aria-label')||'').includes('지역 선택'))).length)
  };
}"""


def _count(x):
    return x if type(x) is int and 0 <= x <= 40 else -1


def _known(value, valid, otherwise):
    return value if type(value) is str and value in valid else otherwise


def sanitize_phase(value):
    data = value if type(value) is dict else {}
    return {
        **{key: _count(data.get(key)) for key in _COUNTS},
        "focus": _known(data.get("focus"), _FOCUS, "UNOBSERVABLE"),
    }


def phase_error(raw):
    if raw is None:
        return "NONE"
    if type(raw) is not str:
        return "OTHER_KNOWN_STEP"
    result = {
        "region_input_not_found": "REGION_INPUT_NOT_FOUND",
        "region_input_not_empty_for_keys": "REGION_INPUT_NOT_EMPTY",
        "region_suggestion_not_ready": "REGION_SUGGESTION_NOT_READY",
        "matching_region_option_not_found": "REGION_OPTION_NOT_FOUND",
        "ambiguous_region_options": "AMBIGUOUS_REGION_OPTIONS",
        "region_option_not_visible": "REGION_OPTION_NOT_VISIBLE",
        "region_option_not_enabled": "REGION_OPTION_DISABLED",
        "unsupported_search_input_mode": "UNSUPPORTED_INPUT_MODE",
        "unsupported_first_activation_mode": "UNSUPPORTED_ACTIVATION",
    }
    return result.get(raw, "STEP_EXCEPTION" if raw in (
        "TimeoutError", "Error", "RuntimeError", "ValueError",
    ) else "OTHER_KNOWN_STEP")


def _is_region_request(url, expected_term):
    """Only classify the exact first-party documented endpoint and query."""
    try:
        u = urlsplit(url)
        if u.scheme != "https" or u.hostname != "www.daangn.com" or (
                u.port is not None or u.path != "/kr/api/v1/regions/keyword"):
            return None
        q = parse_qs(u.query).get("keyword")
        if not q:
            return "missing_keyword_requests"
        if q == [expected_term]:
            return "target_requests"
        return "other_keyword_requests"
    except (TypeError, ValueError, AttributeError):
        return None


def sanitize_picker_phases(value):
    src = value if type(value) is dict else {}
    phases = src.get("phases") if type(src.get("phases")) is dict else {}
    api = src.get("api") if type(src.get("api")) is dict else {}
    state = _known(api.get("state"), _API_STATUS, "INCONCLUSIVE")
    return {
        "phases": {stage: sanitize_phase(phases.get(stage))
                   for stage in _STAGES},
        "step_error": _known(src.get("step_error"),
                             _PHASE_ERROR, "OTHER_KNOWN_STEP"),
        "readiness_state": _known(src.get("readiness_state"),
                                  _READINESS, "NOT_RUN"),
        "picker_opened": src.get("picker_opened") is True,
        "api": {
            **{name: _count(api.get(name)) for name in _REQUEST_COUNTS},
            "state": state,
        },
        "delayed_input_observed": (
            src.get("delayed_input_observed") is True),
        "authorizes_listings": False,
    }


class RegionPickerPhaseWitness:
    def __init__(self, region):
        self.term = region["term"]  # RAM only; never exported
        self.phases = {}
        self.counts = {key: 0 for key in _REQUEST_COUNTS}
        self.targets = set()
        self.api_armed = False
        self.picker_opened = False

    def _increase(self, key):
        self.counts[key] = min(40, self.counts[key] + 1)

    async def sample(self, page, stage):
        if stage not in _STAGES:
            return
        try:
            dom = await page.evaluate(_JS)
        except Exception:
            dom = {}
        try:
            focus = await sample_region_focus(page)
        except Exception:
            focus = "UNOBSERVABLE"
        self.phases[stage] = sanitize_phase({
            **(dom if type(dom) is dict else {}), "focus": focus})

    def on_request(self, request):
        try:
            if request.method != "GET" or request.resource_type not in (
                    "fetch", "xhr"):
                return
            kind = _is_region_request(request.url, self.term)
            if kind is not None:
                self._increase(kind)
                if kind == "target_requests" and len(self.targets) < 40:
                    self.targets.add(request)
        except (AttributeError, TypeError, ValueError):
            pass

    def on_response(self, response):
        try:
            req = response.request
            if req not in self.targets:
                return
            self.targets.discard(req)
            if response.status == 200:
                self._increase("target_responses_200")
            elif response.status in (401, 403, 429):
                self._increase("target_responses_blocked")
            else:
                self._increase("target_responses_other")
        except (AttributeError, TypeError, ValueError):
            pass

    def on_requestfailed(self, request):
        if request in self.targets:
            self.targets.discard(request)
            self._increase("target_request_failures")

    def export(self, *, error=None, readiness=None):
        api = self.counts.copy()
        if api["target_responses_blocked"]:
            state = "ACCESS_RESTRICTED"
        elif api["target_responses_200"] and not (
                api["target_responses_other"] or api["target_request_failures"]):
            state = "RESPONSE_200"
        elif api["target_request_failures"]:
            state = "REQUEST_FAILED"
        elif api["target_responses_other"]:
            state = "RESPONSE_OTHER"
        elif api["target_requests"]:
            state = "REQUEST_WITHOUT_RESPONSE"
        else:
            state = "NO_TARGET_REQUEST"
        earlier = self.phases.get("AFTER_PICKER_OPEN_500MS", {})
        later = self.phases.get("AFTER_SETTLE_4200MS", {})
        delayed = (
            earlier.get("visible_inputs") == 0
            and type(later.get("visible_inputs")) is int
            and later["visible_inputs"] > 0
        )
        return sanitize_picker_phases({
            "phases": self.phases, "step_error": phase_error(error),
            "readiness_state": readiness,
            "picker_opened": self.picker_opened,
            "api": {**api, "state": state},
            "delayed_input_observed": delayed,
        })
