# -*- coding: utf-8 -*-
"""Passive one-Apply-button browser event witness; no click or body inspection.

Attaches to the exact, already verified visible Apply control. Only stores
bounded event counts and trusted flags in the disposable page. The probe
does not synthesize, force, re-play or retry a browser event.
"""
from __future__ import annotations

_NAMES = ("POINTERDOWN", "POINTERUP", "MOUSEDOWN", "MOUSEUP", "CLICK")
_LIMIT = 20

_ARM = r"""el => {
  const key=Symbol.for('auto_daangn_apply_action_witness_v1');
  try {window[key]?.stop?.()} catch(_) {}
  if(!el||!el.isConnected||el.tagName!=='BUTTON'||el.disabled||
     el.getAttribute('aria-disabled')==='true')return false;
  const box=el.getBoundingClientRect();
  const st=getComputedStyle(el);
  if(box.width<=0||box.height<=0||st.display==='none'||
     st.visibility==='hidden'||st.pointerEvents==='none')return false;
  const types=['pointerdown','pointerup','mousedown','mouseup','click'];
  const counts={},trusted={},handlers={};
  for(const type of types){
    const k=type.toUpperCase();
    counts[k]=0;trusted[k]=0;
    handlers[type]=ev=>{
      counts[k]=Math.min(20,counts[k]+1);
      if(ev.isTrusted)trusted[k]=Math.min(20,trusted[k]+1);
    };
    el.addEventListener(type,handlers[type],{capture:true,passive:true});
  }
  window[key]={
    sample:()=>({armed:true,counts:{...counts},trusted:{...trusted}}),
    stop:()=>{
      for(const type of types)
        el.removeEventListener(type,handlers[type],true);
      delete window[key];
    },
  };
  return true;
}"""
_SAMPLE = r"""() => {
  const key=Symbol.for('auto_daangn_apply_action_witness_v1');
  return window[key]?.sample?.() || null;
}"""
_STOP = r"""() => {
  const key=Symbol.for('auto_daangn_apply_action_witness_v1');
  try{window[key]?.stop?.()}catch(_){}
  return true;
}"""


def _count(v):
    return v if type(v) is int and 0 <= v <= _LIMIT else -1


def sanitize_apply_activation(value):
    data = value if type(value) is dict else {}
    counts = data.get("counts") if type(data.get("counts")) is dict else {}
    trusted = data.get("trusted") if type(data.get("trusted")) is dict else {}
    return {
        "armed": data.get("armed") is True,
        "counts": {name: _count(counts.get(name)) for name in _NAMES},
        "trusted": {name: _count(trusted.get(name)) for name in _NAMES},
        "one_trusted_click": (
            data.get("armed") is True
            and all(_count(counts.get(n)) == 1 and
                    _count(trusted.get(n)) == 1 for n in _NAMES)),
        "authorizes_listings": False,
    }


class FilterApplyActivationWitness:
    def __init__(self):
        self.armed = False

    async def arm(self, locator):
        try:
            self.armed = await locator.evaluate(_ARM) is True
        except Exception:
            self.armed = False
        return self.armed

    async def sample(self, page):
        try:
            return sanitize_apply_activation(await page.evaluate(_SAMPLE))
        except Exception:
            return sanitize_apply_activation(None)

    async def stop(self, page):
        if self.armed:
            try:
                await page.evaluate(_STOP)
            except Exception:
                pass
        self.armed = False
