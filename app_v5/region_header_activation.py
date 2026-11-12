# -*- coding: utf-8 -*-
"""Read-only owner-region button event witness for one approved Chrome attempt.

Records only bounded event counts on the visible region-header button.
Never logs text, selectors derived from private data, DOM, HTML, cookies,
coordinates, URLs, request contents, session state or timestamps.
"""
from __future__ import annotations

_EVENTS = ("POINTERDOWN", "POINTERUP", "MOUSEDOWN", "MOUSEUP", "CLICK")
_COUNT = 20

_INSTALL = r"""() => {
  const key=Symbol.for('auto_daangn_header_activation_v1');
  try{document[key]?.stop?.()}catch(_){}
  const counts={};const trusted={};
  const keys=['pointerdown','pointerup','mousedown','mouseup','click'];
  for(const x of keys){counts[x.toUpperCase()]=0;trusted[x.toUpperCase()]=0;}
  const isHeader=e=>{
    const target=e.target;
    if(!target||typeof target.closest!=='function')return false;
    const button=target.closest('button,[role="button"]');
    if(!button)return false;
    return (button.getAttribute('aria-label')||'').startsWith('지역 선택');
  };
  const handlers={};
  for(const x of keys){
    handlers[x]=e=>{
      if(!isHeader(e))return;
      const k=x.toUpperCase();
      counts[k]=Math.min(20,counts[k]+1);
      if(e.isTrusted)trusted[k]=Math.min(20,trusted[k]+1);
    };
    document.addEventListener(x,handlers[x],{capture:true,passive:true});
  }
  document[key]={
    snapshot(){
      const matches=[...document.querySelectorAll(
        'button[aria-label^="지역 선택"],[role="button"][aria-label^="지역 선택"]'
      )].slice(0,40);
      const visible=matches.filter(x=>{try{
        const s=getComputedStyle(x);
        return x.isConnected&&!!x.getClientRects().length&&
          s.display!=='none'&&s.visibility!=='hidden';
      }catch(_){return false;}});
      return {armed:true,header_candidates:matches.length,
        header_visible:visible.length,
        header_enabled:visible.filter(x=>!x.disabled&&
          x.getAttribute('aria-disabled')!=='true').length,
        counts:{...counts},trusted:{...trusted}};
    },
    stop(){
      for(const x of keys)document.removeEventListener(x,handlers[x],true);
      delete document[key];
    }
  };
  return true;
}"""
_SAMPLE = r"""() => {
  const key=Symbol.for('auto_daangn_header_activation_v1');
  return document[key]?.snapshot?.()||null;
}"""
_STOP = r"""() => {
  const key=Symbol.for('auto_daangn_header_activation_v1');
  try{document[key]?.stop?.()}catch(_){}
  return true;
}"""


def _count(value):
    return value if type(value) is int and 0 <= value <= _COUNT else -1


def sanitize_header_activation(value):
    src=value if type(value) is dict else {}
    c=src.get("counts") if type(src.get("counts")) is dict else {}
    t=src.get("trusted") if type(src.get("trusted")) is dict else {}
    return {
        "armed":src.get("armed") is True,
        "header_candidates":_count(src.get("header_candidates")),
        "header_visible":_count(src.get("header_visible")),
        "header_enabled":_count(src.get("header_enabled")),
        "counts":{k:_count(c.get(k)) for k in _EVENTS},
        "trusted":{k:_count(t.get(k)) for k in _EVENTS},
        "authorizes_listings":False,
    }


class HeaderActivationWitness:
    def __init__(self):
        self.armed=False
    async def arm(self,page):
        try:
            self.armed=await page.evaluate(_INSTALL) is True
        except Exception:
            self.armed=False
        return self.armed
    async def sample(self,page):
        try:
            return sanitize_header_activation(await page.evaluate(_SAMPLE))
        except Exception:
            return sanitize_header_activation(None)
    async def stop(self,page):
        if self.armed:
            try:
                await page.evaluate(_STOP)
            except Exception:
                pass
            self.armed=False

# Diagnostic-only continuation gate. The observable UI must be ready,
# without a second click, event synthesis, navigation, or API request.
# Only returns boolean predicates: never export input contents or DOM.
_CHECK_EMPTY_REGION_INPUT = r"""() => {
  const selector='input[placeholder*="지역"],input[placeholder*="동네"],'+
    '[role="dialog"] input,[role="combobox"]';
  const seen=e=>{try{
    const s=getComputedStyle(e);
    return e.isConnected&&!!e.getClientRects().length&&
      s.display!=='none'&&s.visibility!=='hidden';
  }catch(_){return false;}};
  const all=[...document.querySelectorAll(selector)].slice(0,50);
  const visible=all.filter(seen);
  const valid=visible.filter(x=>
    x.closest('[role="dialog"]') &&
    !x.disabled && !x.readOnly &&
    x.getAttribute('aria-disabled')!=='true' &&
    typeof x.value==='string' && x.value.length===0
  );
  return {
    one_visible_region_input:visible.length===1,
    one_empty_enabled_dialog_input:valid.length===1
  };
}"""


_HEADER_TIMEOUT_REASONS = frozenset((
    "NOT_INVOKED", "PAGE_NOT_PUBLIC_SEARCH", "WITNESS_NOT_ARMED",
    "WITNESS_UNAVAILABLE", "HEADER_CONTROL_NOT_UNIQUE",
    "EVENTS_NOT_UNIQUE_TRUSTED", "INPUT_PROBE_ERROR",
    "INPUT_NOT_UNIQUE_VISIBLE", "INPUT_NOT_EMPTY_ENABLED_DIALOG",
    "VERIFIED", "UNOBSERVABLE",
))


def sanitize_header_timeout_reason(value):
    return value if type(value) is str and value in _HEADER_TIMEOUT_REASONS else "UNOBSERVABLE"


async def assess_header_click_timeout_without_reclick(page, witness):
    """Return only a finite reason and boolean; inspect, never click.

    A real Playwright header click may have dispatched while its action promise
    times out. Require one exact trusted event sequence and one empty, enabled
    visible input inside the public region dialog; no new request or action.
    """
    if witness.armed is not True:
        return {"verified": False, "reason": "WITNESS_NOT_ARMED"}
    snapshot = await witness.sample(page)
    if snapshot["armed"] is not True:
        return {"verified": False, "reason": "WITNESS_UNAVAILABLE"}
    if any(snapshot[key] != 1 for key in (
            "header_candidates", "header_visible", "header_enabled")):
        return {"verified": False, "reason": "HEADER_CONTROL_NOT_UNIQUE"}
    if any(snapshot["trusted"][event] != 1
           or snapshot["counts"][event] != 1 for event in _EVENTS):
        return {"verified": False, "reason": "EVENTS_NOT_UNIQUE_TRUSTED"}
    try:
        ready = await page.evaluate(_CHECK_EMPTY_REGION_INPUT)
    except Exception:
        return {"verified": False, "reason": "INPUT_PROBE_ERROR"}
    if type(ready) is not dict or (
            ready.get("one_visible_region_input") is not True):
        return {"verified": False, "reason": "INPUT_NOT_UNIQUE_VISIBLE"}
    if ready.get("one_empty_enabled_dialog_input") is not True:
        return {"verified": False, "reason": "INPUT_NOT_EMPTY_ENABLED_DIALOG"}
    return {"verified": True, "reason": "VERIFIED"}


async def verify_header_click_timeout_without_reclick(page, witness):
    """Compatibility boolean gate. Keep all existing default callers strict."""
    return (await assess_header_click_timeout_without_reclick(
        page, witness))["verified"]
