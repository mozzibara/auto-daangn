# -*- coding: utf-8 -*-
"""v4.22 bounded DOM/rendering diagnosis for unobserved primary sale-state UI.

Read-only public detail inspection in the *already approved v4.20 route and
robots-gated page flow*. Four same-document observations (settled, delayed,
scrolled and narrow viewport) inspect safe structure without preserving any
text, names, links, IDs, class strings, HTML, JSON-LD, screenshot or cookies.
No findings here can authorize listing exports or change v4.21 evidence.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets

import daangn_detail_crosscheck_v4_20 as detail
import daangn_full_route_v4_14 as full
import daangn_sale_sources_v4_21 as sources
import daangn_v4_1_core as core
import daangn_render_gap_v4_12 as render

PHASES=('initial','delayed','scrolled','narrow')
VISIBILITY={'VISIBLE','DISPLAY_NONE','VISIBILITY_HIDDEN','OPACITY_ZERO',
            'ZERO_RECT','ANCESTOR_HIDDEN','ARIA_HIDDEN','INERT','OFFSCREEN'}
SCOPES={'PRIMARY','RECOMMENDATION','LINKED_OTHER_LISTING','NAVIGATION','INTERACTION','OUTSIDE_PRIMARY'}
TAGS={'SPAN','DIV','P','B','STRONG','EM','SMALL','BUTTON','A','LABEL','H1','H2',
      'H3','LI','SECTION','ARTICLE','TIME','INS','DEL','OTHER'}
ROLES={'status','button','link','text','alert','none','other'}
HINTS={'NONE','STATUS','SALE','RESERVATION','OTHER'}
MATCH_KINDS={'DIRECT_TEXT','ARIA_LABEL'}
STATES={'AVAILABLE','SOLD','RESERVED'}
MAX_ELEMENTS=3500
MAX_CANDIDATES=80
MAX_EXPORTED_CANDIDATES=6
MAX_PHASE_TIME_MS=1500

DOM_JS=r"""() => {
  const limit=3500, candidateLimit=80;
  const tokens=new Map([['판매중','AVAILABLE'],['판매 중','AVAILABLE'],
    ['판매완료','SOLD'],['판매 완료','SOLD'],['거래완료','SOLD'],['거래 완료','SOLD'],
    ['예약중','RESERVED'],['예약 중','RESERVED']]);
  const canonical=s=>String(s||'').replace(/\s+/g,' ').trim().slice(0,120);
  const identify=s=>tokens.get(canonical(s))||null;
  const primary=document.querySelector('main article')||document.querySelector('main');
  const scopeOf=e=>{
    // The primary article often *contains* recommended listing cards.
    // Their status badges are evidence for OTHER listings, not the current
    // detail. v4.21 already excludes any nested linked listing card.
    if(e.closest('a[href*="/kr/buy-sell/"]'))return 'LINKED_OTHER_LISTING';
    if(e.closest('[data-testid*="recommend"],[class*="recommend"],'+
       '[aria-label*="추천"],[class*="related"],[data-testid*="related"]'))
       return 'RECOMMENDATION';
    if(e.closest('header,footer,nav,aside'))return 'NAVIGATION';
    if(e.closest('form,[class*="comment"],[data-testid*="comment"],'+
       '[aria-label*="채팅"],[data-testid*="chat"]'))return 'INTERACTION';
    return primary&&primary.contains(e)?'PRIMARY':'OUTSIDE_PRIMARY';
  };
  const visOf=e=>{
    if(e.closest('[aria-hidden="true"]'))return 'ARIA_HIDDEN';
    if(e.closest('[inert]'))return 'INERT';
    let a=e;let hops=0;
    while(a&&hops++<24){
      const st=getComputedStyle(a);
      if(st.display==='none')return a===e?'DISPLAY_NONE':'ANCESTOR_HIDDEN';
      if(st.visibility==='hidden'||st.visibility==='collapse')
         return a===e?'VISIBILITY_HIDDEN':'ANCESTOR_HIDDEN';
      if(st.opacity==='0')return a===e?'OPACITY_ZERO':'ANCESTOR_HIDDEN';
      a=a.parentElement;
    }
    const bb=e.getBoundingClientRect();
    if(!e.getClientRects().length||bb.height===0||bb.width===0)return 'ZERO_RECT';
    if(bb.bottom<=0||bb.top>=innerHeight||bb.right<=0||bb.left>=innerWidth)
      return 'OFFSCREEN';
    return 'VISIBLE';
  };
  const tagOf=e=>['SPAN','DIV','P','B','STRONG','EM','SMALL','BUTTON','A',
    'LABEL','H1','H2','H3','LI','SECTION','ARTICLE','TIME','INS','DEL']
    .includes(e.tagName)?e.tagName:'OTHER';
  const roleOf=e=>['status','button','link','text','alert'].includes(
      e.getAttribute('role'))?e.getAttribute('role'):
      e.getAttribute('role')?'other':'none';
  const hintOf=e=>{
    const v=((e.getAttribute('data-testid')||'')+' '+
             (typeof e.className==='string'?e.className:'')).toLowerCase();
    if(v.includes('status'))return 'STATUS';
    if(v.includes('sale'))return 'SALE';
    if(v.includes('reserv'))return 'RESERVATION';
    return v.trim()?'OTHER':'NONE';
  };
  const path=e=>{
    const tags=[];let node=e;
    for(let i=0;node&&i<5;i++,node=node.parentElement)tags.push(tagOf(node));
    return tags;
  };
  const result={
    scan_complete:false,scan_limit:limit,scanned_elements:0,
    candidate_limit:candidateLimit,raw_candidate_count:0,
    primary_region:'NONE',primary_heading_visible:false,
    dom_ready_state:['loading','interactive','complete'].includes(document.readyState)?
      document.readyState:'other',
    viewport:{width:Math.max(0,Math.min(4000,innerWidth)),
              height:Math.max(0,Math.min(4000,innerHeight))},
    scope_counts:{PRIMARY:0,RECOMMENDATION:0,LINKED_OTHER_LISTING:0,
                  NAVIGATION:0,INTERACTION:0,OUTSIDE_PRIMARY:0},
    visibility_counts:{VISIBLE:0,DISPLAY_NONE:0,VISIBILITY_HIDDEN:0,
       OPACITY_ZERO:0,ZERO_RECT:0,ANCESTOR_HIDDEN:0,
       ARIA_HIDDEN:0,INERT:0,OFFSCREEN:0},
    primary_state_counts:{AVAILABLE:0,SOLD:0,RESERVED:0},
    match_counts:{DIRECT_TEXT:0,ARIA_LABEL:0},
    primary_old_selector_missed:0,
    primary_visible_exact_tokens:0,
    primary_nonvisible_exact_tokens:0,
    semantic_status_elements:{primary_visible:0,primary_hidden:0,outside:0},
    candidates:[]
  };
  if(primary){
    result.primary_region=primary.tagName==='ARTICLE'?'MAIN_ARTICLE':'MAIN_ONLY';
    const headings=[...primary.querySelectorAll('h1')].filter(el=>visOf(el)==='VISIBLE');
    result.primary_heading_visible=headings.length===1;
  }
  const elements=document.querySelectorAll('body *');
  result.scanned_elements=Math.min(elements.length,limit);
  result.scan_complete=elements.length<=limit;
  const old='[role="status"],[data-testid*="status"],[data-testid*="sale-state"],'+
       '[class*="status"],[class*="Status"],[aria-label],span,p,b,strong,em,small,div';
  for(const el of [...elements].slice(0,limit)){
    if(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','SVG'].includes(el.tagName))continue;
    if(el.closest('script,style,noscript,template,svg'))continue;
    const direct=[...el.childNodes].filter(n=>n.nodeType===3)
       .map(n=>n.textContent||'').join(' ');
    const textVal=identify(direct);
    const ariaVal=identify(el.getAttribute('aria-label'));
    const hinted=/status|sale-state|reservation/i.test(
       (el.getAttribute('data-testid')||'')+' '+
       (typeof el.className==='string'?el.className:''));
    const semantic=(el.getAttribute('role')==='status'||hinted)&&
       !el.closest('svg,script,style');
    if(semantic){
      const sc=scopeOf(el),vs=visOf(el);
      if(sc==='PRIMARY'&&vs==='VISIBLE')
        result.semantic_status_elements.primary_visible++;
      else if(sc==='PRIMARY')result.semantic_status_elements.primary_hidden++;
      else result.semantic_status_elements.outside++;
    }
    if(!textVal&&!ariaVal)continue;
    const match=textVal?'DIRECT_TEXT':'ARIA_LABEL';
    const state=textVal||ariaVal;
    const scope=scopeOf(el),visibility=visOf(el);
    result.raw_candidate_count++;
    result.scope_counts[scope]++;
    result.visibility_counts[visibility]++;
    result.match_counts[match]++;
    if(scope==='PRIMARY'){
      result.primary_state_counts[state]++;
      if(visibility==='VISIBLE')result.primary_visible_exact_tokens++;
      else result.primary_nonvisible_exact_tokens++;
      if(!el.matches(old))result.primary_old_selector_missed++;
    }
    if(result.candidates.length<8){
      result.candidates.push({
        state,scope,visibility,match,tag:tagOf(el),
        role:roleOf(el),hint:hintOf(el),
        ancestor_tags:path(el),
        old_selector_covers:el.matches(old),
        has_aria_label:el.hasAttribute('aria-label')
      });
    }
    if(result.raw_candidate_count>=candidateLimit){
      result.scan_complete=false;
      break;
    }
  }
  return result;
}""".strip()


def sanitize(raw):
    """Reject all unknown property names, arbitrary text, URLs or CSS classes."""
    if not isinstance(raw,dict):return {'status':'INVALID'}
    def count(v,maximum=3500):
        return v if type(v) is int and 0<=v<=maximum else None
    def code(v,allowed,default):
        return v if isinstance(v,str) and v in allowed else default
    def counts(v,keys):
        d=v if isinstance(v,dict) else {}
        return {k:count(d.get(k)) for k in sorted(keys)}
    safe={
        'status':'OBSERVED',
        'scan_complete':raw.get('scan_complete') is True,
        'scanned_elements':count(raw.get('scanned_elements')),
        'raw_candidate_count':count(raw.get('raw_candidate_count')),
        'primary_region':code(raw.get('primary_region'),
                          {'NONE','MAIN_ONLY','MAIN_ARTICLE'},'NONE'),
        'primary_heading_visible':raw.get('primary_heading_visible') is True,
        'dom_ready_state':code(raw.get('dom_ready_state'),
                          {'loading','interactive','complete','other'},'other'),
        'viewport':{'width':count((raw.get('viewport') or {}).get('width'),4000)
                      if isinstance(raw.get('viewport'),dict) else None,
                    'height':count((raw.get('viewport') or {}).get('height'),4000)
                      if isinstance(raw.get('viewport'),dict) else None},
        'scope_counts':counts(raw.get('scope_counts'),SCOPES),
        'visibility_counts':counts(raw.get('visibility_counts'),VISIBILITY),
        'primary_state_counts':counts(raw.get('primary_state_counts'),STATES),
        'match_counts':counts(raw.get('match_counts'),MATCH_KINDS),
        'primary_old_selector_missed':count(raw.get('primary_old_selector_missed')),
        'primary_visible_exact_tokens':count(raw.get('primary_visible_exact_tokens')),
        'primary_nonvisible_exact_tokens':count(raw.get('primary_nonvisible_exact_tokens')),
        'semantic_status_elements':counts(raw.get('semantic_status_elements'),
                                {'primary_visible','primary_hidden','outside'}),
        'candidates':[]}
    items=raw.get('candidates') if isinstance(raw.get('candidates'),list) else []
    for row in items[:MAX_EXPORTED_CANDIDATES]:
        if not isinstance(row,dict):continue
        tags=row.get('ancestor_tags') if isinstance(row.get('ancestor_tags'),list) else []
        safe['candidates'].append({
            'state':code(row.get('state'),STATES,'UNKNOWN'),
            'scope':code(row.get('scope'),SCOPES,'OUTSIDE_PRIMARY'),
            'visibility':code(row.get('visibility'),VISIBILITY,'ZERO_RECT'),
            'match':code(row.get('match'),MATCH_KINDS,'DIRECT_TEXT'),
            'tag':code(row.get('tag'),TAGS,'OTHER'),
            'role':code(row.get('role'),ROLES,'other'),
            'hint':code(row.get('hint'),HINTS,'NONE'),
            'ancestor_tags':[code(x,TAGS,'OTHER') for x in tags[:5]],
            'old_selector_covers':row.get('old_selector_covers') is True,
            'has_aria_label':row.get('has_aria_label') is True})
    return safe


async def snapshot(page):
    try:
        result=await asyncio.wait_for(page.evaluate(DOM_JS),timeout=7)
        return sanitize(result)
    except Exception as ex:
        return {'status':'ERROR_'+type(ex).__name__}


async def examine(page,first_source,settle_ms=1500):
    """Four static same-document states, no clicks or additional navigation."""
    phases={}
    original=page.viewport_size
    url=page.url  # Used in RAM for identity continuity; never persisted.
    async def record(name,old=None):
        observed=await snapshot(page)
        old=old if isinstance(old,dict) else await sources.probe_sources(page)
        return {'structure':observed,
                'v421_ui_state':(old.get('ui') or {}).get('state','NOT_OBSERVABLE'),
                'v421_jsonld_state':(old.get('jsonld') or {}).get('state','NOT_OBSERVABLE'),
                'same_document_url':page.url==url}
    try:
        phases['initial']=await record('initial',first_source)
        await page.wait_for_timeout(max(300,min(1000,settle_ms//2)))
        phases['delayed']=await record('delayed')
        await page.evaluate("""() => {
          const main=document.querySelector('main article')||document.querySelector('main');
          const heading=main?.querySelector('h1');
          if(heading)heading.scrollIntoView({block:'center',behavior:'auto'});
        }""")
        await page.wait_for_timeout(150)
        phases['scrolled']=await record('scrolled')
        await page.set_viewport_size({'width':390,'height':844})
        await page.wait_for_timeout(250)
        phases['narrow']=await record('narrow')
    except Exception as ex:
        return {'status':'ERROR_'+type(ex).__name__,'phases':phases}
    finally:
        if original:
            try:await page.set_viewport_size(original)
            except Exception:pass
    outcome=classify(phases)
    valid=outcome not in ('INCOMPLETE_PHASES','PAGE_URL_CHANGED','INCONCLUSIVE_DOM_SCAN')
    return {'status':'CAPTURED' if valid else 'INCONCLUSIVE',
            'outcome':outcome,'phases':phases,
            'actual_sale_ui_proven':False,
            'strict_listing_approved_count':0}


def classify(phases):
    """Bounded diagnosis only; do not infer a site-wide rendering policy."""
    if set(phases)!=set(PHASES):return 'INCOMPLETE_PHASES'
    if any(not (x.get('same_document_url') is True) for x in phases.values()):
        return 'PAGE_URL_CHANGED'
    structures=[phases[k].get('structure') or {} for k in PHASES]
    if any(x.get('status')!='OBSERVED' or
           x.get('scan_complete') is not True or
           not x.get('primary_heading_visible') for x in structures):
        return 'INCONCLUSIVE_DOM_SCAN'
    def n(obj,key,field):
        return (obj.get(key) or {}).get(field,0) or 0
    def visible_primary(o):
        return (o.get('primary_visible_exact_tokens') or 0)>0
    # Explicit UI source is only v4.21's own safe proof; the structural
    # diagnostic sees potential candidates but cannot relax that proof.
    if any(phases[k].get('v421_ui_state') in ('AVAILABLE','SOLD','RESERVED') for k in PHASES):
        first=next(k for k in PHASES if phases[k].get('v421_ui_state') in
                   ('AVAILABLE','SOLD','RESERVED'))
        return {'initial':'VISIBLE_STATUS_REPRODUCED',
                'delayed':'STATUS_EMERGED_AFTER_SETTLE',
                'scrolled':'STATUS_EMERGED_AFTER_SCROLL',
                'narrow':'STATUS_EMERGED_NARROW_VIEWPORT'}[first]
    if any(visible_primary(x) for x in structures):
        if any(n(x,'primary_old_selector_missed')>0 for x in structures):
            return 'PRIMARY_VISIBLE_STATUS_OLD_SELECTOR_GAP'
        return 'PRIMARY_VISIBLE_STATUS_UNRESOLVED_BY_V421'
    if any(n(x,'scope_counts','PRIMARY')>0 for x in structures):
        return 'PRIMARY_STATUS_TOKEN_HIDDEN_OR_OFFSCREEN'
    if any(n(x,'semantic_status_elements','primary_visible')>0 for x in structures):
        return 'PRIMARY_SEMANTIC_STATUS_ELEMENT_WITHOUT_EXACT_SALE_TOKEN'
    if any(n(x,'semantic_status_elements','primary_hidden')>0 for x in structures):
        return 'PRIMARY_HIDDEN_SEMANTIC_STATUS_ELEMENT'
    if all(n(x,'scope_counts','PRIMARY')==0 for x in structures) and all(
            n(x,'scope_counts','RECOMMENDATION')==0 and
            n(x,'scope_counts','NAVIGATION')==0 and
            n(x,'scope_counts','INTERACTION')==0 and
            n(x,'scope_counts','OUTSIDE_PRIMARY')==0 for x in structures) and any(
            n(x,'scope_counts','LINKED_OTHER_LISTING')>0 for x in structures):
        return 'STATUS_TOKENS_ONLY_IN_OTHER_LISTING_CARDS'
    if any(n(x,'scope_counts','RECOMMENDATION')+
           n(x,'scope_counts','LINKED_OTHER_LISTING')+
           n(x,'scope_counts','NAVIGATION')+
           n(x,'scope_counts','INTERACTION')+
           n(x,'scope_counts','OUTSIDE_PRIMARY')>0 for x in structures):
        return 'STATUS_TOKENS_ONLY_OUTSIDE_PRIMARY'
    return 'NO_EXACT_STATUS_TOKEN_IN_BOUNDED_DOM_PHASES'


def aggregate(rows):
    counts=Counter()
    detail_rows=[]
    for row in rows:
        d=row.get('v420_detail_audit') or {}
        item_rows=[]
        for item in d.get('samples') or []:
            probe=item.get('v422_dom_diagnostic') or {}
            outcome=probe.get('outcome','NOT_CAPTURED')
            counts[outcome]+=1
            item_rows.append({
                'rank':item.get('source_rank'),
                'identity_confirmed':item.get('same_listing_identity') is True,
                'page_status':item.get('page_status'),
                'outcome':outcome,
                'phases':probe.get('phases') or {}})
        detail_rows.append({
            'context':row.get('context'),'route_count':row.get('route_count'),
            'route_correlated':row.get('route_correlated') is True,
            'audit_status':d.get('status'),
            'detail_visits':d.get('page_visits'),
            'sample_count':d.get('selected_sample_count'),
            'items':item_rows})
    complete=(len(rows)==3 and sum(counts.values())==9 and
        all(row.get('route_correlated') is True and
            (row.get('v420_detail_audit') or {}).get('status')=='DETAIL_SAMPLE_AUDITED'
            and (row.get('v420_detail_audit') or {}).get('page_visits')==3
            and all((x.get('v422_dom_diagnostic') or {}).get('status')=='CAPTURED'
                    and len((x.get('v422_dom_diagnostic') or {}).get('phases') or {})==4
                    for x in (row.get('v420_detail_audit') or {}).get('samples',[]))
            for row in rows))
    blocked=any((r.get('v420_detail_audit') or {}).get('stop_access') is True for r in rows)
    if blocked:verdict='STOP_ACCESS_RESTRICTION'
    elif not complete:verdict='INCONCLUSIVE_DOM_RENDER_AUDIT_INCOMPLETE'
    elif counts['NO_EXACT_STATUS_TOKEN_IN_BOUNDED_DOM_PHASES']==9:
        verdict='NO_EXACT_VISIBLE_STATUS_UI_IN_TESTED_DOM_PHASES'
    elif sum(v for k,v in counts.items() if k.startswith('STATUS_EMERGED_'))>0:
        verdict='STATE_RENDERING_CONDITION_OBSERVED'
    elif counts['PRIMARY_VISIBLE_STATUS_OLD_SELECTOR_GAP']>0:
        verdict='V421_SELECTOR_COVERAGE_GAP_OBSERVED'
    elif counts['STATUS_TOKENS_ONLY_IN_OTHER_LISTING_CARDS']==9:
        verdict='ONLY_OTHER_LISTING_CARD_STATUS_MARKERS_OBSERVED'
    else:verdict='MIXED_OR_NONPRIMARY_DOM_STATUS_EVIDENCE'
    return {
        'status':verdict,'capture_complete':complete,
        'sampled_detail_visits':sum(counts.values()),
        'diagnostic_outcome_counts':dict(sorted(counts.items())),
        'initial_no_visible_v421_status':sum(
            (item.get('phases') or {}).get('initial',{}).get('v421_ui_state')=='NOT_OBSERVABLE'
            for row in detail_rows for item in row['items']),
        'whole_route_status_ui_proven':False,
        'inferred_sitewide_absence':False,
        'jsonld_instock_substituted_for_ui':False,
        'strict_listing_approved_count':0,
        'contexts':detail_rows}


def report(result):
    e=result['evaluation']
    lines=['# v4.22 detailed DOM/rendering diagnosis','',
           f"- Final diagnosis: **{e['status']}**",
           f"- Study complete: {e['capture_complete']}",
           f"- Bounded detail visits: {e['sampled_detail_visits']}",
           f"- Original v4.21 UI not observable at initial phase: {e['initial_no_visible_v421_status']}",
           '- No claim about unobserved site conditions, other devices, sessions or listings.',
           '- Existing strict listing gate: unchanged, 0 approved.',
           '', '| Context | Route rows | Detail visits | Outcome distribution |',
           '|---|---:|---:|---|']
    for row in e['contexts']:
        outcomes=Counter(x['outcome'] for x in row['items'])
        vals=', '.join(f'{k}:{v}' for k,v in sorted(outcomes.items()))
        lines.append(f"| {row['context']} | {row['route_count']} | {row['detail_visits']} | {vals} |")
    lines+=['','## Observation conditions','',
        '- Initial: after the bounded v4.20 page settle and v4.21 status check.',
        '- Delayed: same document after an additional bounded wait.',
        '- Scrolled: same document with primary heading scrolled into view.',
        '- Narrow: same document at 390×844 viewport, without clicking or navigating.',
        '- For exact status tokens, the bounded DOM probe records only scope, tag/role categories, visibility reason and ancestor tag shape; no raw text, URLs, item IDs or HTML.',
        '- A missing exact token across these conditions means *not observed in this bounded sample*, not that the site never shows a status UI.',
        '- A visible status found in the structural audit is an investigation lead, not automatic independent v4.21 status proof.','']
    return '\n'.join(lines)


async def run(opts):
    opts.filter_recheck_v15=True
    opts.detail_probe_v420=True
    opts.sale_sources_v421=True
    opts.dom_diagnosis_v422=True
    opts.filter_dom_v16=False
    opts.filter_activation_v161=False
    rows=[]
    salt=secrets.token_bytes(32)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=not opts.headed)
            try:
                for name,region in [('cheonan_a','cheonan'),('asan_control','asan'),
                                    ('cheonan_b','cheonan')]:
                    row=await full.capture(browser,name,region,opts,salt)
                    rows.append(row)
                    d=row.get('v420_detail_audit') or {}
                    print('v4.22',name,'route',row.get('route_count'),
                          'sample',d.get('page_visits'),'status',d.get('status'),
                          'diagnoses',[(x.get('v422_dom_diagnostic') or {}).get('outcome')
                                     for x in d.get('samples',[])])
                    if row.get('status','').startswith('STOP_') or row.get('access_blocked'):
                        break
                    if d.get('status','').startswith('STOP_'):
                        break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as exc:
        rows.append({'context':'browser','status':'STOP_'+type(exc).__name__,
                     'route_correlated':False})
    outcome=aggregate(rows)
    output={'version':'4.22','utc_timestamp':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'design':{'detail_visits_upper_bound':9,
                      'contexts':['cheonan_a','asan_control','cheonan_b'],
                      'phases':list(PHASES),
                      'no_additional_detail_navigation':True,
                      'original_route_and_detail_robots_required':True,
                      'original_approval_gate_unchanged':True},
            'evaluation':outcome,
            'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    opts.output_dir.mkdir(parents=True,exist_ok=True)
    (opts.output_dir/'v422_dom_render_results.json').write_text(
        json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (opts.output_dir/'v422_dom_render_report.md').write_text(
        report(output),encoding='utf-8')
    (opts.output_dir/'v422_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if outcome['capture_complete'] and not (
        outcome['status']=='STOP_ACCESS_RESTRICTION') else 2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=Path('v422_output'))
    parser.add_argument('--timeout',type=int,default=25)
    parser.add_argument('--settle-ms',type=int,default=1600)
    parser.add_argument('--headed',action='store_true')
    opts=parser.parse_args()
    opts.output_dir=opts.output_dir.resolve()
    opts.timeout=max(15,min(45,opts.timeout))
    opts.settle_ms=max(800,min(3500,opts.settle_ms))
    return asyncio.run(run(opts))


if __name__=='__main__':
    raise SystemExit(main())
