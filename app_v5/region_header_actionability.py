# -*- coding: utf-8 -*-
"""Read-only finite actionability snapshots of the public region header.

No screenshots, DOM HTML/text/attributes, input contents, raw coordinates,
overlapping element identity, URLs, cookies, requests or timestamps exported.
This cannot grant click/region validation or trigger retries.
"""
from __future__ import annotations

_PROBE = r"""() => {
  const doc=document;
  const known=['button[aria-label^="지역 선택"]',
               '[role="button"][aria-label^="지역 선택"]'];
  const controls=[...doc.querySelectorAll(known.join(','))].slice(0,40);
  const result={
    state:'OBSERVED',
    document_visibility:doc.visibilityState==='visible'?'VISIBLE':
      doc.visibilityState==='hidden'?'HIDDEN':'OTHER',
    document_ready:doc.readyState==='complete'?'COMPLETE':
      doc.readyState==='interactive'?'INTERACTIVE':
      doc.readyState==='loading'?'LOADING':'UNOBSERVABLE',
    control_count:Math.min(20,controls.length),
    control_visible:'UNOBSERVABLE',
    control_enabled:'UNOBSERVABLE',
    geometry:'UNOBSERVABLE',
    center_hit:'UNOBSERVABLE',
    pointer_events:'UNOBSERVABLE',
  };
  if(controls.length!==1)return result;
  try{
    const el=controls[0],style=getComputedStyle(el),box=el.getBoundingClientRect();
    const visible=el.isConnected&&el.getClientRects().length>0&&
      style.visibility!=='hidden'&&style.display!=='none'&&
      box.width>0&&box.height>0;
    const enabled=!el.disabled&&el.getAttribute('aria-disabled')!=='true';
    result.control_visible=visible?'YES':'NO';
    result.control_enabled=enabled?'YES':'NO';
    result.pointer_events=style.pointerEvents==='none'?'NONE':'ENABLED';
    if(!visible){
      result.geometry='EMPTY';
      result.center_hit='NO_ELEMENT';
      return result;
    }
    const viewW=window.innerWidth,viewH=window.innerHeight;
    if(viewW<=0||viewH<=0)return result;
    if(box.bottom<=0||box.right<=0||box.left>=viewW||box.top>=viewH){
      result.geometry='OUTSIDE_VIEWPORT';
    }else if(box.top>=0&&box.left>=0&&
             box.right<=viewW&&box.bottom<=viewH){
      result.geometry='IN_VIEWPORT';
    }else{
      result.geometry='PARTIAL_VIEWPORT';
    }
    const cx=box.left+box.width/2,cy=box.top+box.height/2;
    if(cx<0||cy<0||cx>=viewW||cy>=viewH){
      result.center_hit='OUTSIDE_VIEWPORT';
    }else{
      const top=doc.elementFromPoint(cx,cy);
      result.center_hit=(!top)?'NO_ELEMENT':
        (top===el||el.contains(top))?'TARGET':'OTHER_ELEMENT';
    }
  }catch(_){
    result.state='UNOBSERVABLE';
  }
  return result;
}"""

_STATES = ("OBSERVED", "UNOBSERVABLE")
_VISIBILITY = ("VISIBLE", "HIDDEN", "OTHER", "UNOBSERVABLE")
_READY = ("COMPLETE", "INTERACTIVE", "LOADING", "UNOBSERVABLE")
_YESNO = ("YES", "NO", "UNOBSERVABLE")
_POINTER = ("ENABLED", "NONE", "UNOBSERVABLE")
_GEOMETRY = (
    "IN_VIEWPORT", "PARTIAL_VIEWPORT", "OUTSIDE_VIEWPORT", "EMPTY",
    "UNOBSERVABLE",
)
_HIT = (
    "TARGET", "OTHER_ELEMENT", "NO_ELEMENT", "OUTSIDE_VIEWPORT",
    "UNOBSERVABLE",
)


def _enum(raw, allowed):
    return raw if type(raw) is str and raw in allowed else "UNOBSERVABLE"


def sanitize_header_actionability(raw):
    v = raw if type(raw) is dict else {}
    count = v.get("control_count")
    return {
        "state": _enum(v.get("state"), _STATES),
        "document_visibility": _enum(v.get("document_visibility"), _VISIBILITY),
        "document_ready": _enum(v.get("document_ready"), _READY),
        "control_count": (
            count if type(count) is int and 0 <= count <= 20 else -1),
        "control_visible": _enum(v.get("control_visible"), _YESNO),
        "control_enabled": _enum(v.get("control_enabled"), _YESNO),
        "geometry": _enum(v.get("geometry"), _GEOMETRY),
        "center_hit": _enum(v.get("center_hit"), _HIT),
        "pointer_events": _enum(v.get("pointer_events"), _POINTER),
        "authorizes_listings": False,
    }


async def sample_header_actionability(page):
    """One bounded page.evaluate, no mouse/input changes and no retries."""
    try:
        return sanitize_header_actionability(await page.evaluate(_PROBE))
    except Exception:
        return sanitize_header_actionability(None)
