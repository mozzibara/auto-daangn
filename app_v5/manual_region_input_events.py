# -*- coding: utf-8 -*-
"""Document-delegated, passive witness for the owner's dynamically created region input.

Arms BEFORE the owner opens the region dialog. No raw keystrokes, IME text,
field values, URLs, form data, attributes, or timestamps leave the page.
This module has no locator, keyboard, click, navigation or network actions.
"""
from __future__ import annotations

from app_v5.region_input_events import sanitize_input_events

_JS_ARM = r"""() => {
  const key=Symbol.for('auto_daangn_manual_input_events_v1');
  try { document[key]?.stop?.(); } catch (_) {}
  const names=['focus','blur','focusin','focusout','keydown','keyup',
    'beforeinput','input','change','compositionstart','compositionupdate','compositionend'];
  const counts={},trusted={},inputTypes={
    INSERT_TEXT:0,INSERT_COMPOSITION:0,DELETE:0,OTHER:0};
  const sequence=[];
  for(const name of names){
    counts[name.toUpperCase()]=0;
    trusted[name.toUpperCase()]=0;
  }
  let composingEvents=0,overflow=false,observed=false;
  const qualifies=el=>{
    if(!(el instanceof Element)||
       !el.matches('input,[role="combobox"]'))return false;
    const dialog=el.closest('[role="dialog"]');
    if(!dialog) return false;
    const placeholder=el.getAttribute('placeholder')||'';
    return /지역|동네|검색/.test(placeholder)||
      el.getAttribute('role')==='combobox'||el.type==='search';
  };
  const classify=e=>{
    const t=e.inputType;
    if(t==='insertText'||t==='insertReplacementText')return 'INSERT_TEXT';
    if(t==='insertCompositionText'||t==='insertFromComposition')
      return 'INSERT_COMPOSITION';
    if(typeof t==='string'&&t.startsWith('delete'))return 'DELETE';
    return 'OTHER';
  };
  const handlers=new Map();
  for(const name of names){
    const fn=e=>{
      if(!qualifies(e.target))return;
      observed=true;
      const kind=name.toUpperCase();
      counts[kind]=Math.min(48,counts[kind]+1);
      if(e.isTrusted)trusted[kind]=Math.min(48,trusted[kind]+1);
      if(e.isComposing===true)composingEvents=Math.min(48,composingEvents+1);
      if(name==='input'||name==='beforeinput'){
        const inputKind=classify(e);
        inputTypes[inputKind]=Math.min(48,inputTypes[inputKind]+1);
      }
      if(sequence.length<48)sequence.push(kind);else overflow=true;
    };
    document.addEventListener(name,fn,{capture:true,passive:true});
    handlers.set(name,fn);
  }
  document[key]={
    snapshot(){
      return {armed:true,observed_input:observed,counts:{...counts},
        trusted:{...trusted},sequence:[...sequence],overflow,
        input_types:{...inputTypes},composing_events:composingEvents};
    },
    stop(){
      for(const [name,fn] of handlers)document.removeEventListener(name,fn,true);
      handlers.clear();
      delete document[key];
    }
  };
  return true;
}"""

_JS_READ = r"""() => {
  const key=Symbol.for('auto_daangn_manual_input_events_v1');
  return document[key]?.snapshot?.()||null;
}"""

_JS_STOP = r"""() => {
  const key=Symbol.for('auto_daangn_manual_input_events_v1');
  try{document[key]?.stop?.()}catch(_){}
  return true;
}"""


def sanitize_manual_input_events(raw):
    """Strictly whitelist the same event schema as Chrome's automated witness."""
    source = raw if type(raw) is dict else {}
    out = sanitize_input_events(source)
    out["observed_input"] = source.get("observed_input") is True
    return out


class ManualRegionInputEventWitness:
    async def arm(self, page):
        try:
            return await page.evaluate(_JS_ARM) is True
        except Exception:
            return False

    async def sample(self, page):
        try:
            raw = await page.evaluate(_JS_READ)
        except Exception:
            raw = None
        return sanitize_manual_input_events(raw)

    async def stop(self, page):
        try:
            await page.evaluate(_JS_STOP)
        except Exception:
            pass
