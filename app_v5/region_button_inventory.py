# -*- coding: utf-8 -*-
"""Read-only button classification in the region picker, never listing authority.

Only capped aggregate counts and fixed-enum button samples leave the browser.
A new DOM node can be a rerender: it is NOT proof of a second selection step.
"""
from __future__ import annotations

_MAX_COUNT = 100
_MAX_SAMPLES = 8
_STAGES = ("AFTER_CLICK", "AFTER_SETTLE")
_ROLES = ("NATIVE_BUTTON", "ARIA_OPTION", "ARIA_BUTTON", "OTHER")
_CANDIDATES = ("TARGET_WITH_CITY", "TARGET_ONLY", "CITY_ONLY",
               "OTHER_REGION_LIKE", "NOT_REGION_LIKE")
_AREAS = ("HEADER", "FOOTER", "LISTBOX", "NEAR_INPUT", "BODY", "OTHER")
_VERTICAL = ("TOP", "MIDDLE", "BOTTOM", "UNKNOWN")
_ACTIONS = ("BACK", "CONFIRM", "CLOSE", "SEARCH", "OTHER")
_ORIGINS = ("ORIGINAL_DIALOG", "OTHER_DIALOG")
_FRESH = ("PRESENT_AT_ARM", "NEW_DOM_NODE")
_SCOPES = ("ORIGINAL_AND_OTHER", "ORIGINAL_ONLY", "OTHER_ONLY",
           "NO_VISIBLE_DIALOG", "UNOBSERVABLE")
_PURPOSE = (
    "NOT_OBSERVABLE", "TARGET_MATCHING_NEW_DOM_NODES",
    "REGION_LIKE_NEW_DOM_NODES", "GENERIC_DOM_REPLACEMENTS_ONLY",
    "NO_NEW_BUTTON_NODES", "DIALOG_SCOPE_UNRESOLVED",
)
_COUNTERS = ("visible_buttons", "new_dom_buttons", "new_target_buttons",
             "new_region_like_buttons", "visible_target_buttons",
             "region_like_buttons", "active_dialogs")
_GROUPS = {
    "role": _ROLES, "candidate": _CANDIDATES, "area": _AREAS,
    "vertical": _VERTICAL, "action": _ACTIONS, "origin": _ORIGINS,
    "freshness": _FRESH,
}

