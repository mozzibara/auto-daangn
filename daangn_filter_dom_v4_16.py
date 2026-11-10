# -*- coding: utf-8 -*-
"""v4.16: passive, bounded DOM anatomy of surviving public-search filter controls.

No synthetic requests, mutation, click, raw HTML, raw CSS, labels, URLs, seller
data or browser state are collected. Report only allowlisted attributes and
spatial/parent/ARIA structure to distinguish a filter action from a status chip.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import secrets
from datetime import datetime,timezone

import daangn_filter_recheck_v4_15 as v15
import daangn_full_route_v4_14 as v14

# All names or attributes from page DOM are converted to finite classifications.
DOM_JS=r"""() => {
  const tags=['BUTTON','A','DIV','SPAN','NAV','HEADER','MAIN','SECTION','ASIDE','FOOTER','FORM','LABEL','UL','LI','INPUT','SVG'];
  const hintWords=['filter','search','toolbar','button','chip','badge','tag','pill','icon',
                   'clear','reset','input','panel','dialog','header','navigation','list','result','sort'];
  const words={
    reset:/(?:초기화|해제|삭제|제거|지우기|리셋|reset|clear|remove)/i,
    edit:/(?:편집|변경|수정|설정|열기|edit|change|configure)/i,
    apply:/(?:적용|apply)/i,
    open:/(?:열기|펼치기|선택|open)/i,
    count:/(?:[0-9]+\s*(?:개|건|선택)|\([0-9]+\))/,
    price:/(?:가격|price)/i,
    category:/(?:카테고리|category)/i,
    availability:/(?:거래 가능|판매 중|판매중|available|on sale)/i,
    exact:/(?:^필터$|^filter$|^filters$)/i
  };
  const clean=(s)=>(s||'').replace(/\s+/g,' ').trim().slice(0,85);
  const accessible=(el)=>{
    const a=clean(el.getAttribute('aria-label'));
    if(a)return {value:a,source:'ARIA_LABEL'};
    const t=clean(el.getAttribute('title'));
    if(t)return {value:t,source:'TITLE'};
    const c=clean(el.innerText||el.textContent);
    return {value:c,source:c?'TEXT':'NONE'};
  };
  const visible=(el)=>{
    const b=el.getBoundingClientRect(),s=getComputedStyle(el);
    return b.width>0&&b.height>0&&el.getClientRects().length>0 &&
           s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0';
  };
  const cap=(n,max=50)=>Math.min(max,n);
  const zone=(x,limit)=>x<limit/3?'FIRST_THIRD':x<limit*2/3?'MIDDLE_THIRD':'LAST_THIRD';
  const links=[...document.querySelectorAll('a[href*="/kr/buy-sell/"]')].filter(visible);
  const cardBottom=links.length?Math.max(...links.map(x=>x.getBoundingClientRect().bottom+scrollY)):null;
  const elements=[...document.querySelectorAll('button,a[href],[role="button"]')];
  const selected=elements.map((el,absoluteIndex)=>({el,absoluteIndex,access:accessible(el)}))
      .filter(x=>/(?:필터|filter)/i.test(x.access.value)&&x.access.value.length<=80);
  function ancestorStructure(el){
    const rows=[];let parent=el.parentElement;
    for(let depth=0;depth<6&&parent;depth++,parent=parent.parentElement){
      const classes=[...parent.classList].map(x=>String(x).toLowerCase());
      const hints=hintWords.filter(w=>classes.some(x=>x.includes(w))).slice(0,5);
      rows.push({tag:tags.includes(parent.tagName)?parent.tagName:'OTHER',
        role:['navigation','main','search','toolbar','dialog','group','list','listitem','region'].includes(parent.getAttribute('role'))?parent.getAttribute('role'):'OTHER_OR_NONE',
        hints,child_count:cap(parent.children.length),depth});
    }
    return rows;
  }
  function linkKind(el){
    if(el.tagName!=='A')return 'NOT_A_LINK';
    const href=el.getAttribute('href');
    if(!href)return 'NO_HREF';
    try{
      const u=new URL(href,location.href),here=new URL(location.href);
      if(u.origin!==here.origin)return 'EXTERNAL';
      if(u.pathname===here.pathname){
        const keys=['q','in','price','category_id','only_on_sale'];
        return keys.every(k=>u.searchParams.get(k)===here.searchParams.get(k))?'SAME_FILTER_SEARCH':'SAME_PATH_DIFFERENT_FILTER';
      }
      return 'FIRST_PARTY_OTHER_PATH';
    }catch{return 'INVALID_HREF';}
  }
  const candidates=selected.slice(0,8).map(({el,absoluteIndex,access},ordinal)=>{
    const b=el.getBoundingClientRect(),s=getComputedStyle(el);
    const tag=tags.includes(el.tagName)?el.tagName:'OTHER';
    const role=el.getAttribute('role');
    const flags=Object.fromEntries(Object.entries(words).map(([k,re])=>[k,re.test(access.value)]));
    const hasPopup=el.getAttribute('aria-haspopup')||'';
    const expanded=el.getAttribute('aria-expanded');
    const pressed=el.getAttribute('aria-pressed');
    const currentY=b.top+scrollY;
    const main=el.closest('main,[role="main"]'),header=el.closest('header,nav,[role="navigation"]');
    const dialog=el.closest('[role="dialog"],[aria-modal="true"]');
    const footer=el.closest('footer');
    return {
      ordinal,tag,role:['button','link','tab','menuitem','switch','checkbox'].includes(role)?role:'NONE_OR_OTHER',
      access_name_source:access.source,access_name_length:access.value.length,
      semantic_flags:flags,
      aria:{haspopup:['menu','dialog','listbox','grid','tree','true'].includes(hasPopup)?hasPopup:'NONE_OR_OTHER',
        expanded:expanded==='true'?'TRUE':expanded==='false'?'FALSE':'UNSET_OR_OTHER',
        pressed:pressed==='true'?'TRUE':pressed==='false'?'FALSE':'UNSET_OR_OTHER',
        controls_present:el.hasAttribute('aria-controls'),
        describedby_present:el.hasAttribute('aria-describedby'),
        label_present:el.hasAttribute('aria-label')},
      action:{type:tag==='BUTTON'&&['button','submit','reset'].includes(el.getAttribute('type'))?el.getAttribute('type'):'OTHER_OR_UNSET',
        link_kind:linkKind(el),
        disabled:!!el.disabled||el.getAttribute('aria-disabled')==='true',
        has_inline_onclick:el.hasAttribute('onclick'),
        pointer_events:s.pointerEvents==='none'?'NONE':'ENABLED_OR_OTHER'},
      geometry:{visible:visible(el),viewport_horizontal:zone(b.left+b.width/2,innerWidth),
        viewport_vertical:zone(b.top+b.height/2,innerHeight),
        width_band:b.width<40?'TINY':b.width<140?'SMALL':b.width<350?'MEDIUM':'LARGE',
        inside_header_nav:!!header,inside_main:!!main,inside_footer:!!footer,inside_dialog:!!dialog,
        relative_to_last_card:cardBottom===null?'NO_CARD':
          currentY<cardBottom-100?'ABOVE_LAST_RESULT':
          currentY<=cardBottom+300?'AT_LAST_RESULT':'AFTER_LAST_RESULT'},
      ancestry:ancestorStructure(el),
      children:{svg_count:cap(el.querySelectorAll('svg').length),
        span_count:cap(el.querySelectorAll('span').length),
        input_count:cap(el.querySelectorAll('input').length),
        button_count:cap(el.querySelectorAll('button').length)},
      semantic_dom_position:cap(absoluteIndex,500)
    };
  });
  return {status:'OBSERVED',candidate_count:selected.length,
    candidates_truncated:selected.length>8,candidates,
    page_result_anchor_count:links.length};
}""".strip()

TAGS={'BUTTON','A','DIV','SPAN','NAV','HEADER','MAIN','SECTION','ASIDE','FOOTER','FORM','LABEL','UL','LI','INPUT','SVG','OTHER'}
ROLES={'button','link','tab','menuitem','switch','checkbox','NONE_OR_OTHER'}
ANCESTOR_ROLES={'navigation','main','search','toolbar','dialog','group','list','listitem','region','OTHER_OR_NONE'}
HINTS={'filter','search','toolbar','button','chip','badge','tag','pill','icon','clear','reset','input','panel','dialog','header','navigation','list','result','sort'}
SOURCES={'ARIA_LABEL','TITLE','TEXT','NONE'}
LINKS={'NOT_A_LINK','NO_HREF','EXTERNAL','SAME_FILTER_SEARCH','SAME_PATH_DIFFERENT_FILTER','FIRST_PARTY_OTHER_PATH','INVALID_HREF'}
THIRDS={'FIRST_THIRD','MIDDLE_THIRD','LAST_THIRD'}
FLAGS={'reset','edit','apply','open','count','price','category','availability','exact'}

def enum(value, allowed, fallback):
    return value if isinstance(value,str) and value in allowed else fallback

def bounded(n, limit=1000):
    return n if type(n) is int and 0<=n<=limit else None

def boolean(v):
    return v is True

def sanitize_probe(raw):
    """Exact-schema allowlist. Source text, hrefs, identifiers and class names are dropped."""
    if not isinstance(raw,dict) or raw.get('status')!='OBSERVED':
        return {'status':'UNVERIFIED'}
    candidates=[]
    items=raw.get('candidates')
    if not isinstance(items,list):
        return {'status':'UNVERIFIED'}
    for x in items[:8]:
        if not isinstance(x,dict):
            continue
        flags=x.get('semantic_flags') if isinstance(x.get('semantic_flags'),dict) else {}
        a=x.get('aria') if isinstance(x.get('aria'),dict) else {}
        act=x.get('action') if isinstance(x.get('action'),dict) else {}
        geo=x.get('geometry') if isinstance(x.get('geometry'),dict) else {}
        children=x.get('children') if isinstance(x.get('children'),dict) else {}
        ancestors=[]
        parents=x.get('ancestry') if isinstance(x.get('ancestry'),list) else []
        for p in parents[:6]:
            if not isinstance(p,dict):
                continue
            ancestors.append({
                'tag':enum(p.get('tag'),TAGS,'OTHER'),
                'role':enum(p.get('role'),ANCESTOR_ROLES,'OTHER_OR_NONE'),
                'hints':[v for v in (p.get('hints') if isinstance(p.get('hints'),list) else [])[:5] if isinstance(v,str) and v in HINTS],
                'depth':bounded(p.get('depth'),5),
                'child_count':bounded(p.get('child_count'),50)})
        candidate={
            'ordinal':bounded(x.get('ordinal'),7),
            'tag':enum(x.get('tag'),TAGS,'OTHER'),
            'role':enum(x.get('role'),ROLES,'NONE_OR_OTHER'),
            'access_name_source':enum(x.get('access_name_source'),SOURCES,'NONE'),
            'access_name_length':bounded(x.get('access_name_length'),80),
            'semantic_flags':{k:boolean(flags.get(k)) for k in FLAGS},
            'aria':{
              'haspopup':enum(a.get('haspopup'),{'menu','dialog','listbox','grid','tree','true','NONE_OR_OTHER'},'NONE_OR_OTHER'),
              'expanded':enum(a.get('expanded'),{'TRUE','FALSE','UNSET_OR_OTHER'},'UNSET_OR_OTHER'),
              'pressed':enum(a.get('pressed'),{'TRUE','FALSE','UNSET_OR_OTHER'},'UNSET_OR_OTHER'),
              'controls_present':boolean(a.get('controls_present')),
              'describedby_present':boolean(a.get('describedby_present')),
              'label_present':boolean(a.get('label_present'))},
            'action':{
              'type':enum(act.get('type'),{'button','submit','reset','OTHER_OR_UNSET'},'OTHER_OR_UNSET'),
              'link_kind':enum(act.get('link_kind'),LINKS,'INVALID_HREF'),
              'disabled':boolean(act.get('disabled')),
              'has_inline_onclick':boolean(act.get('has_inline_onclick')),
              'pointer_events':enum(act.get('pointer_events'),{'NONE','ENABLED_OR_OTHER'},'NONE')},
            'geometry':{
              'visible':boolean(geo.get('visible')),
              'viewport_horizontal':enum(geo.get('viewport_horizontal'),THIRDS,'MIDDLE_THIRD'),
              'viewport_vertical':enum(geo.get('viewport_vertical'),THIRDS,'MIDDLE_THIRD'),
              'width_band':enum(geo.get('width_band'),{'TINY','SMALL','MEDIUM','LARGE'},'MEDIUM'),
              'inside_header_nav':boolean(geo.get('inside_header_nav')),
              'inside_main':boolean(geo.get('inside_main')),
              'inside_footer':boolean(geo.get('inside_footer')),
              'inside_dialog':boolean(geo.get('inside_dialog')),
              'relative_to_last_card':enum(geo.get('relative_to_last_card'),
                    {'NO_CARD','ABOVE_LAST_RESULT','AT_LAST_RESULT','AFTER_LAST_RESULT'},'NO_CARD')},
            'ancestry':ancestors,
            'children':{k:bounded(children.get(k),50) for k in ('svg_count','span_count','input_count','button_count')},
            'semantic_dom_position':bounded(x.get('semantic_dom_position'),500)}
        candidate['structural_fingerprint']=hashlib.sha256(json.dumps(
            {k:v for k,v in candidate.items() if k not in ('ordinal','semantic_dom_position')},
            sort_keys=True,ensure_ascii=True).encode('utf-8')).hexdigest()[:16]
        candidate['role_hypothesis']=role_hypothesis(candidate)
        candidates.append(candidate)
    return {'status':'OBSERVED','candidate_count':bounded(raw.get('candidate_count'),100),
       'candidates_truncated':boolean(raw.get('candidates_truncated')),
       'page_result_anchor_count':bounded(raw.get('page_result_anchor_count'),650),
       'candidates':candidates}


def role_hypothesis(candidate):
    """Descriptive affordance, not proof of functional behavior."""
    f=candidate.get('semantic_flags') or {}
    a=candidate.get('aria') or {}
    action=candidate.get('action') or {}
    if action.get('link_kind')=='EXTERNAL':
        return 'EXTERNAL_NAVIGATION_NOT_A_FILTER_EDITOR'
    if f.get('reset') and (candidate.get('tag')=='BUTTON' or action.get('type')=='reset'):
        return 'FILTER_RESET_AFFORDANCE_UNCONFIRMED'
    if (a.get('haspopup') in ('menu','dialog','listbox','true') and
            (f.get('edit') or f.get('open') or f.get('exact'))):
        return 'FILTER_PANEL_TRIGGER_AFFORDANCE_UNCONFIRMED'
    if action.get('link_kind') in ('SAME_PATH_DIFFERENT_FILTER','FIRST_PARTY_OTHER_PATH'):
        return 'NAVIGATION_OR_FILTER_LINK_UNCONFIRMED'
    if f.get('count') and not f.get('edit') and not a.get('controls_present'):
        return 'FILTER_STATUS_OR_COUNT_INDICATOR_UNCONFIRMED'
    return 'FILTER_RELATED_CONTROL_FUNCTION_UNKNOWN'


async def inspect(page):
    """Read-only DOM inspection; external page data is allowlisted before export."""
    try:
        return sanitize_probe(await asyncio.wait_for(page.evaluate(DOM_JS),timeout=5))
    except Exception as exc:
        return {'status':'ERROR_'+type(exc).__name__}


def evaluate(rows):
    base=v15.evaluate(rows)
    contexts=[]
    for row in rows:
        d=row.get('ui_persistence') or {}
        observed={
            'baseline':row.get('baseline_dom_v16') or {},
            'spa':d.get('spa_dom_v16') or {},
            'reload':d.get('reload_dom_v16') or {}
        }
        signatures={}
        for phase,probe in observed.items():
            signatures[phase]={
                'status':probe.get('status'),
                'candidate_count':probe.get('candidate_count'),
                'visible_filter_related_candidates':sum(x.get('geometry',{}).get('visible') is True
                    for x in probe.get('candidates',[])),
                'role_hypotheses':[x.get('role_hypothesis') for x in probe.get('candidates',[])],
                'fingerprints':[x.get('structural_fingerprint') for x in probe.get('candidates',[])]}
        contexts.append({'context':row.get('context'),'phases':signatures})
    healthy=bool(base.get('capture_complete') and len(rows)==3 and all(
        (r.get('baseline_dom_v16') or {}).get('status')=='OBSERVED' and
        ((r.get('ui_persistence') or {}).get('spa_dom_v16') or {}).get('status')=='OBSERVED' and
        ((r.get('ui_persistence') or {}).get('reload_dom_v16') or {}).get('status')=='OBSERVED' and
        all(not probe.get('candidates_truncated') for probe in (
            r['baseline_dom_v16'],r['ui_persistence']['spa_dom_v16'],r['ui_persistence']['reload_dom_v16']))
        for r in rows))
    post=[((r.get('ui_persistence') or {}).get('spa_dom_v16') or {}).get('candidates',[]) for r in rows]
    stable=healthy and all(len(x)==1 for x in post) and len({
        x[0].get('structural_fingerprint') for x in post})==1
    role=post[0][0].get('role_hypothesis') if stable else 'NOT_INFERRED'
    confirmed=stable and role not in (
        'FILTER_RELATED_CONTROL_FUNCTION_UNKNOWN',
        'FILTER_STATUS_OR_COUNT_INDICATOR_UNCONFIRMED','NAVIGATION_OR_FILTER_LINK_UNCONFIRMED')
    if any(x.get('access_blocked') for x in rows):
        status='STOP_ACCESS_RESTRICTION'
    elif not healthy:
        status='INCONCLUSIVE_DOM_STRUCTURE_CAPTURE'
    elif stable:
        status='REPRODUCED_SAME_SURVIVING_CONTROL_STRUCTURE'
    else:
        status='DOM_STRUCTURE_OBSERVED_WITH_DIFFERENCES'
    return {'status':status,'capture_complete':healthy,
      'contexts_expected':3,'contexts_captured':len(rows),
      'route_counts':base.get('route_counts'),
      'baseline_spa_reload':contexts,
      'same_surviving_control_structure_in_all_contexts':stable,
      'role_hypothesis':role,'role_proven_by_activation':False,
      'role_affordance_supported':bool(confirmed),
      'ui_filter_selection_verified':bool(len(base.get('stable_selection_verified') or [])==3 and
            all(base['stable_selection_verified'])),
      'strict_listing_approved_count':0,
      'no_control_clicks':True,
      'backend_filter_enforcement_proven':False,
      'full_inventory_proven':False}


def report(doc):
    e=doc['evaluation']
    lines=['# v4.16: surviving search filter control DOM anatomy','',
       f"- Verdict: **{e['status']}**; captured: {e['capture_complete']}",
       f"- Same SPA control structure in three regions: {e['same_surviving_control_structure_in_all_contexts']}",
       f"- Functional hypothesis: {e['role_hypothesis']} (NOT activation-proven)",
       f"- Selected filter verified: {e['ui_filter_selection_verified']}; strict listing approvals: 0",
       '', '| Context | Baseline filter candidates | SPA candidates | Reload candidates | SPA structural hypotheses |',
       '|---|---:|---:|---:|---|']
    for x in doc['contexts']:
        d=x.get('ui_persistence') or {}
        b=x.get('baseline_dom_v16') or {}
        spa=d.get('spa_dom_v16') or {}
        reload=d.get('reload_dom_v16') or {}
        lines.append('| '+' | '.join(map(str,[x.get('context'),
            b.get('candidate_count'),spa.get('candidate_count'),
            reload.get('candidate_count'),
            ', '.join(c.get('role_hypothesis','?') for c in spa.get('candidates',[]))]))+' |')
    lines+=['','## Evidence scope',
      '- Each candidate includes allowlisted HTML tag and ARIA attributes, semantic-word flags, geometry, ancestor tags and class-hint categories, child counts, same-run structural fingerprint.',
      '- No raw DOM markup, raw class/attribute values, raw labels, URLs, seller data or cookies are exported.',
      '- No unknown control is clicked; visual structure cannot establish the JavaScript handler or functional side-effect.',
      '- Baseline and the exact UI-generated filtered URL are both tested; absence of a filter button is not filter-reset proof.',
      '- v4.15 strict selection and server metadata gates remain unchanged.','']
    return '\n'.join(lines)


async def run(options):
    options.filter_recheck_v15=True
    options.filter_dom_v16=True
    salt=secrets.token_bytes(32)
    rows=[]
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=not options.headed)
            try:
                for name,region in [('cheonan_a','cheonan'),
                                    ('asan_control','asan'),('cheonan_b','cheonan')]:
                    row=await v14.capture(browser,name,region,options,salt)
                    rows.append(row)
                    print('v4.16',name,row.get('status'),row.get('route_count'),
                        'spacandidates',((row.get('ui_persistence') or {}).get('spa_dom_v16') or {}).get('candidate_count'))
                    if row.get('status','').startswith('STOP_') or row.get('access_blocked'):
                        break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as exc:
        rows.append({'context':'browser','status':'STOP_'+type(exc).__name__,
                     'access_blocked':False})
    verdict=evaluate(rows)
    doc={'version':'4.16','utc_time':datetime.now(timezone.utc).isoformat(timespec='seconds'),
       'scope':{'target':'cheonan','control':'asan','keyword':'HDD','max_price_krw':50000,
                'public_filter_controls_only':True,'read_only':True},
       'evaluation':verdict,
       'contexts':[v14.sanitized_context(r)|{
          'baseline_dom_v16':r.get('baseline_dom_v16'),
          'ui_persistence':r.get('ui_persistence')} for r in rows],
       'strict_listing_accept':{'blocked':True,'approved_listings':[]}}
    options.output_dir.mkdir(parents=True,exist_ok=True)
    (options.output_dir/'v416_dom_anatomy_results.json').write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (options.output_dir/'v416_dom_anatomy_report.md').write_text(report(doc),encoding='utf-8')
    (options.output_dir/'v416_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if verdict['capture_complete'] else 2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=Path('v416_output'))
    parser.add_argument('--headed',action='store_true')
    parser.add_argument('--timeout',type=int,default=25)
    parser.add_argument('--settle-ms',type=int,default=1600)
    options=parser.parse_args()
    options.output_dir=options.output_dir.resolve()
    options.timeout=max(15,min(45,options.timeout))
    options.settle_ms=max(800,min(3500,options.settle_ms))
    return asyncio.run(run(options))


if __name__=='__main__':
    raise SystemExit(main())
