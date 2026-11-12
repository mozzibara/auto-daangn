# -*- coding: utf-8 -*-
"""Read-only, privacy-bounded fixed-event witness on a single visible input.

Never exports typed characters, key names, input values, HTML, IDs, URLs,
coordinates, selections or event timestamps; never performs UI actions.
"""
from __future__ import annotations

EVENTS = (
    "FOCUS", "BLUR", "FOCUSIN", "FOCUSOUT", "KEYDOWN", "KEYUP",
    "BEFOREINPUT", "INPUT", "CHANGE", "COMPOSITIONSTART",
    "COMPOSITIONUPDATE", "COMPOSITIONEND",
)
_MAX_SEQ = 48
_MAX_COUNT = 48
INPUT_TYPES = ("INSERT_TEXT", "INSERT_COMPOSITION", "DELETE", "OTHER")
FOCUS_STATES = frozenset(("REGION_INPUT", "DIALOG_OTHER", "OUTSIDE_DIALOG",
                          "BODY", "UNOBSERVABLE"))

def sanitize_region_focus(value):
    return value if type(value) is str and value in FOCUS_STATES else "UNOBSERVABLE"

_JS_FOCUS = r"""() => {
  const active=document.activeElement;
  if(!active||active===document.body||active===document.documentElement)
    return 'BODY';
  const dialog=active.closest?.('[role="dialog"]');
  if(!dialog) return 'OUTSIDE_DIALOG';
  if(active.matches?.('input,[role="combobox"]')){
    const p=active.getAttribute('placeholder')||'';
    if(/지역|동네|검색/.test(p)||active.type==='search'||
       active.getAttribute('role')==='combobox') return 'REGION_INPUT';
  }
  return 'DIALOG_OTHER';
}"""

async def sample_region_focus(page):
    try:
        return sanitize_region_focus(await page.evaluate(_JS_FOCUS))
    except Exception:
        return "UNOBSERVABLE"


_JS_INSTALL = r"""el => {
  const key=Symbol.for('auto_daangn_chrome_input_event_v1');
  try { document[key]?.stop?.(); } catch(_) {}
  const allowed=[
    'focus','blur','focusin','focusout','keydown','keyup','beforeinput',
    'input','change','compositionstart','compositionupdate','compositionend'
  ];
  const counts={}, trusted={}, sequence=[];
  allowed.forEach(x=>{counts[x.toUpperCase()]=0;trusted[x.toUpperCase()]=0});
  let overflow=false;
  const inputTypes={INSERT_TEXT:0,INSERT_COMPOSITION:0,DELETE:0,OTHER:0};
  let composingEvents=0;
  const typeOfInput=e=>{
    const t=e.inputType;
    if(t==='insertText'||t==='insertReplacementText')return 'INSERT_TEXT';
    if(t==='insertCompositionText'||t==='insertFromComposition')return 'INSERT_COMPOSITION';
    if(typeof t==='string'&&t.startsWith('delete'))return 'DELETE';
    return 'OTHER';
  };
  const handlers=new Map();
  for (const name of allowed) {
    const onEvent=e=>{
      if(e.target!==el)return;
      const upper=name.toUpperCase();
      counts[upper]=Math.min(48,counts[upper]+1);
      if(e.isTrusted)trusted[upper]=Math.min(48,trusted[upper]+1);
      if(e.isComposing===true)composingEvents=Math.min(48,composingEvents+1);
      if(name==='input'||name==='beforeinput'){
        const kind=typeOfInput(e);
        inputTypes[kind]=Math.min(48,inputTypes[kind]+1);
      }
      if(sequence.length<48)sequence.push(upper);else overflow=true;
    };
    el.addEventListener(name,onEvent,{capture:true,passive:true});
    handlers.set(name,onEvent);
  }
  document[key]={
    snapshot(){
      return {armed:el.isConnected,counts:{...counts},
        trusted:{...trusted},sequence:[...sequence],overflow,
        input_types:{...inputTypes},composing_events:composingEvents};
    },
    stop(){
      for (const [name,fn] of handlers)
        el.removeEventListener(name,fn,true);
      handlers.clear();delete document[key];
    }
  };
  return el.isConnected;
}"""

_JS_SNAPSHOT = r"""() => {
  const key=Symbol.for('auto_daangn_chrome_input_event_v1');
  return document[key]?.snapshot?.()||null;
}"""

_JS_STOP = r"""() => {
  const key=Symbol.for('auto_daangn_chrome_input_event_v1');
  try{document[key]?.stop?.()}catch(_){}
  return true;
}"""


def sanitize_input_events(raw) -> dict:
    src = raw if type(raw) is dict else {}
    counts = src.get("counts") if type(src.get("counts")) is dict else {}
    trusted = src.get("trusted") if type(src.get("trusted")) is dict else {}
    seq = src.get("sequence") if type(src.get("sequence")) is list else []
    input_types = (src.get("input_types")
                   if type(src.get("input_types")) is dict else {})
    return {
        "armed": src.get("armed") is True,
        "counts": {
            name: counts[name] if type(counts.get(name)) is int
            and 0 <= counts[name] <= _MAX_COUNT else -1
            for name in EVENTS
        },
        "trusted": {
            name: trusted[name] if type(trusted.get(name)) is int
            and 0 <= trusted[name] <= _MAX_COUNT else -1
            for name in EVENTS
        },
        "sequence": [x for x in seq[:_MAX_SEQ] if type(x) is str and x in EVENTS],
        "truncated": src.get("overflow") is True
                     or src.get("truncated") is True
                     or len(seq) > _MAX_SEQ,
        "input_types": {
            name: input_types[name] if type(input_types.get(name)) is int
            and 0 <= input_types[name] <= _MAX_COUNT else -1
            for name in INPUT_TYPES
        },
        "composing_events": (src["composing_events"]
                             if type(src.get("composing_events")) is int
                             and 0 <= src["composing_events"] <= _MAX_COUNT else -1),
        "authorizes_listings": False,
    }


class RegionInputEventWitness:
    """Install prior to entering the target input; snapshot and always stop."""

    def __init__(self):
        self.armed = False

    async def arm(self, locator) -> bool:
        try:
            self.armed = await locator.evaluate(_JS_INSTALL) is True
        except Exception:
            self.armed = False
        return self.armed

    async def sample(self, page) -> dict:
        try:
            raw = await page.evaluate(_JS_SNAPSHOT)
        except Exception:
            raw = None
        return sanitize_input_events(raw)

    async def stop(self, page):
        try:
            await page.evaluate(_JS_STOP)
        except Exception:
            pass