_ARM_JS = r"""(el, meta) => {
  const key=Symbol.for('auto_daangn_button_inventory_v1');
  try { document[key]?.stop?.(); } catch (_) {}
  const root=el.closest('[role="dialog"]');
  if (!root) return {armed:'NOT_OBSERVABLE'};
  const visible=e=>{
    if (!e?.isConnected) return false;
    try {
      const css=getComputedStyle(e);
      return !!e.getClientRects().length && css.visibility!=='hidden' &&
             css.display!=='none';
    } catch (_) {return false;}
  };
  const cap=n=>Math.min(100,n);
  const buttonQuery='button,[role="button"],[role="option"]';
  const baseline=new WeakSet();
  const nodes=[...root.querySelectorAll(buttonQuery)]
    .filter(visible).slice(0,160);
  nodes.forEach(e=>baseline.add(e));
  const getArea=e=>{
    if(e.closest('[role="listbox"]'))return 'LISTBOX';
    if(e.closest('header,[role="banner"]'))return 'HEADER';
    if(e.closest('footer,[role="contentinfo"]'))return 'FOOTER';
    const parent=e.parentElement;
    if(parent && [...parent.querySelectorAll('input')]
         .some(x=>/지역|동네|검색/.test(x.getAttribute('placeholder')||'')))
      return 'NEAR_INPUT';
    return 'BODY';
  };
  const classify=(e, origin)=>{
    // Text is examined in-page for category tests; it is NEVER returned.
    const txt=(e.textContent||'').replace(/\s+/g,' ').trim().slice(0,200);
    const accessible=(e.getAttribute('aria-label')||'').trim().slice(0,120);
    const all=(txt+' '+accessible).trim();
    const target=all.includes(meta.term), city=all.includes(meta.city);
    const candidate=target ? (city?'TARGET_WITH_CITY':'TARGET_ONLY') :
      city?'CITY_ONLY':
      /(?:[가-힣0-9]{1,14}(?:동|읍|면|리))(?:\s|$|[,\-·])/u.test(all)
      ?'OTHER_REGION_LIKE':'NOT_REGION_LIKE';
    const role=e.getAttribute('role');
    const type=role==='option'?'ARIA_OPTION':
      e.tagName==='BUTTON'?'NATIVE_BUTTON':
      role==='button'?'ARIA_BUTTON':'OTHER';
    const action=/^(뒤로|이전|돌아가기)$/.test(all)?'BACK':
      /^(확인|완료|적용|선택|설정|이 동네로 설정|선택하기)$/.test(all)
      ?'CONFIRM':/^(닫기|취소|X|×)$/.test(all)?'CLOSE':
      /^(검색|찾기)$/.test(all)?'SEARCH':'OTHER';
    const rect=e.getBoundingClientRect();
    const pos=rect.height>0 && innerHeight>0?
      rect.top+rect.height/2 < innerHeight/3 ? 'TOP':
      rect.top+rect.height/2 < (innerHeight*2/3) ? 'MIDDLE':'BOTTOM':'UNKNOWN';
    return {
      role:type, candidate, area:getArea(e), vertical:pos, action,
      origin, freshness:baseline.has(e)?'PRESENT_AT_ARM':'NEW_DOM_NODE',
    };
  };
  const sample=()=>{
    const dialogs=[...document.querySelectorAll('[role="dialog"]')].slice(0,60);
    const found=new Set(), rows=[], seenDialogs=new Set();
    let overflow=false;
    for(const dlg of dialogs) {
      const all=[...dlg.querySelectorAll(buttonQuery)];
      if (all.length>160) overflow=true;
      for(const el of all.slice(0,160)) {
        if(!visible(el)||found.has(el))continue;
        if(el.closest('[role="dialog"]')!==dlg)continue; // nested dialog dedupe
        found.add(el);seenDialogs.add(dlg);
        if(rows.length>=160){overflow=true;break;}
        const origin=dlg===root?'ORIGINAL_DIALOG':'OTHER_DIALOG';
        rows.push(classify(el,origin));
      }
      if(rows.length>=160)break;
    }
    if(rows.length>100)overflow=true;
    let original=false, other=false;
    for(const d of seenDialogs){if(d===root)original=true;else other=true;}
    const scope=original&&other?'ORIGINAL_AND_OTHER':original?'ORIGINAL_ONLY':
      other?'OTHER_ONLY':'NO_VISIBLE_DIALOG';
    const inc=(d,k)=>{d[k]=cap(d[k]+1);};
    const groups={};
    for(const [key,allowed] of Object.entries({
      role:['NATIVE_BUTTON','ARIA_OPTION','ARIA_BUTTON','OTHER'],
      candidate:['TARGET_WITH_CITY','TARGET_ONLY','CITY_ONLY',
                 'OTHER_REGION_LIKE','NOT_REGION_LIKE'],
      area:['HEADER','FOOTER','LISTBOX','NEAR_INPUT','BODY','OTHER'],
      vertical:['TOP','MIDDLE','BOTTOM','UNKNOWN'],
      action:['BACK','CONFIRM','CLOSE','SEARCH','OTHER'],
      origin:['ORIGINAL_DIALOG','OTHER_DIALOG'],
      freshness:['PRESENT_AT_ARM','NEW_DOM_NODE']
    })) groups[key]=Object.fromEntries(allowed.map(v=>[v,0]));
    let fresh=0,freshTarget=0,freshRegion=0,targets=0,region=0;
    const samples=[];
    for(const x of rows) {
      for(const kind of Object.keys(groups))inc(groups[kind],x[kind]);
      const target=['TARGET_WITH_CITY','TARGET_ONLY'].includes(x.candidate);
      const regionLike=target||['CITY_ONLY','OTHER_REGION_LIKE'].includes(x.candidate);
      if(target)targets++;
      if(regionLike)region++;
      if(x.freshness==='NEW_DOM_NODE'){
        fresh++;
        if(target)freshTarget++;
        if(regionLike)freshRegion++;
      }
      // Favor newly mounted region-like nodes, then preexisting target.
      if((x.freshness==='NEW_DOM_NODE'&&regionLike)||target)
        if(samples.length<8)samples.push(x);
    }
    return {scope,overflow,
      visible_buttons:cap(rows.length),new_dom_buttons:cap(fresh),
      new_target_buttons:cap(freshTarget),
      new_region_like_buttons:cap(freshRegion),
      visible_target_buttons:cap(targets),region_like_buttons:cap(region),
      active_dialogs:cap(seenDialogs.size),groups,samples};
  };
  document[key]={sample,stop(){delete document[key];}};
  return {armed:'ARMED',baseline:sample()};
}"""

