# -*- coding: utf-8 -*-
"""v4.23: public sold/reserved control listings discovered from real linked cards.

No invented listing IDs, guessed search APIs, login, bypass, or uncontrolled
pagination. This is a read-only controlled study, not a source of approved
listing exports. A linked card is a *hypothesis* about another listing's
status, never a primary-page witness until its own robots-approved detail is
checked. All URLs and item identifiers exist only in memory.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import secrets
from urllib.parse import urlsplit

import daangn_v4_1_core as core
import daangn_render_gap_v4_12 as render
import daangn_detail_crosscheck_v4_20 as detail
import daangn_sale_sources_v4_21 as sources
from daangn_state_consumers_v4_25 import consume, control_comparison, summarize
import daangn_status_dom_v4_22 as dom
import daangn_full_route_v4_14 as full

TARGET_STATES=('SOLD','RESERVED')
MAX_CONTROLS_PER_CONTEXT=2
MAX_CONTEXTS=3
MAX_EXTRA_DETAIL_VISITS=6
PHASES=dom.PHASES

CARD_JS=r"""() => {
  // The source is an already visited, exact-identity public detail page.
  // Only statuses inside a *different public listing link* are candidates.
  const exact=new Map([['판매완료','SOLD'],['판매 완료','SOLD'],
    ['거래완료','SOLD'],['거래 완료','SOLD'],
    ['예약중','RESERVED'],['예약 중','RESERVED']]);
  const state=s=>exact.get(String(s||'').replace(/\s+/g,' ').trim().slice(0,80))||null;
  const validCSS=el=>{
    for(let a=el,i=0;a&&i<24;a=a.parentElement,i++){
      const s=getComputedStyle(a);
      if(s.display==='none'||s.visibility==='hidden'||
         s.visibility==='collapse'||s.opacity==='0'||a.hasAttribute('inert')||
         a.getAttribute('aria-hidden')==='true')return false;
    }
    const b=el.getBoundingClientRect();
    return b.width>0&&b.height>0&&el.getClientRects().length>0;
  };
  const links=[...document.querySelectorAll('a[href*="/kr/buy-sell/"]')].slice(0,600);
  const found=[];
  let statusNodes=0,offscreen=0;
  for(const a of links){
    if(!validCSS(a))continue;
    const values=new Set();
    for(const e of [...a.querySelectorAll('span,div,p,strong,b,em,small,label')].slice(0,70)){
      const direct=[...e.childNodes].filter(n=>n.nodeType===3)
        .map(n=>n.textContent||'').join(' ');
      const s=state(direct)||state(e.getAttribute('aria-label'));
      if(!s||!validCSS(e))continue;
      values.add(s);statusNodes++;
      const bb=e.getBoundingClientRect();
      if(bb.bottom<0||bb.top>=innerHeight)offscreen++;
    }
    if(values.size!==1)continue; // no mixed badges in one candidate card
    const href=a.getAttribute('href');
    if(typeof href!=='string'||href.length>420)continue;
    // Canonical public URL checks, identity and robots occur in Python.
    found.push({href,state:[...values][0]});
    if(found.length>=45)break;
  }
  return {status:'OBSERVED',links_scanned:links.length,
          status_nodes:Math.min(statusNodes,300),
          offscreen_nodes:Math.min(offscreen,300),
          candidates:found};
}""".strip()


# Exact first-party matched Product JSON-LD availability only, while preserving
# the original v4.21 classifier has been removed in v4.26.
# OutOfStock is generic stock unavailability; it does NOT prove SOLD.
AVAILABILITY_KINDS=frozenset({
    'IN_STOCK','OUT_OF_STOCK','SOLD_OUT','PRE_ORDER','PRE_SALE',
    'NOT_OBSERVABLE','AMBIGUOUS','OTHER'})
AVAILABILITY_JS=r"""() => {
  const sameListing=s=>{
    if(typeof s!=='string'||s.length>2048)return false;
    try{
      const u=new URL(s,window.location.href);
      return u.origin===window.location.origin&&
        u.pathname.replace(/\/?$/,'/')===window.location.pathname.replace(/\/?$/,'/');
    }catch{return false;}
  };
  const matched=[];
  const walk=(x,depth=0)=>{
    if(!x||depth>5||matched.length>12)return;
    if(Array.isArray(x)){x.slice(0,15).forEach(y=>walk(y,depth+1));return;}
    if(typeof x!=='object')return;
    const types=Array.isArray(x['@type'])?x['@type']:[x['@type']];
    if(types.some(y=>typeof y==='string'&&y.split('/').pop()==='Product')){
      const ref=x.url||x.mainEntityOfPage;
      const url=typeof ref==='string'?ref:ref&&typeof ref==='object'?ref['@id']:null;
      if(sameListing(url))matched.push(x);
    }
    if(x['@graph'])walk(x['@graph'],depth+1);
  };
  for(const node of [...document.querySelectorAll('script[type="application/ld+json"]')].slice(0,8)){
    const raw=node.textContent||'';
    if(raw.length>30000)continue;
    try{walk(JSON.parse(raw));}catch{}
  }
  const types={InStock:'IN_STOCK',OutOfStock:'OUT_OF_STOCK',
    SoldOut:'SOLD_OUT',PreOrder:'PRE_ORDER',PreSale:'PRE_SALE'};
  if(matched.length!==1){
    return {kind:matched.length>1?'AMBIGUOUS':'NOT_OBSERVABLE',
            matched_product_count:Math.min(20,matched.length)};
  }
  let offers=matched[0].offers;
  if(Array.isArray(offers))offers=offers.length===1?offers[0]:null;
  const uri=offers&&typeof offers==='object'?offers.availability:null;
  if(typeof uri!=='string')
    return {kind:'NOT_OBSERVABLE',matched_product_count:1};
  const suffix=uri.split('/').pop();
  return {kind:types[suffix]||'OTHER',matched_product_count:1};
}""".strip()


async def probe_exact_availability(page):
    """Return only safe finite schema enums, never original JSON-LD."""
    try:
        raw=await asyncio.wait_for(page.evaluate(AVAILABILITY_JS),timeout=7)
    except Exception as exc:
        return {'status':'ERROR_'+type(exc).__name__,
                'kind':'NOT_OBSERVABLE','matched_product_count':None}
    if not isinstance(raw,dict):
        return {'status':'INVALID','kind':'NOT_OBSERVABLE',
                'matched_product_count':None}
    count=raw.get('matched_product_count')
    return {'status':'OBSERVED',
            'kind':raw.get('kind') if isinstance(raw.get('kind'),str)
                    and raw.get('kind') in AVAILABILITY_KINDS else 'OTHER',
            'matched_product_count':count if type(count) is int and 0<=count<=20
                                     else None}


def canonical_public_detail(raw):
    """Only actual first-party HTTPS canonical detail paths, no URL query."""
    if not isinstance(raw,str) or len(raw)>420:return None
    try:
        p=urlsplit(raw)
        if raw.startswith('/'):
            if raw.startswith('//') or p.scheme or p.netloc:return None
        elif p.scheme!='https' or p.netloc!='www.daangn.com':
            return None
        if p.query or p.fragment or p.username or p.password or p.port:
            return None
        normalized=core.normalized_listing(raw)
        if not normalized:return None
        n=urlsplit(normalized)
        if n.scheme!='https' or n.netloc!='www.daangn.com':
            return None
        return normalized
    except (ValueError,TypeError):
        return None


def sanitize_cards(raw,origin):
    """Intermediate candidate URLs never cross into output artifacts."""
    safe={'status':'INVALID','links_scanned':0,'status_nodes':0,
          'offscreen_nodes':0,'eligible_by_state':{'SOLD':0,'RESERVED':0}}
    if not isinstance(raw,dict) or raw.get('status')!='OBSERVED':
        return safe,[]
    def small(v):
        return v if type(v) is int and 0<=v<=600 else 0
    safe['status']='OBSERVED'
    safe['links_scanned']=small(raw.get('links_scanned'))
    safe['status_nodes']=small(raw.get('status_nodes'))
    safe['offscreen_nodes']=small(raw.get('offscreen_nodes'))
    controls=[]
    seen=set()
    rows=raw.get('candidates') if isinstance(raw.get('candidates'),list) else []
    for row in rows[:45]:
        if not isinstance(row,dict) or row.get('state') not in TARGET_STATES:
            continue
        uri=canonical_public_detail(row.get('href'))
        if not uri or uri==origin or uri in seen:continue
        seen.add(uri)
        controls.append({'url':uri,'source_card_state':row['state']})
        safe['eligible_by_state'][row['state']]+=1
    return safe,controls


async def collect_cards(page,source_uri):
    try:
        raw=await asyncio.wait_for(page.evaluate(CARD_JS),timeout=8)
        return sanitize_cards(raw,source_uri)
    except Exception as exc:
        return {'status':'ERROR_'+type(exc).__name__,
                'eligible_by_state':{'SOLD':0,'RESERVED':0}},[]


def choose_controls(pool,max_targets=MAX_CONTROLS_PER_CONTEXT):
    """Prefer independent SOLD and RESERVED; no guesses if one is absent."""
    chosen=[]
    used=set()
    for target in TARGET_STATES:
        for item in pool:
            if item.get('source_card_state')!=target:continue
            uri=canonical_public_detail(item.get('url'))
            if not uri or uri in used:continue
            chosen.append({'url':uri,'source_card_state':target,
                           'source_rank':item.get('source_rank')})
            used.add(uri)
            break
        if len(chosen)>=max_targets:break
    return chosen


def control_verdict(canonical_record):
    """v4.26: reject legacy JSON-LD/classification arguments entirely."""
    return control_comparison(canonical_record)


def phase_projection(diag):
    frames=(diag or {}).get('phases') or {}
    output={}
    for name in PHASES:
        x=frames.get(name) if isinstance(frames.get(name),dict) else {}
        st=x.get('structure') if isinstance(x.get('structure'),dict) else {}
        output[name]={
            'ui':x.get('v421_ui_state') if isinstance(x.get('v421_ui_state'),str)
                  and x.get('v421_ui_state') in sources.SALE_STATE
                  else 'NOT_OBSERVABLE',
            'dom_scan_complete':st.get('scan_complete') is True,
            'primary_visible_tokens':st.get('primary_visible_exact_tokens')
              if type(st.get('primary_visible_exact_tokens')) is int else None,
            'related_listing_tokens':(st.get('scope_counts') or {}).get('LINKED_OTHER_LISTING')
              if isinstance(st.get('scope_counts'),dict) else None}
    return output


async def audit_controls(page,pool,options,*,checker=None):
    """At most two real public targets selected from authentic card badges."""
    checker=checker or detail.robots_check_detail
    chosen=choose_controls(pool)
    report={'status':'NOT_STARTED',
        'selected_control_count':len(chosen),
        'selected_source_status_counts':dict(sorted(Counter(
            i['source_card_state'] for i in chosen).items())),
        'both_control_classes_found':set(i['source_card_state'] for i in chosen)==set(TARGET_STATES),
        'detail_robots':{'allowed':False,'reason':'NOT_CHECKED'},
        'visited_control_count':0,
        'stop_access':False,'controls':[],
        'strict_listing_approved_count':0}
    if not chosen:
        report['status']='NO_ELIGIBLE_SOLD_OR_RESERVED_PUBLIC_CARD'
        return report
    agent=await page.evaluate('()=>navigator.userAgent')
    robot=await asyncio.to_thread(checker,[i['url'] for i in chosen],
                                  user_agent=agent)
    report['detail_robots']=robot
    if robot.get('allowed') is not True:
        report['status']='STOP_CONTROL_ROBOTS_'+str(robot.get('reason','UNKNOWN'))
        report['stop_access']=True
        return report
    for selected in chosen:
        entry={'source_rank':selected.get('source_rank'),
               'source_card_state':selected['source_card_state'],
               'status':'NOT_VISITED',
               'identity_matched':False,
               'page_status':'NOT_VISITED',
               'initial_visible_ui':'NOT_OBSERVABLE',
               'target_jsonld_exact_kind':'NOT_OBSERVABLE',
               'exact_schema_probe_status':'NOT_CAPTURED',
               'render_diagnosis':'NOT_CAPTURED',
               'phases':{},'comparison':'NOT_OBSERVABLE'}
        report['controls'].append(entry)
        try:
            response=await page.goto(selected['url'],wait_until='domcontentloaded',
                                     timeout=options.timeout*1000)
            report['visited_control_count']+=1
            if response is None:
                entry['status']='HTTP_NO_RESPONSE';continue
            if response.status in core.BLOCK_STATUS:
                entry['status']='STOP_ACCESS_RESTRICTION'
                report['stop_access']=True
                break
            if response.status==404:
                entry['status']='NOT_FOUND_NOT_SOLD_PROOF'
                continue
            if response.status!=200:
                entry['status']='HTTP_OTHER'
                continue
            await page.wait_for_timeout(options.settle_ms)
            if (await render.snapshot(page)).get('restricted'):
                report['stop_access']=True
                entry['status']='STOP_ACCESS_RESTRICTION'
                break
            matched=canonical_public_detail(page.url)==selected['url']
            entry['identity_matched']=matched
            if not matched:
                entry['status']='IDENTITY_CHANGED'
                continue
            entry['page_status']='HTTP_200_EXACT_IDENTITY'
            witness=await sources.probe_sources(page)
            if witness.get('status')!='OBSERVED':
                entry['status']='WITNESS_NOT_OBSERVABLE'
                continue
            entry['initial_visible_ui']=(witness.get('ui') or {}).get('state',
                                              'NOT_OBSERVABLE')
            exact=await probe_exact_availability(page)
            entry['exact_schema_probe_status']=exact['status']
            entry['target_jsonld_exact_kind']=exact['kind']
            diag=await dom.examine(page,witness,options.settle_ms)
            entry['render_diagnosis']=diag.get('outcome','INCOMPLETE_PHASES')
            entry['phases']=phase_projection(diag)
            if getattr(options,'status_signals_v429',False):
                from daangn_status_signals_v4_29 import probe as v429_probe
                if canonical_public_detail(page.url)==selected['url'] and not (
                    await render.snapshot(page)).get('restricted'):
                    entry['v429_status_signal_survey']=await v429_probe(page)
                else:
                    entry['v429_status_signal_survey']={'status':'PRIMARY_NOT_VERIFIED'}
            if getattr(options,'for_sale_diagnosis_v428',False):
                from daangn_for_sale_ui_v4_28 import probe as v428_probe
                if canonical_public_detail(page.url)==selected['url'] and not (
                    await render.snapshot(page)).get('restricted'):
                    entry['v428_for_sale_probe']=await v428_probe(page)
                    entry['v428_dom_diagnostic']=diag
                else:
                    entry['v428_for_sale_probe']={'status':'PRIMARY_NOT_VERIFIED'}
            if canonical_public_detail(page.url)!=selected['url']:
                entry['status']='IDENTITY_CHANGED'
                continue
            if (await render.snapshot(page)).get('restricted'):
                entry['status']='STOP_ACCESS_RESTRICTION'
                report['stop_access']=True
                break
            ui=[x['ui'] for x in entry['phases'].values()]
            from daangn_listing_state_v4_24 import build_record, clean_record
            record=build_record(
                ui,entry['target_jsonld_exact_kind'],
                card_state=entry['source_card_state'],
                identity_confirmed=matched,
                render_complete=diag.get('status')=='CAPTURED',
                same_product=(exact['status']=='OBSERVED'
                    and exact.get('matched_product_count')==1),
                context='CONTROL',
                ui_origin='PRIMARY_PHASE_OBSERVATION')
            entry['v424_state_model']=clean_record(record)
            entry['comparison']=control_verdict(entry['v424_state_model'])
            entry['v425_control_comparison']=entry['comparison']
            entry['status']='AUDITED' if diag.get('status')=='CAPTURED' else 'INCONCLUSIVE_DOM'
        except Exception as exc:
            entry['status']='ERROR_'+type(exc).__name__
        if report['stop_access']:break
        await asyncio.sleep(1.5)
    report['status']='STOP_ACCESS_RESTRICTION' if report['stop_access'] else (
         'CONTROL_DETAILS_AUDITED' if report['visited_control_count']==len(chosen)
         else 'CONTROL_DETAILS_INCOMPLETE')
    return report



def project_source_pipeline(sample):
    """Allowlisted per-source witness path, without item URL or seller identity."""
    from daangn_listing_state_v4_24 import UI_STATES, AVAILABILITY_KINDS
    if not isinstance(sample,dict):
        return None
    src=sample.get('v421_sale_sources')
    src=src if isinstance(src,dict) else {}
    ui=src.get('ui') if isinstance(src.get('ui'),dict) else {}
    meta=src.get('jsonld') if isinstance(src.get('jsonld'),dict) else {}
    def bounded(value, choices, default):
        return value if isinstance(value,str) and value in choices else default
    cat=(sample.get('category') or {})
    cat=cat if isinstance(cat,dict) else {}
    v420=(sample.get('sale') or {})
    v420=v420 if isinstance(v420,dict) else {}
    return {
        'source_rank':sample.get('source_rank') if type(sample.get('source_rank')) is int
                      and 0<=sample['source_rank']<=650 else None,
        'page_identity_confirmed':sample.get('same_listing_identity') is True,
        'detail_http_200_identity':sample.get('page_status')=='HTTP_200_IDENTITY_MATCH',
        'primary_heading_visible':sample.get('v420_heading_visible') is True,
        'category_verdict':bounded(cat.get('verdict'),
            ('MATCH','MISMATCH','AMBIGUOUS','NOT_OBSERVABLE'),'NOT_OBSERVABLE'),
        'category_evidence_source':bounded(cat.get('source'),(
            'PRIMARY_SEMANTIC_CATEGORY','PAGE_META_CATEGORY',
            'MATCHED_PRODUCT_JSONLD'),'NONE'),
        # Numeric per-item price is from the same exact Route item selected
        # before navigating to its exact-identity public detail page.
        'route_item_price_krw':sample.get('v432_route_price_krw') if (
            type(sample.get('v432_route_price_krw')) is int and
            0<=sample['v432_route_price_krw']<=1000000000 and
            sample.get('v432_route_price_item_identity') is True and
            sample.get('page_status')=='HTTP_200_IDENTITY_MATCH' and
            sample.get('same_listing_identity') is True) else None,
        'route_item_price_identity_matched':bool(
            sample.get('v432_route_price_item_identity') is True and
            sample.get('page_status')=='HTTP_200_IDENTITY_MATCH' and
            sample.get('same_listing_identity') is True),
        # 80-bit HMAC tag from one capture-scoped secret; cannot be
        # compared across independent runs. No raw article identity.
        'listing_run_hmac':sample.get('v433_listing_run_hmac') if (
            isinstance(sample.get('v433_listing_run_hmac'),str) and
            re.fullmatch(r'[0-9a-f]{20}',sample['v433_listing_run_hmac'])
            and sample.get('page_status')=='HTTP_200_IDENTITY_MATCH'
            and sample.get('same_listing_identity') is True
            and sample.get('v432_route_price_item_identity') is True) else None,
        'v420_ui_status':bounded(v420.get('verdict'),UI_STATES,'NOT_OBSERVABLE'),
        'v420_verdict':bounded(sample.get('detail_verdict'),(
            'IDENTITY_MISMATCH','DETAIL_NOT_OBSERVABLE','CATEGORY_CONTRADICTION',
            'DETAIL_CANONICAL_NOT_VERIFIED','DETAIL_AMBIGUOUS','CATEGORY_ONLY',
            'DETAIL_FIELDS_NOT_OBSERVABLE','NOT_AVAILABLE',
            'ITEM_UI_PREDICATES_CORROBORATED','SALE_ONLY'),'NOT_OBSERVABLE'),
        'v421_probe_status':bounded(src.get('status'),
            ('OBSERVED','NOT_OBSERVABLE','INVALID'),'NOT_OBSERVABLE'),
        'v421_primary_valid':src.get('valid_primary') is True,
        'v421_ui_status':bounded(ui.get('state'),UI_STATES,'NOT_OBSERVABLE'),
        'v421_ui_origin':bounded(ui.get('source'),
            ('PRIMARY_STATUS_MARKER','PRIMARY_EXACT_VISIBLE_LEAF',
             'NONE'),'NONE'),
        'v421_exact_availability':bounded(meta.get('kind'),
            AVAILABILITY_KINDS,'NOT_OBSERVABLE'),
        'v421_product_match_count':meta.get('matching_product_count')
            if type(meta.get('matching_product_count')) is int and
               0<=meta['matching_product_count']<=20 else None,
        'v421_verdict':bounded(sample.get('v421_sale_comparison'),(
            'IDENTITY_NOT_MATCHED','SOURCES_NOT_OBSERVABLE',
            'MISSING_CANONICAL_RECORD','INVALID_CANONICAL_RECORD',
            'CANONICAL_SEMANTIC_CONFLICT_QUARANTINED',
            'CANONICAL_METADATA_NOT_PRIMARY_UI_PROOF',
            'CANONICAL_UI_NOT_VERIFIED','CANONICAL_UI_AND_STOCK_COMPATIBLE',
            'CANONICAL_UI_WITH_NONSPECIFIC_STOCK',
            'CANONICAL_PRIMARY_UI_ONLY','CANONICAL_UI_STOCK_INCONCLUSIVE'),
            'NOT_OBSERVABLE')
    }



def project_v428_diagnosis(probe, kind='SOURCE'):
    """Export only allowlisted finite-state DOM forensics per already visited item."""
    from daangn_for_sale_ui_v4_28 import sanitize
    src=probe if isinstance(probe,dict) else {}
    raw=src.get('v428_for_sale_probe') or {}
    safe=sanitize(raw) if isinstance(raw,dict) and 'scan_complete' in raw else {
        'status':'PRIMARY_NOT_VERIFIED','explicit_positive_proof':False,
        'ctas_are_transaction_proof':False,'jsonld_is_transaction_proof':False}
    diag=src.get('v422_dom_diagnostic') if kind=='SOURCE' else src.get('v428_dom_diagnostic')
    diag=diag if isinstance(diag,dict) else {}
    frames=diag.get('phases') if isinstance(diag.get('phases'),dict) else {}
    frame_projection={}
    for name in dom.PHASES:
        row=frames.get(name) if isinstance(frames.get(name),dict) else {}
        structure=row.get('structure') if isinstance(row.get('structure'),dict) else {}
        def n(k):
            v=structure.get(k)
            return v if type(v) is int and 0<=v<=3500 else None
        sc=structure.get('scope_counts')
        sc=sc if isinstance(sc,dict) else {}
        frame_projection[name]={
            'ui':row.get('v421_ui_state') if isinstance(row.get('v421_ui_state'),str)
                and row.get('v421_ui_state') in sources.SALE_STATE else 'NOT_OBSERVABLE',
            'same_document_url':row.get('same_document_url') is True,
            'scan_complete':structure.get('scan_complete') is True,
            'primary_heading_visible':structure.get('primary_heading_visible') is True,
            'primary_visible_exact_tokens':n('primary_visible_exact_tokens'),
            'primary_nonvisible_exact_tokens':n('primary_nonvisible_exact_tokens'),
            'old_selector_missed':n('primary_old_selector_missed'),
            'linked_listing_exact_tokens':sc.get('LINKED_OTHER_LISTING')
                if type(sc.get('LINKED_OTHER_LISTING')) is int
                    and 0<=sc['LINKED_OTHER_LISTING']<=3500 else None,
            'primary_exact_tokens':sc.get('PRIMARY')
                if type(sc.get('PRIMARY')) is int and 0<=sc['PRIMARY']<=3500 else None}
    outcome=diag.get('outcome')
    return {'source_rank':src.get('source_rank')
            if type(src.get('source_rank')) is int and 0<=src['source_rank']<=650 else None,
        'role':kind,'probe':safe,
        'dom_outcome':outcome if isinstance(outcome,str) and outcome in (
            'VISIBLE_STATUS_REPRODUCED','STATUS_EMERGED_AFTER_SETTLE',
            'STATUS_EMERGED_AFTER_SCROLL','STATUS_EMERGED_NARROW_VIEWPORT',
            'PRIMARY_VISIBLE_STATUS_OLD_SELECTOR_GAP',
            'PRIMARY_VISIBLE_STATUS_UNRESOLVED_BY_V421',
            'PRIMARY_STATUS_TOKEN_HIDDEN_OR_OFFSCREEN',
            'PRIMARY_SEMANTIC_STATUS_ELEMENT_WITHOUT_EXACT_SALE_TOKEN',
            'PRIMARY_HIDDEN_SEMANTIC_STATUS_ELEMENT',
            'STATUS_TOKENS_ONLY_IN_OTHER_LISTING_CARDS',
            'STATUS_TOKENS_ONLY_OUTSIDE_PRIMARY',
            'NO_EXACT_STATUS_TOKEN_IN_BOUNDED_DOM_PHASES',
            'INCOMPLETE_PHASES','PAGE_URL_CHANGED','INCONCLUSIVE_DOM_SCAN')
            else 'INCOMPLETE_PHASES',
        'dom_capture_status':diag.get('status') if diag.get('status') in (
            'CAPTURED','INCONCLUSIVE') else 'NOT_CAPTURED',
        'phases':frame_projection}



def project_v429_signal(item,kind):
    """One rank-linked sanitized witness, never raw page or seller fields."""
    from daangn_status_signals_v4_29 import sanitize
    src=item if isinstance(item,dict) else {}
    data=src.get('v429_status_signal_survey')
    if isinstance(data,dict) and 'scan_complete' in data:
        safe=sanitize(data)
    else:
        safe={'status':'PRIMARY_NOT_VERIFIED','direct_for_sale_proven':False,
              'machine_trade_field_calibrated':False,
              'stock_metadata_is_transaction_proof':False}
    return {'role':kind,
        'source_rank':src.get('source_rank') if type(src.get('source_rank')) is int
              and 0<=src['source_rank']<=650 else None,'survey':safe}


def aggregate(rows):
    """Separate control discovery, attempted visits and actual verified UI."""
    controls=[]
    bycontext=[]
    source_counts=Counter()
    # Preserve only the exception class for startup failures; no messages/URLs.
    runtime_errors=Counter(row.get('status') for row in rows
        if isinstance(row,dict) and row.get('context')=='browser'
        and isinstance(row.get('status'),str)
        and re.fullmatch(r'STOP_[A-Za-z]{1,48}',row['status']))
    for row in rows:
        detail_audit=row.get('v420_detail_audit') or {}
        ctrl=detail_audit.get('v423_controls') or {}
        samples=detail_audit.get('samples') or []
        for s in samples:
            stats=s.get('v423_card_stats') or {}
            eligible=stats.get('eligible_by_state') or {}
            for st in TARGET_STATES:source_counts[st]+=eligible.get(st,0) or 0
        controls+=ctrl.get('controls') or []
        bycontext.append({'context':row.get('context'),
           'route_correlated':row.get('route_correlated') is True,
           'source_detail_count':detail_audit.get('page_visits'),
           'control_discovery':ctrl.get('status','NOT_OBSERVED'),
           'control_classes_found':ctrl.get('both_control_classes_found') is True,
           'selected_control_count':ctrl.get('selected_control_count',0),
           'visited_control_count':ctrl.get('visited_control_count',0),
           'controls':ctrl.get('controls') or [],
           # Only rank and allowlisted v4.24 evidence, never item URL/slug.
           'v427_source_pipeline':[
                project_source_pipeline(item) for item in samples[:3]],
           'v428_source_diagnostics':[
                project_v428_diagnosis(item,'SOURCE') for item in samples[:3]],
           'v428_control_diagnostics':[
                project_v428_diagnosis(item,'CONTROL') for item in (ctrl.get('controls') or [])[:2]],
           'v429_source_signal_surveys':[
                project_v429_signal(item,'SOURCE') for item in samples[:3]],
           'v429_control_signal_surveys':[
                project_v429_signal(item,'CONTROL') for item in (ctrl.get('controls') or [])[:2]],
           'source_state_models':[
               {'source_rank':item.get('source_rank'),
                'model':item['v424_state_model']}
               for item in samples if isinstance(item.get('v424_state_model'),dict)
           ]})
    source_records=[
        consume(s.get('v424_state_model'),'SOURCE')
        for row in rows for s in
        ((row.get('v420_detail_audit') or {}).get('samples') or [])]
    source_coverage=summarize(source_records,expected_count=MAX_CONTEXTS*3)
    source_complete=source_coverage['status']=='CANONICAL_COVERAGE_COMPLETE'
    audited_controls=[x for x in controls if x.get('status')=='AUDITED']
    canonical_views=[consume(x.get('v424_state_model'),'CONTROL') for x in audited_controls]
    canonical_summary=summarize(canonical_views,expected_count=len(audited_controls))
    canonical_complete=canonical_summary['status']=='CANONICAL_COVERAGE_COMPLETE'
    results=[control_verdict(x.get('v424_state_model')) for x in controls]
    statuses=Counter(results)
    by_card=[(x,consume(x.get('v424_state_model'),'CONTROL'))
             for x in audited_controls]
    per_class_proven={state:any(x.get('source_card_state')==state
        and view['card_ui_corroborated']
        and view['primary_transaction_status']==state
        for x,view in by_card) for state in TARGET_STATES}
    all_captured=source_complete and len(rows)==MAX_CONTEXTS and all(
        row.get('route_correlated') is True and
        (row.get('v420_detail_audit') or {}).get('status')=='DETAIL_SAMPLE_AUDITED'
        and (row.get('v420_detail_audit') or {}).get('page_visits')==3
        and (row.get('v420_detail_audit') or {}).get('v423_controls',{}).get('status')
            in ('CONTROL_DETAILS_AUDITED','NO_ELIGIBLE_SOLD_OR_RESERVED_PUBLIC_CARD')
        for row in rows)
    blocked=any((row.get('v420_detail_audit') or {}).get('stop_access')
        or (row.get('v420_detail_audit') or {}).get('v423_controls',{}).get('stop_access')
        for row in rows)
    audited_states=set(x.get('source_card_state') for x in audited_controls)
    both=audited_states==set(TARGET_STATES)
    matched_ui=sum(view['card_ui_corroborated'] for _,view in by_card)
    both_proven=all(per_class_proven.values())
    disagreements=sum(view['status']=='CANONICAL_QUARANTINED'
                      for _,view in by_card)
    availability_counts=Counter(view['product_jsonld_exact_availability']
        for _,view in by_card if view['schema_valid'])
    metadata_broad=sum(view['card_ui_corroborated'] and
        view['product_jsonld_stock_class'] in
        ('UNAVAILABLE_GENERIC','PRE_ORDER','PRE_SALE','SOLD_OUT')
        for _,view in by_card)
    if blocked:status='STOP_ACCESS_RESTRICTION'
    elif not all_captured:status='INCONCLUSIVE_CONTROL_STUDY_INCOMPLETE'
    elif not canonical_complete:status='INCONCLUSIVE_CANONICAL_CONTROL_RECORDS'
    elif disagreements:status='PUBLIC_CONTROL_WITNESSES_CONFLICT'
    elif both_proven:status='BOTH_SOLD_AND_RESERVED_CONTROL_UI_CORROBORATED'
    elif not both:status='PARTIAL_CONTROL_CLASSES_AVAILABLE'
    elif matched_ui==0:status='CONTROL_UI_NOT_OBSERVABLE'
    else:status='PARTIAL_CONTROL_UI_CORROBORATED'
    return {'status':status,'bounded_capture_complete':all_captured,
        'browser_capture_exception_types':dict(sorted(runtime_errors.items())),
        'source_detail_visits':sum((row.get('v420_detail_audit') or {}).get('page_visits',0)
                                   or 0 for row in rows),
        'source_card_badge_candidate_counts':{k:source_counts[k] for k in TARGET_STATES},
        'selected_control_visits':len(controls),
        'actual_control_page_visits':sum(x['visited_control_count'] or 0 for x in bycontext),
        'sold_control_detail_audits':sum(x.get('source_card_state')=='SOLD' and
                                       x.get('status')=='AUDITED' for x in controls),
        'reserved_control_detail_audits':sum(x.get('source_card_state')=='RESERVED' and
                                       x.get('status')=='AUDITED' for x in controls),
        'control_ui_card_concordances':matched_ui,
        'control_ui_matches_with_generic_availability_only':metadata_broad,
        'exact_jsonld_availability_kind_counts':dict(sorted(availability_counts.items())),
        'explicit_conflict_count':disagreements,
        'comparison_counts':dict(sorted(statuses.items())),
        'both_control_classes_verified':(both_proven and disagreements==0
            and all_captured and canonical_complete),
        'per_class_primary_ui_proven':per_class_proven,
        'single_sitewide_render_policy_proven':False,
        'source_card_is_primary_ui_proof':False,
        'jsonld_instock_substituted_for_ui':False,
        'old_strict_filter_gate_overridden':False,
        'strict_listing_approved_count':0,
        'source_canonical_consumer':source_coverage,
        'v425_canonical_consumer':canonical_summary,
        'v425_per_class_primary_ui_proven':per_class_proven,
        'v425_both_control_classes_ui_proven':(
            all(per_class_proven.values()) and
            canonical_summary['status']=='CANONICAL_COVERAGE_COMPLETE' and source_complete),
        'contexts':bycontext}


def report(doc):
    e=doc['evaluation']
    lines=['# v4.23 public sold/reserved listing status controls','',
        f"- Bounded study: **{e['status']}**",
        f"- Original source detail pages: {e['source_detail_visits']}",
        f"- Control public detail visits: {e['actual_control_page_visits']}",
        f"- Eligible public card badge counts (not distinct listings): {e['source_card_badge_candidate_counts']}",
        f"- SOLD control detail audits: {e['sold_control_detail_audits']}",
        f"- RESERVED control detail audits: {e['reserved_control_detail_audits']}",
        f"- Card-to-target-UI corroborations: {e['control_ui_card_concordances']}",
        f"- UI matches with only generic JSON-LD availability: {e['control_ui_matches_with_generic_availability_only']}",
        f"- Exact availability enum counts: {e['exact_jsonld_availability_kind_counts']}",
        f"- Explicit conflicts: {e['explicit_conflict_count']}",
        '- A public related-card badge is only a hypothesis about the linked item.',
        '- OutOfStock is generic unavailability, NOT proof of a completed sale. the v4.26 model keeps both exact stock values distinct.',
        '- An explicitly RESERVED primary UI with OutOfStock JSON-LD is an observed UI match plus non-specific unavailability, not an exact RESERVED JSON-LD witness.',
        '- An unavailable sold control page is NOT confirmation of a completed trade.',
        '- No full marketplace/UI policy or original filter gate approval is claimed.',
        '- Strict listing approved count: 0.',
        '', '| Context | Source pages | Eligible controls | Visited controls | Result |',
        '|---|---:|---:|---:|---|']
    for row in e['contexts']:
        lines.append('| '+' | '.join(map(str,[
            row['context'],row['source_detail_count'],
            row['selected_control_count'],row['visited_control_count'],
            row['control_discovery']]))+' |')
    lines+=['','## Limits','',
        '- Selected controls originate only from exact CSS-rendered SOLD/RESERVED badges within actual public linked listing cards on previously robots-approved source pages.',
        '- A control is then checked against its own robots rules, HTTP status, exact public URL identity, primary visible UI state and matching Product JSON-LD.',
        '- Revisit four bounded phases within the same document to distinguish delayed, scrolled or mobile-only status UI; no clicks, login or bypass.',
        '- If SOLD is not seen among candidate cards, it stays an unfilled control class. RESERVED cannot substitute for it.',
        '- Only bounded enums and counts are persisted, not public item links, slugs, IDs, seller names, HTML or cookies.',
        '- All findings remain independent research, without admitting any listing.','']
    return '\n'.join(lines)


async def run(options):
    options.filter_recheck_v15=True
    options.detail_probe_v420=True
    options.sale_sources_v421=True
    options.controls_v423=True
    options.state_model_v424=True
    options.dom_diagnosis_v422=(getattr(options,'for_sale_diagnosis_v428',False) is True)
    options.filter_dom_v16=False
    options.filter_activation_v161=False
    salt=secrets.token_bytes(32)
    rows=[]
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=not options.headed)
            try:
                for name,region in [('cheonan_a','cheonan'),
                                    ('asan_control','asan'),('cheonan_b','cheonan')]:
                    row=await full.capture(browser,name,region,options,salt)
                    rows.append(row)
                    d=row.get('v420_detail_audit') or {}
                    c=d.get('v423_controls') or {}
                    print('v4.23',name,'Route',row.get('route_count'),
                          'source',d.get('page_visits'),'control',c.get('status'),
                          'visits',c.get('visited_control_count'))
                    if row.get('status','').startswith('STOP_') or row.get('access_blocked'):
                        break
                    if (d.get('status','').startswith('STOP_') or
                        c.get('status','').startswith('STOP_')):break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as exc:
        rows.append({'context':'browser','status':'STOP_'+type(exc).__name__,
                     'route_correlated':False})
    evaluation=aggregate(rows)
    obj={'version':'4.23',
        'consumer_schema_version':'4.26','canonical_state_schema_version':'4.24',
        'utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'design':{'context_count':3,'source_visits_max':9,
                  'control_visits_max':MAX_EXTRA_DETAIL_VISITS,
                  'source_badges':['SOLD','RESERVED'],
                  'source_link_and_target_identity_checked':True,
                  'robots_exact_targets_required':True,
                  'original_strict_listing_gate_changed':False},
        'evaluation':evaluation,
        'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    options.output_dir.mkdir(parents=True,exist_ok=True)
    (options.output_dir/'v423_public_controls_results.json').write_text(
        json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (options.output_dir/'v423_public_controls_report.md').write_text(
        report(obj),encoding='utf-8')
    (options.output_dir/'v423_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if evaluation['bounded_capture_complete'] and evaluation['status'] not in (
            'STOP_ACCESS_RESTRICTION','PUBLIC_CONTROL_WITNESSES_CONFLICT') else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v423_output'))
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--headed',action='store_true')
    opts=p.parse_args()
    opts.timeout=max(15,min(45,opts.timeout))
    opts.settle_ms=max(800,min(3500,opts.settle_ms))
    opts.output_dir=opts.output_dir.resolve()
    return asyncio.run(run(opts))


if __name__=='__main__':
    raise SystemExit(main())
