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