_SAMPLE_JS = r"""() => {
  const key=Symbol.for('auto_daangn_button_inventory_v1');
  return document[key]?.sample?.() || null;
}"""
_STOP_JS = r"""() => {
  const key=Symbol.for('auto_daangn_button_inventory_v1');
  try{document[key]?.stop?.();}catch(_){}
  return true;
}"""


def _safe_count(value):
    return value if type(value) is int and 0 <= value <= _MAX_COUNT else -1


def _safe_button(value):
    obj = value if type(value) is dict else {}
    return {k: (obj.get(k) if type(obj.get(k)) is str and
                obj[k] in allowed else "UNKNOWN")
            for k, allowed in _GROUPS.items()}


def sanitize_button_snapshot(value):
    src = value if type(value) is dict else {}
    groups = src.get("groups")
    groups = groups if type(groups) is dict else {}
    safe_groups = {}
    for field, allowed in _GROUPS.items():
        raw = groups.get(field)
        raw = raw if type(raw) is dict else {}
        safe_groups[field] = {key: _safe_count(raw.get(key)) for key in allowed}
    sample = src.get("samples")
    sample = sample if type(sample) is list else []
    scope = src.get("scope")
    return {
        "scope": scope if type(scope) is str and scope in _SCOPES
                 else "UNOBSERVABLE",
        "overflow": src.get("overflow") is True,
        **{k: _safe_count(src.get(k)) for k in _COUNTERS},
        "groups": safe_groups,
        "samples": [_safe_button(item) for item in sample[:_MAX_SAMPLES]],
    }


def classify_inventory(value):
    src = value if type(value) is dict else {}
    if src.get("armed") != "ARMED":
        return "NOT_OBSERVABLE"
    snaps = src.get("checkpoints")
    snaps = snaps if type(snaps) is dict else {}
    after = snaps.get("AFTER_CLICK")
    after = after if type(after) is dict else {}
    if after.get("scope") in ("UNOBSERVABLE", "NO_VISIBLE_DIALOG", None):
        return "DIALOG_SCOPE_UNRESOLVED"
    newly = after.get("new_dom_buttons", -1)
    target = after.get("new_target_buttons", -1)
    region = after.get("new_region_like_buttons", -1)
    if any(type(x) is not int or x < 0 for x in (newly,target,region)):
        return "NOT_OBSERVABLE"
    if target:
        return "TARGET_MATCHING_NEW_DOM_NODES"
    if region:
        return "REGION_LIKE_NEW_DOM_NODES"
    if newly:
        return "GENERIC_DOM_REPLACEMENTS_ONLY"
    return "NO_NEW_BUTTON_NODES"


def sanitize_button_inventory(value):
    src = value if type(value) is dict else {}
    status = src.get("armed")
    interpretation = src.get("interpretation")
    return {
        "armed": status if type(status) is str and status in
                 ("ARMED","NOT_OBSERVABLE") else "NOT_OBSERVABLE",
        "baseline": sanitize_button_snapshot(src.get("baseline")),
        "checkpoints": {
            stage: sanitize_button_snapshot(
                (src.get("checkpoints") if type(src.get("checkpoints")) is dict
                 else {}).get(stage))
            for stage in _STAGES},
        "interpretation": interpretation if type(interpretation) is str
                          and interpretation in _PURPOSE else "NOT_OBSERVABLE",
        "authorizes_listings": False,
    }


class RegionButtonInventory:
    """Passive witness, attached at the exact uniquely visible option."""

    def __init__(self, region):
        self.region = region
        self.armed = False
        self.baseline = {}
        self.checkpoints = {}

    async def arm(self, locator):
        try:
            raw = await locator.evaluate(
                _ARM_JS, {"term": self.region["term"], "city": self.region["label"]})
            self.armed = (type(raw) is dict and raw.get("armed") == "ARMED")
            self.baseline = sanitize_button_snapshot(
                raw.get("baseline") if type(raw) is dict else {})
        except Exception:
            self.armed = False

    async def checkpoint(self, page, stage):
        if stage not in _STAGES:
            return
        try:
            raw = await page.evaluate(_SAMPLE_JS)
        except Exception:
            raw = None
        self.checkpoints[stage] = sanitize_button_snapshot(raw)

    async def stop(self, page):
        try:
            await page.evaluate(_STOP_JS)
        except Exception:
            pass

    def export(self):
        row = {"armed": "ARMED" if self.armed else "NOT_OBSERVABLE",
               "baseline": self.baseline, "checkpoints": self.checkpoints}
        row["interpretation"] = classify_inventory(row)
        return sanitize_button_inventory(row)
