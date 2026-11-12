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
  const handlers=new Map();
  for (const name of allowed) {
    const onEvent=e=>{
      if(e.target!==el)return;
      const upper=name.toUpperCase();
      counts[upper]=Math.min(48,counts[upper]+1);
      if(e.isTrusted)trusted[upper]=Math.min(48,trusted[upper]+1);
      if(sequence.length<48)sequence.push(upper);else overflow=true;
    };
    el.addEventListener(name,onEvent,{capture:true,passive:true});
    handlers.set(name,onEvent);
  }
  document[key]={
    snapshot(){
      return {armed:el.isConnected,counts:{...counts},
        trusted:{...trusted},sequence:[...sequence],overflow};
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
        "truncated": src.get("overflow") is True or len(seq) > _MAX_SEQ,
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
