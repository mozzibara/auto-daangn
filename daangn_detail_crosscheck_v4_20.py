# -*- coding: utf-8 -*-
"""v4.20: independent public listing-detail verification of Route item attributes.

Read a deliberately small rank-stratified sample from the *already matched*
real public search Route. Navigate only to public, normalized Daangn listing
links, after exact-target robots permission. Never claim all 270 items verified.
Detail evidence is read-only, privacy-limited and non-authorizing: no matching
sample bypasses the historical response filter proof or individual listing gate.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime,timezone
import hmac
import hashlib
import json
from pathlib import Path
import secrets
from types import SimpleNamespace
from urllib.parse import urlsplit
import urllib.request
import urllib.robotparser

import daangn_v4_1_core as core
import daangn_v4_5_evidence as evidence
import daangn_browser_v4_6 as v46
import daangn_full_route_v4_14 as full
import daangn_render_gap_v4_12 as render
import daangn_v4_4_gate as old_gate
from daangn_state_consumers_v4_25 import consume

SAMPLE_RANKS_TARGET=(0,32,'HALFWAY')
SAMPLES_PER_CONTEXT=3
MAX_DETAIL_VISITS=9
ROBOTS_UA='DaangnRegionDiagnostic/4.1'

# Only selected, finite-value provenance from actual primary item UI is retained.
DETAIL_JS=r"""expected => {
 const clamp=(n,max=100)=>Number.isInteger(n)?Math.max(0,Math.min(max,n)):0;
 const visible=e=>{
   if(!e?.getBoundingClientRect)return false;
   const b=e.getBoundingClientRect(),s=getComputedStyle(e);
   return b.width>0&&b.height>0&&e.getClientRects().length>0&&
     s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0';
 };
 const clean=s=>String(s||'').replace(/\s+/g,' ').trim().slice(0,150);
 const own=document.querySelector('main article')||document.querySelector('main');
 const result={
   primary_item_present:!!own,
   primary_heading_visible:!!own&&[...own.querySelectorAll('h1')].filter(visible).length>0,
   primary_heading_count:own?clamp([...own.querySelectorAll('h1')].filter(visible).length):0,
   category:{verdict:'NOT_OBSERVABLE',source:'NONE',candidate_count:0},
   sale:{verdict:'NOT_OBSERVABLE',source:'NONE',candidate_count:0},
   primary_category_link_count:0,
   primary_status_marker_count:0,
   structured_product_count:0,
   og_category_present:false
 };
 if(!own)return result;
 // Link in a breadcrumb or category-specific semantic locator is eligible;
 // generic occurrences of category text in recommendation cards are not.
 const insideRec=e=>!!e.closest('[data-testid*="recommend"],[class*="recommend"],[aria-label*="추천"]');
 const categoryNodes=[...own.querySelectorAll(
   '[data-testid*="category"],[aria-label*="category"],'+
   'nav[aria-label*="breadcrumb"] a,nav[aria-label*="경로"] a,'+
   '[aria-label*="breadcrumb"] a,ol[aria-label*="breadcrumb"] a,'+
   'a[href*="category_id="],a[href*="/category/"]'
 )].filter(e=>visible(e)&&!insideRec(e));
 result.primary_category_link_count=clamp(categoryNodes.length);
 const cats=categoryNodes.map(e=>clean(e.getAttribute('aria-label')||e.innerText));
 const otherCategories=['생활가전','디지털기기','가구/인테리어','생활/주방','여성의류',
   '남성패션/잡화','뷰티/미용','스포츠/레저','취미/게임/음반','도서','유아동','반려동물용품'];
 const claims=[];
 for(const text of cats){
   if(text===expected.category)claims.push({type:'MATCH',source:'PRIMARY_SEMANTIC_CATEGORY'});
   else if(otherCategories.includes(text))claims.push({type:'MISMATCH',source:'PRIMARY_SEMANTIC_CATEGORY'});
 }
 // Metadata applies to the current canonical article, not the listing feed.
 for(const m of document.querySelectorAll('meta[property="article:section"],meta[property="product:category"]')){
    const text=clean(m.getAttribute('content'));
    if(text===expected.category)claims.push({type:'MATCH',source:'PAGE_META_CATEGORY'});
    else if(otherCategories.includes(text))claims.push({type:'MISMATCH',source:'PAGE_META_CATEGORY'});
    result.og_category_present=true;
 }
 const statusCandidates=[...own.querySelectorAll(
   '[data-testid*="status"],[data-testid*="sale-state"],[role="status"],'+
   '[aria-label*="판매완료"],[aria-label*="거래완료"],[aria-label*="판매중"],'+
   '[class*="status"],[class*="Status"]'
 )].filter(e=>visible(e)&&!insideRec(e));
 result.primary_status_marker_count=clamp(statusCandidates.length);
 const saleClaims=[];
 const soldRe=/^(?:판매완료|거래완료|거래 완료|판매 완료)$/;
 const sellingRe=/^(?:판매중|판매 중|판매하기)$/;
 const reservedRe=/^(?:예약중|예약 중)$/;
 for(const e of statusCandidates){
   const t=clean(e.getAttribute('aria-label')||e.innerText);
   if(soldRe.test(t))saleClaims.push({type:'SOLD',source:'PRIMARY_STATUS_MARKER'});
   else if(sellingRe.test(t))saleClaims.push({type:'AVAILABLE',source:'PRIMARY_STATUS_MARKER'});
   else if(reservedRe.test(t))saleClaims.push({type:'RESERVED',source:'PRIMARY_STATUS_MARKER'});
 }
 // Structured product status only when an exact URL relates the schema to
 // this listing, not to a recommended product or a surrounding collection.
 const canon=window.location.origin+window.location.pathname.replace(/\/?$/,'/');
 const sameUrl=s=>{
    if(typeof s!=='string'||s.length>2048)return false;
    try{const u=new URL(s,window.location.href);
        return u.origin===window.location.origin&&
            u.pathname.replace(/\/?$/,'/')===window.location.pathname.replace(/\/?$/,'/');}
    catch{return false;}
 };
 const scripts=[...document.querySelectorAll('script[type="application/ld+json"]')].slice(0,7);
 const products=[];
 const walk=(o,depth=0)=>{
   if(!o||depth>4||products.length>12)return;
   if(Array.isArray(o)){o.slice(0,12).forEach(x=>walk(x,depth+1));return;}
   if(typeof o!=='object')return;
   const typ=Array.isArray(o['@type'])?o['@type']:typeof o['@type']==='string'?[o['@type']]:[];
   if(typ.some(t=>String(t).split('/').pop()==='Product')){
     const src=o.url||o.mainEntityOfPage;
     const addr=typeof src==='string'?src:src&&typeof src==='object'?src['@id']:null;
     if(sameUrl(addr))products.push(o);
   }
   if(o['@graph'])walk(o['@graph'],depth+1);
 };
 for(const s of scripts){
   if((s.textContent||'').length>30000)continue;
   try{walk(JSON.parse(s.textContent||'null'));}catch{}
 }
 result.structured_product_count=clamp(products.length);
 if(products.length===1){
   const p=products[0];
   const cat=typeof p.category==='string'?clean(p.category):null;
   if(cat===expected.category)claims.push({type:'MATCH',source:'MATCHED_PRODUCT_JSONLD'});
   else if(cat&&otherCategories.includes(cat))
     claims.push({type:'MISMATCH',source:'MATCHED_PRODUCT_JSONLD'});

 }
 const categoryTypes=[...new Set(claims.map(x=>x.type))];
 const saleTypes=[...new Set(saleClaims.map(x=>x.type))];
 result.category.candidate_count=clamp(claims.length);
 if(categoryTypes.length===1){
   result.category.verdict=categoryTypes[0];
   result.category.source=claims[0].source;
 }else if(categoryTypes.length>1)result.category.verdict='AMBIGUOUS';
 result.sale.candidate_count=clamp(saleClaims.length);
 if(saleTypes.length===1){
   result.sale.verdict=saleTypes[0];
   result.sale.source=saleClaims[0].source;
 }else if(saleTypes.length>1)result.sale.verdict='AMBIGUOUS';
 return result;
}""".strip()

ALLOWED_CAT={'MATCH','MISMATCH','AMBIGUOUS','NOT_OBSERVABLE'}
ALLOWED_SALE={'AVAILABLE','SOLD','RESERVED','AMBIGUOUS','NOT_OBSERVABLE'}
ALLOWED_SOURCE={'NONE','PRIMARY_SEMANTIC_CATEGORY','PAGE_META_CATEGORY',
                'MATCHED_PRODUCT_JSONLD','PRIMARY_STATUS_MARKER'}


def sanitize_probe(data):
    """Only finite enums/bounded counts, no raw title, page path or seller data."""
    if not isinstance(data,dict):
        return {'status':'ERROR_UNSUPPORTED_PROBE'}
    def count(val):
        return val if type(val) is int and 0<=val<=100 else None
    def read(key,allowed):
        o=data.get(key) if isinstance(data.get(key),dict) else {}
        return {
            'verdict':o.get('verdict') if o.get('verdict') in allowed else 'NOT_OBSERVABLE',
            'source':o.get('source') if o.get('source') in ALLOWED_SOURCE else 'NONE',
            'candidate_count':count(o.get('candidate_count'))}
    return {'status':'OBSERVED',
            'primary_item_present':data.get('primary_item_present') is True,
            'primary_heading_visible':data.get('primary_heading_visible') is True,
            'primary_heading_count':count(data.get('primary_heading_count')),
            'category':read('category',ALLOWED_CAT),
            'sale':read('sale',ALLOWED_SALE),
            'primary_category_link_count':count(data.get('primary_category_link_count')),
            'primary_status_marker_count':count(data.get('primary_status_marker_count')),
            'structured_product_count':count(data.get('structured_product_count')),
            'og_category_present':data.get('og_category_present') is True}


def pick_samples(model,salt,limit=SAMPLES_PER_CONTEXT):
    """Choose one actual Route listing near ranks 0, 32, and halfway.

    No direct searches, guessed endpoints, or listing URL are persisted.
    Only rows with both item predicates missing are chosen.
    """
    articles=(model or {}).get('articles') or []
    if not isinstance(articles,list) or not articles:return []
    starts=[0,32,len(articles)//2]
    ends=[min(32,len(articles)),min(len(articles)//2,len(articles)),
          len(articles)]
    out=[]
    seen=set()
    for begin,end in zip(starts[:limit],ends[:limit]):
        if end<=begin:continue
        for index in range(begin,end):
            row=articles[index]
            if not isinstance(row,dict) or row.get('categoryId') is not None or row.get('isSoldOut') is not None:
                continue
            price=evidence.int_price(row.get('price'))
            if price is None or price<0 or price>50000:continue
            link=core.normalized_listing(row.get('href'))
            stable=old_gate.stable_article_id(link) if link else None
            if not link or not stable or stable in seen:continue
            seen.add(stable)
            # In-memory token helps detect accidental duplicate rows, never exported.
            tok=hmac.new(salt,stable.encode('ascii'),hashlib.sha256).hexdigest()[:20]
            # The class came from the exact same correlated search Route row.
            # It is a finite enum, never an address or seller region string.
            from app_v5.listing_locality import sanitize_item_locality
            out.append({'rank':index,'url':link,'token':tok,'price':price,
                        'item_locality_status':sanitize_item_locality(
                            row.get('item_locality_status'))})
            break
    return out


def robots_check_detail(urls,*,getter=None,user_agent=None):
    """Verify robots.txt for EXACT public listing URLs before any navigation."""
    if not urls or len(urls)>SAMPLES_PER_CONTEXT:return {'allowed':False,'reason':'BAD_SAMPLE_SET','count':len(urls)}
    for u in urls:
        if core.normalized_listing(u)!=u:
            return {'allowed':False,'reason':'NOT_PUBLIC_NORMALIZED_LISTING','count':len(urls)}
    getter=getter or urllib.request.urlopen
    try:
        req=urllib.request.Request(core.BASE+'/robots.txt',
                                   headers={'User-Agent':ROBOTS_UA})
        with getter(req,timeout=20) as response:
            if response.status!=200:
                return {'allowed':False,'reason':'ROBOTS_NOT_200','count':len(urls)}
            raw=response.read(400001)
        if len(raw)>400000:
            return {'allowed':False,'reason':'ROBOTS_OVERSIZE','count':len(urls)}
        parser=urllib.robotparser.RobotFileParser()
        parser.parse(raw.decode('utf-8','replace').splitlines())
        agents=[ROBOTS_UA]
        if isinstance(user_agent,str) and user_agent.strip():
            agents.append(user_agent)
        allowed=all(parser.can_fetch(agent,u) for agent in agents for u in urls)
        return {'allowed':allowed,'reason':'ALLOWED' if allowed else 'ROBOTS_DENIED',
                'count':len(urls),'checked_exact_detail_urls':True}
    except Exception as ex:
        return {'allowed':False,'reason':'ROBOTS_ERROR_'+type(ex).__name__,
                'count':len(urls)}


async def probe_page(page):
    try:
        raw=await asyncio.wait_for(page.evaluate(DETAIL_JS,{'category':'디지털기기'}),timeout=7)
        return sanitize_probe(raw)
    except Exception as ex:
        return {'status':'ERROR_'+type(ex).__name__}


def classify_detail(probe,identity_ok,canonical_record=None):
    """v4.26: only validated independent UI transaction may prove sale state."""
    if not identity_ok:return 'IDENTITY_MISMATCH'
    if not isinstance(probe,dict) or probe.get('status')!='OBSERVED' or not (
        probe.get('primary_item_present') and probe.get('primary_heading_visible')):
        return 'DETAIL_NOT_OBSERVABLE'
    cat=(probe.get('category') or {}).get('verdict')
    if cat=='MISMATCH':return 'CATEGORY_CONTRADICTION'
    view=consume(canonical_record,'SOURCE')
    if not view['schema_valid']:return 'DETAIL_CANONICAL_NOT_VERIFIED'
    if cat=='AMBIGUOUS' or view['status']=='CANONICAL_QUARANTINED':
        return 'DETAIL_AMBIGUOUS'
    if not view['primary_ui_proven']:
        return 'CATEGORY_ONLY' if cat=='MATCH' else 'DETAIL_FIELDS_NOT_OBSERVABLE'
    txn=view['primary_transaction_status']
    if txn in ('SOLD','RESERVED'):return 'NOT_AVAILABLE'
    if cat=='MATCH' and txn=='FOR_SALE':
        return 'ITEM_UI_PREDICATES_CORROBORATED'
    if txn=='FOR_SALE':return 'SALE_ONLY'
    return 'DETAIL_FIELDS_NOT_OBSERVABLE'


async def audit_sample(page,model,name,region,options,salt,ui_diag,*,checker=robots_check_detail):
    """One controlled, serial batch after Route and UI filter recheck."""
    report={'status':'NOT_STARTED','context':name,'region':region,
            'route_total':len((model or {}).get('articles') or []),
            'sample_plan':'rank_stratified_0_32_midpoint',
            'selected_sample_count':0,'page_visits':0,
            'detail_robots':{'allowed':False,'reason':'NOT_CHECKED'},
            'ui_filter_verified_before_details':ui_diag.get('stable_selection_verified') is True,
            'stop_access':False,'samples':[],'strict_listing_approved_count':0}
    if not report['ui_filter_verified_before_details']:
        report['status']='STOP_UI_FILTER_NOT_VERIFIED'
        return report
    selected=pick_samples(model,salt)
    report['selected_sample_count']=len(selected)
    if not selected or len(selected)>SAMPLES_PER_CONTEXT:
        report['status']='STOP_NO_VALID_PUBLIC_ROUTE_SAMPLE'
        return report
    user_agent=await page.evaluate('()=>navigator.userAgent')
    robot=await asyncio.to_thread(checker,[s['url'] for s in selected],
                                   user_agent=user_agent)
    report['detail_robots']=robot
    if robot.get('allowed') is not True:
        report['status']='STOP_DETAIL_ROBOTS_'+str(robot.get('reason','UNKNOWN'))
        return report
    # v4.23 cards are held only in process memory until exact robots gates.
    v423_candidate_pool=[]
    for sample in selected:
        entry={'source_rank':sample['rank'],'beyond_32_dom':sample['rank']>=32,
               'page_status':'NOT_VISITED','same_listing_identity':False,
               'category':{'verdict':'NOT_OBSERVABLE','source':'NONE','candidate_count':0},
               'sale':{'verdict':'NOT_OBSERVABLE','source':'NONE','candidate_count':0},
               'detail_verdict':'NOT_OBSERVABLE'}
        report['samples'].append(entry)
        try:
            resp=await page.goto(sample['url'],wait_until='domcontentloaded',
                                  timeout=options.timeout*1000)
            report['page_visits']+=1
            if resp is None:
                entry['page_status']='NO_HTTP_RESPONSE'
                continue
            if resp.status in core.BLOCK_STATUS:
                entry['page_status']='ACCESS_RESTRICTED'
                report['stop_access']=True
                break
            if resp.status==404:
                entry['page_status']='NOT_FOUND'
                continue
            if resp.status!=200:
                entry['page_status']='HTTP_OTHER'
                continue
            await page.wait_for_timeout(options.settle_ms)
            restricted=await render.snapshot(page)
            if restricted.get('restricted'):
                entry['page_status']='ACCESS_RESTRICTED'
                report['stop_access']=True
                break
            identity=core.normalized_listing(page.url)==sample['url']
            entry['same_listing_identity']=identity
            if not identity:
                entry['page_status']='DETAIL_REDIRECTED_OR_WRONG_IDENTITY'
                entry['detail_verdict']='IDENTITY_MISMATCH'
                continue
            entry['page_status']='HTTP_200_IDENTITY_MATCH'
            # v4.32: retain only bounded numeric Route price for the
            # exact listing successfully opened from the matched Route.
            # Never export its URL, title, stable ID or ephemeral token.
            entry['v432_route_price_krw']=sample['price']
            entry['v432_route_price_item_identity']=True
            entry['v435_route_item_locality_status']=sample['item_locality_status']
            # v4.33: keyed same-run article identity, never a raw URL or stable ID.
            # One ephemeral salt covers all three contexts of this capture.
            entry['v433_listing_run_hmac']=sample['token']
            observed=await probe_page(page)
            if observed.get('status')=='OBSERVED':
                entry['category']=observed['category']
                entry['sale']=observed['sale']
                entry['evidence_counts']={
                    'heading':observed.get('primary_heading_count'),
                    'category_candidate':observed.get('primary_category_link_count'),
                    'sale_candidate':observed.get('primary_status_marker_count'),
                    'structured_product':observed.get('structured_product_count')}
            # Extract the canonical record on every valid detail observation,
            # independently of which study is running.
            from daangn_sale_sources_v4_21 import probe_sources
            from daangn_state_controls_v4_23 import probe_exact_availability
            from daangn_listing_state_v4_24 import build_record, clean_record
            separated=await probe_sources(page)
            exact=await probe_exact_availability(page)
            primary=(separated.get('ui') or {})
            record=build_record(
                [primary.get('state','NOT_OBSERVABLE')], exact.get('kind'),
                identity_confirmed=identity,
                render_complete=(separated.get('status')=='OBSERVED'
                    and separated.get('valid_primary') is True),
                same_product=(exact.get('status')=='OBSERVED'
                    and exact.get('matched_product_count')==1),
                context='SOURCE', ui_origin=primary.get('source','NONE'))
            entry['v424_state_model']=clean_record(record)
            entry['v420_heading_visible']=observed.get('primary_heading_visible') is True
            entry['detail_verdict']=classify_detail(observed,identity,entry['v424_state_model'])
            if getattr(options,'sale_sources_v421',False):
                from daangn_sale_sources_v4_21 import compare_sources
                entry['v421_sale_sources']=separated
                entry['v421_sale_comparison']=compare_sources(
                    separated,identity,entry['v424_state_model'])
                if getattr(options,'dom_diagnosis_v422',False):
                    from daangn_status_dom_v4_22 import examine
                    # No extra navigation; inspect the same robots-approved,
                    # exact-identity public detail document in four phases.
                    entry['v422_dom_diagnostic']=await examine(
                        page,separated,options.settle_ms)
                    if core.normalized_listing(page.url)!=sample['url']:
                        entry['v422_dom_diagnostic']['status']='IDENTITY_CHANGED'
                    if (await render.snapshot(page)).get('restricted'):
                        report['stop_access']=True
                        break
                if getattr(options,'for_sale_diagnosis_v428',False):
                    # Same document, without an extra page visit or any clicks.
                    from daangn_for_sale_ui_v4_28 import probe as v428_probe
                    if core.normalized_listing(page.url)!=sample['url']:
                        entry['v428_for_sale_probe']={'status':'PRIMARY_NOT_VERIFIED'}
                    elif (await render.snapshot(page)).get('restricted'):
                        report['stop_access']=True
                        break
                    else:
                        entry['v428_for_sale_probe']=await v428_probe(page)
                if getattr(options,'status_signals_v429',False):
                    # Already visited, exact-identity page; no new requests.
                    from daangn_status_signals_v4_29 import probe as v429_probe
                    if core.normalized_listing(page.url)!=sample['url']:
                        entry['v429_status_signal_survey']={'status':'PRIMARY_NOT_VERIFIED'}
                    elif (await render.snapshot(page)).get('restricted'):
                        report['stop_access']=True
                        break
                    else:
                        entry['v429_status_signal_survey']=await v429_probe(page)
                # Title and URL exist only in volatile process memory
                # during explicitly requested local or encrypted collection.
                # Do not persist either in public research JSON or runner logs.
                local_sink=getattr(options,'v432_local_link_sink',None)
                if (isinstance(local_sink,list) and
                    name in ('cheonan_a','cheonan_b') and
                    entry.get('page_status')=='HTTP_200_IDENTITY_MATCH'):
                    from daangn_secure_links_v4_34 import capture_primary_title
                    title=await capture_primary_title(page,sample['url'])
                    local_sink.append({
                        'context':name,'source_rank':sample['rank'],
                        'price_krw':sample['price'],'url':sample['url'],
                        'listing_run_hmac':sample['token'],
                        'title':title.get('title'),
                        'title_status':title.get('status')})
                if getattr(options,'controls_v423',False):
                    from daangn_state_controls_v4_23 import collect_cards
                    stats,candidates=await collect_cards(page,sample['url'])
                    entry['v423_card_stats']=stats
                    for c in candidates:
                        v423_candidate_pool.append({
                            'url':c['url'],'source_card_state':c['source_card_state'],
                            'source_rank':sample['rank']})
        except Exception as ex:
            entry['page_status']='ERROR_'+type(ex).__name__
        if report['stop_access']:break
        await asyncio.sleep(1.5)
    if getattr(options,'controls_v423',False) and not report['stop_access']:
        from daangn_state_controls_v4_23 import audit_controls
        # At most two NEW exact public detail visits per context; unrelated
        # linked-card badges cannot be treated as primary item witnesses.
        report['v423_controls']=await audit_controls(
            page,v423_candidate_pool,options)
        if report['v423_controls'].get('stop_access'):
            report['stop_access']=True
    report['status']='STOP_ACCESS_RESTRICTION' if report['stop_access'] else (
        'DETAIL_SAMPLE_AUDITED' if report['page_visits']==len(selected)
        else 'DETAIL_SAMPLE_INCOMPLETE')
    return report


def aggregate(rows):
    """Never interpret a verified *sample* as proof of all Route rows."""
    statuses=Counter()
    details=[]
    canonical_valid_count=0
    for row in rows:
        d=row.get('v420_detail_audit') or {}
        details.append(d)
        for s in d.get('samples') or []:
            canonical_valid_count+=int(consume(s.get('v424_state_model'),'SOURCE')['schema_valid'])
            statuses[classify_detail(
                {'status':'OBSERVED',
                 'primary_item_present':s.get('page_status')=='HTTP_200_IDENTITY_MATCH',
                 'primary_heading_visible':s.get('v420_heading_visible') is True,
                 'category':s.get('category')},
                s.get('same_listing_identity') is True,
                s.get('v424_state_model'))]+=1
    complete=len(rows)==3 and canonical_valid_count==MAX_DETAIL_VISITS and all(
        row.get('route_correlated') is True and
        (row.get('v420_detail_audit') or {}).get('status')=='DETAIL_SAMPLE_AUDITED'
        and (row.get('v420_detail_audit') or {}).get('selected_sample_count')==SAMPLES_PER_CONTEXT
        and (row.get('v420_detail_audit') or {}).get('page_visits')==SAMPLES_PER_CONTEXT
        for row in rows)
    blocked=any((d or {}).get('stop_access') for d in details)
    total=sum(statuses.values())
    verified=statuses['ITEM_UI_PREDICATES_CORROBORATED']
    contradictory=sum(statuses[x] for x in ('CATEGORY_CONTRADICTION','NOT_AVAILABLE','IDENTITY_MISMATCH'))
    if blocked:verdict='STOP_ACCESS_RESTRICTION'
    elif not complete:verdict='INCONCLUSIVE_DETAIL_SAMPLE_INCOMPLETE'
    elif contradictory:verdict='DETAIL_SAMPLE_CONTRADICTIONS_OBSERVED'
    elif verified==total and total==MAX_DETAIL_VISITS:
        verdict='ALL_SAMPLED_ITEM_UI_FIELDS_CORROBORATED'
    else:verdict='DETAIL_SAMPLE_PARTIAL_OR_UNOBSERVABLE'
    return {
        'status':verdict,'capture_complete':complete,
        'canonical_valid_records':canonical_valid_count,
        'sampled_rows':total,'sample_both_fields_verified':verified,
        'sample_contradictions':contradictory,
        'sample_unobserved_or_partial':total-verified-contradictory,
        'per_item_verdict_counts':dict(sorted(statuses.items())),
        'public_detail_robots_allowed_all':all(
            (d.get('detail_robots') or {}).get('allowed') is True for d in details)
            if len(details)==3 else False,
        'every_route_listing_verified':False,
        'route_total_inventory_verified':False,
        'historical_filter_applied_verified_overridden':False,
        'independent_behavioral_tier_overridden':False,
        'strict_listing_approved_count':0}


def report_results(doc):
    s=doc['evaluation']
    lines=['# v4.20 — independent public detail item-attribute sample','',
       f"- Verdict: **{s['status']}**",
       f"- Full bounded experiment complete: {s['capture_complete']}",
       f"- Sample count: {s['sampled_rows']}",
       f"- Both item attributes independently corroborated: {s['sample_both_fields_verified']}",
       f"- Explicit contradictions: {s['sample_contradictions']}",
       f"- Partial or not observable: {s['sample_unobserved_or_partial']}",
       '- No conclusion extends from sampled items to all Route items.',
       '- Original strict filter gate / historical listing approval: unchanged, 0 approved.',
       '', '| Context | Route rows | Sampled | Inspected detail pages | Status |',
       '|---|---:|---:|---:|---|']
    for row in doc['contexts']:
        d=row.get('detail') or {}
        lines.append('| '+' | '.join(map(str,[row.get('context'),row.get('route_count'),
            d.get('selected_sample_count'),d.get('page_visits'),d.get('status')]))+' |')
    lines+=['','## Limits','',
       '- Category evidence is restricted to primary item semantic category labels or matched product metadata, not recommendation text.',
       '- Available/sold/reserved requires explicit primary status metadata; absence of a SOLD flag in the Route is not a positive sale status.',
       '- A HTTP 404, unavailable detail, login wall or robots restriction is NOT interpreted as sold or completed.',
       '- No raw URLs, seller profiles, item names, listing IDs, cookies, HTML or screenshots are stored.',
       '- A partial or contradictory detail observation is quarantined, not repaired from filter URL or the Route search membership.','']
    return '\n'.join(lines)


async def run(options):
    options.filter_recheck_v15=True
    options.detail_probe_v420=True
    options.filter_dom_v16=False
    options.filter_activation_v161=False
    salt=secrets.token_bytes(32)
    rows=[]
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=not options.headed)
            try:
                for name,region in [('cheonan_a','cheonan'),('asan_control','asan'),
                                    ('cheonan_b','cheonan')]:
                    row=await full.capture(browser,name,region,options,salt)
                    rows.append(row)
                    d=row.get('v420_detail_audit') or {}
                    print('v4.20',name,'Route',row.get('route_count'),
                          'detail',d.get('status'),'samples',d.get('page_visits'))
                    if row.get('status','').startswith('STOP_') or row.get('access_blocked'):
                        break
                    if d.get('status','').startswith('STOP_'):
                        break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as ex:
        rows.append({'context':'browser','status':'STOP_'+type(ex).__name__,
                     'route_correlated':False})
    evaluation=aggregate(rows)
    doc={'version':'4.20',
        'consumer_schema_version':'4.26','canonical_state_schema_version':'4.24','timestamp_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
         'design':{'category_id':1,'available_only':True,'max_price_krw':50000,
                   'rank_stratified_sample_size_per_context':SAMPLES_PER_CONTEXT,
                   'target_region_repeated':2,'regional_control_repeated':1,
                   'all_route_rows_not_verified':True,
                   'read_only_public_detail_and_exact_robots':True},
         'evaluation':evaluation,
         'contexts':[{'context':row.get('context'),
             'region':row.get('region'),
             'route_count':row.get('route_count'),
             'source_route_correlated':row.get('route_correlated') is True,
             'filter_proof_status':row.get('filter_proof_status'),
             'detail':row.get('v420_detail_audit') or {},
             'candidate_gate':False} for row in rows],
         'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    options.output_dir.mkdir(parents=True,exist_ok=True)
    (options.output_dir/'v420_detail_crosscheck_results.json').write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (options.output_dir/'v420_detail_crosscheck_report.md').write_text(
        report_results(doc),encoding='utf-8')
    (options.output_dir/'v420_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if evaluation['capture_complete'] and not evaluation['sample_contradictions'] else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v420_output'))
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--headed',action='store_true')
    options=p.parse_args()
    options.output_dir=options.output_dir.resolve()
    options.timeout=max(15,min(45,options.timeout))
    options.settle_ms=max(800,min(3500,options.settle_ms))
    return asyncio.run(run(options))


if __name__=='__main__':
    raise SystemExit(main())
