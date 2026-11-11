# -*- coding: utf-8 -*-
"""Read-only API-completion + DOM-stability gate for one owner-approved region click.

No new requests, bypasses, additional clicks, or content exports. All public
evidence is categorical/boolean/capped counts. A READY gate does not authorize
listing locality; the independent fresh Route+visible-control proof still rules.
"""
from __future__ import annotations

import asyncio
from time import monotonic

_MAX_COUNT = 100
_STATES = frozenset((
    "NOT_RUN", "READY", "API_TIMEOUT", "API_BLOCKED", "API_NOT_UNIQUE",
    "API_ID_MISMATCH", "API_SCHEMA_UNKNOWN", "DOM_NOT_FOUND",
    "DOM_NOT_STABLE", "DOM_AMBIGUOUS", "DOM_PROBE_ERROR",
))
_STAGES = ("INITIAL", "FINAL")
_COUNTS = ("candidate_buttons", "target_buttons", "target_city_buttons",
           "dom_mutations")
_PROBE_JS = r"""meta => {
  const key=Symbol.for('auto_daangn_picker_dom_stability_v1');
  try{document[key]?.stop?.();}catch(_){}
  const seen=e=>{
    try{
      const s=getComputedStyle(e);
      return e.isConnected && !!e.getClientRects().length &&
        s.display!=='none' && s.visibility!=='hidden';
    }catch(_){return false;}
  };
  const inputs=[...document.querySelectorAll(
    'input[placeholder*="지역"],input[placeholder*="동네"],[role="dialog"] input')]
    .filter(x=>seen(x)&&x.value===meta.term).slice(0,20);
  if(inputs.length!==1)return {armed:false};
  const dialog=inputs[0].closest('[role="dialog"]');
  if(!dialog)return {armed:false};
  let mutation=0;
  const observer=new MutationObserver(records=>{
    if(records.some(record=>record.type==='childList' ||
        record.type==='characterData' || record.type==='attributes'))
      mutation=Math.min(100,mutation+1);
  });
  observer.observe(dialog,{
    subtree:true,childList:true,characterData:true,attributes:true,
    attributeFilter:['class','hidden','disabled','aria-hidden','aria-expanded']
  });
  const snapshot=()=>{
    if(!dialog.isConnected)return null;
    const buttons=[...dialog.querySelectorAll(
      'button,[role="button"],[role="option"]')]
      .filter(e=>seen(e)&&e.closest('[role="dialog"]')===dialog)
      .slice(0,200);
    const terms=buttons.filter(e=>(e.textContent||'').includes(meta.term));
    const exactCity=terms.filter(e=>(e.textContent||'').includes(meta.city));
    return {
      candidate_buttons:Math.min(100,buttons.length),
      target_buttons:Math.min(100,terms.length),
      target_city_buttons:Math.min(100,exactCity.length),
      dom_mutations:mutation,
      connected:true
    };
  };
  document[key]={snapshot,stop(){observer.disconnect();delete document[key];}};
  return {armed:true,snapshot:snapshot()};
}"""
_SAMPLE_JS = r"""() => {
  const key=Symbol.for('auto_daangn_picker_dom_stability_v1');
  return document[key]?.snapshot?.()||null;
}"""
_STOP_JS = r"""() => {
  const key=Symbol.for('auto_daangn_picker_dom_stability_v1');
  try{document[key]?.stop?.();}catch(_){}
  return true;
}"""


def _safe_snapshot(value):
    src = value if type(value) is dict else {}
    return {k: (src[k] if type(src.get(k)) is int and
                0 <= src[k] <= _MAX_COUNT else -1) for k in _COUNTS}


def sanitize_readiness(value):
    src = value if type(value) is dict else {}
    state = src.get("state")
    stages = src.get("snapshots")
    stages = stages if type(stages) is dict else {}
    return {
        "state": state if type(state) is str and state in _STATES else "NOT_RUN",
        "api_response_count": (src["api_response_count"]
                               if type(src.get("api_response_count")) is int
                               and 0 <= src["api_response_count"] <= 20 else -1),
        "api_unique_candidate": src.get("api_unique_candidate") is True,
        "api_expected_id": src.get("api_expected_id") is True,
        "dom_stable": src.get("dom_stable") is True,
        "stable_samples": (src["stable_samples"]
                           if type(src.get("stable_samples")) is int
                           and 0 <= src["stable_samples"] <= 10 else -1),
        "snapshots": {stage: _safe_snapshot(stages.get(stage))
                      for stage in _STAGES},
        "authorizes_listings": False,
    }


class RegionReadinessWitness:
    """Wait for browser-emitted API response, then 3 stable DOM samples."""

    def __init__(self, region, resolver):
        self.region = region
        self.resolver = resolver
        self.data = {
            "state": "NOT_RUN", "api_response_count": 0,
            "api_unique_candidate": False, "api_expected_id": False,
            "dom_stable": False, "stable_samples": 0,
            "snapshots": {},
        }

    def export(self):
        return sanitize_readiness(self.data)

    async def _stop_dom(self, page):
        try:
            await page.evaluate(_STOP_JS)
        except Exception:
            pass

    async def await_ready(self, page, *, timeout_seconds=7.0,
                          interval_seconds=0.18, stable_needed=3):
        """Fail closed if the exact candidate never stabilizes before deadline."""
        deadline = monotonic() + timeout_seconds
        self.data["state"] = "API_TIMEOUT"
        try:
            # Wait for *the browser's own* first-party region keyword response.
            # The response is already observed and size-limited by resolver.
            while monotonic() < deadline:
                if self.resolver.blocked:
                    self.data["state"] = "API_BLOCKED"
                    return self.export()
                if self.resolver.events:
                    break
                await asyncio.sleep(min(0.12, max(0.01, deadline-monotonic())))
            self.data["api_response_count"] = self.resolver.responses
            if not self.resolver.events:
                return self.export()
            if (self.resolver.responses != 1 or len(self.resolver.events) != 1):
                self.data["state"] = "API_NOT_UNIQUE"
                return self.export()
            event = self.resolver.events[0]
            if type(event) is not dict or event.get("state") != "OBSERVED":
                self.data["state"] = "API_SCHEMA_UNKNOWN"
                return self.export()
            matches = event.get("matches")
            if type(matches) is not list or len(matches) != 1:
                self.data["state"] = "API_NOT_UNIQUE"
                return self.export()
            self.data["api_unique_candidate"] = True
            if str(matches[0]) != str(self.region["id"]):
                self.data["state"] = "API_ID_MISMATCH"
                return self.export()
            self.data["api_expected_id"] = True

            armed = await page.evaluate(_PROBE_JS, {
                "term": self.region["term"], "city": self.region["label"]})
            if type(armed) is not dict or armed.get("armed") is not True:
                self.data["state"] = "DOM_NOT_FOUND"
                return self.export()
            first = armed.get("snapshot")
            if type(first) is not dict:
                self.data["state"] = "DOM_NOT_FOUND"
                return self.export()
            self.data["snapshots"]["INITIAL"] = _safe_snapshot(first)
            self.data["state"] = "DOM_NOT_STABLE"
            prior = None
            streak = 0
            while monotonic() < deadline:
                await asyncio.sleep(min(interval_seconds,
                                        max(0.01, deadline-monotonic())))
                snap = await page.evaluate(_SAMPLE_JS)
                if type(snap) is not dict:
                    self.data["state"] = "DOM_NOT_FOUND"
                    return self.export()
                clean = _safe_snapshot(snap)
                self.data["snapshots"]["FINAL"] = clean
                if clean["target_buttons"] != 1 or clean["target_city_buttons"] != 1:
                    self.data["state"] = "DOM_AMBIGUOUS"
                    prior = None
                    streak = 0
                    continue
                marker = tuple(clean[k] for k in _COUNTS)
                if any(x < 0 for x in marker):
                    self.data["state"] = "DOM_PROBE_ERROR"
                    return self.export()
                streak = streak + 1 if marker == prior else 1
                prior = marker
                self.data["stable_samples"] = min(streak, 10)
                if streak >= stable_needed:
                    # Exact API+DOM settled does not imply click commits locality.
                    if self.resolver.blocked or self.resolver.responses != 1:
                        self.data["state"] = "API_NOT_UNIQUE"
                    else:
                        self.data["dom_stable"] = True
                        self.data["state"] = "READY"
                    return self.export()
            return self.export()
        except Exception:
            self.data["state"] = "DOM_PROBE_ERROR"
            return self.export()
        finally:
            await self._stop_dom(page)
