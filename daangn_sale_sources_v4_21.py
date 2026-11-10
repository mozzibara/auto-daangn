# -*- coding: utf-8 -*-
"""v4.21: independently compare primary visible sale-state UI vs same-item JSON-LD.

As of v4.26, neither this module nor v4.20 converts Product JSON-LD
availability into marketplace sale state. Only a validated independent
canonical record can establish a positive primary UI transaction witness. No URLs, item IDs, titles, seller
data, raw text, cookies, JSON-LD or HTML are exported.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import secrets

import daangn_detail_crosscheck_v4_20 as detail
import daangn_listing_state_v4_24 as state
import daangn_full_route_v4_14 as full
from daangn_state_consumers_v4_25 import consume, source_comparison, summarize

SALE_STATE=frozenset({'AVAILABLE','SOLD','RESERVED','AMBIGUOUS','NOT_OBSERVABLE'})
SOURCES=frozenset({'NONE','PRIMARY_STATUS_MARKER','PRIMARY_EXACT_VISIBLE_LEAF',
                    'MATCHED_PRODUCT_JSONLD'})
MAX_SAMPLED=9

SOURCES_JS=r"""() => {
  const clamp=(n,max=100)=>Number.isInteger(n)?Math.max(0,Math.min(max,n)):0;
  const visible=e=>{
    if(!e?.getBoundingClientRect)return false;
    const b=e.getBoundingClientRect(),s=getComputedStyle(e);
    return b.width>0&&b.height>0&&e.getClientRects().length>0&&
      s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0';
  };
  const clean=t=>String(t||'').replace(/\s+/g,' ').trim().slice(0,80);
  const primary=document.querySelector('main article')||document.querySelector('main');
  const heading=primary?[...primary.querySelectorAll('h1')].filter(visible):[];
  const result={
    valid_primary:!!primary&&visible(primary)&&heading.length===1,
    primary_heading_count:clamp(heading.length),
    ui:{state:'NOT_OBSERVABLE',source:'NONE',candidates:0,
        semantic_candidates:0,visible_leaf_candidates:0},
    jsonld:{kind:'NOT_OBSERVABLE',source:'NONE',candidates:0,
            matching_product_count:0}
  };
  if(!result.valid_primary)return result;
  const excluded=el=>!!el.closest(
    'aside,footer,nav,form,[data-testid*="recommend"],[class*="recommend"],'+
    '[aria-label*="추천"],[data-testid*="related"],[class*="related"],'+
    '[aria-label*="관련 상품"],[class*="comment"],[data-testid*="comment"]'
  );
  const sale=t=>{
    const x=clean(t);
    if(/^(판매중|판매 중)$/.test(x))return 'AVAILABLE';
    if(/^(거래완료|거래 완료|판매완료|판매 완료)$/.test(x))return 'SOLD';
    if(/^(예약중|예약 중)$/.test(x))return 'RESERVED';
    return null;
  };
  const claims=[];
  const possible=[...primary.querySelectorAll(
    '[role="status"],[data-testid*="status"],[data-testid*="sale-state"],'+
    '[class*="status"],[class*="Status"],[aria-label],span,p,b,strong,em,small,div'
  )].slice(0,1200);
  for(const el of possible){
    if(!visible(el)||excluded(el)||el.closest('a[href*="/kr/buy-sell/"]'))continue;
    const aria=clean(el.getAttribute('aria-label'));
    const direct=[...el.childNodes].filter(n=>n.nodeType===3)
      .map(n=>n.textContent||'').join(' ');
    const val=sale(aria)||sale(direct);
    if(!val)continue;
    const semantic=!!(el.getAttribute('role')==='status'||
      el.hasAttribute('aria-label')||/status|sale-state/i.test(
       el.getAttribute('data-testid')||'')||
      /status/i.test(typeof el.className==='string'?el.className:''));
    claims.push({state:val,source:semantic?'PRIMARY_STATUS_MARKER':
      'PRIMARY_EXACT_VISIBLE_LEAF'});
  }
  const uiSet=[...new Set(claims.map(x=>x.state))];
  result.ui.candidates=clamp(claims.length);
  result.ui.semantic_candidates=clamp(claims.filter(x=>x.source==='PRIMARY_STATUS_MARKER').length);
  result.ui.visible_leaf_candidates=clamp(claims.filter(x=>x.source==='PRIMARY_EXACT_VISIBLE_LEAF').length);
  if(uiSet.length>1)result.ui.state='AMBIGUOUS';
  else if(uiSet.length===1){
    result.ui.state=uiSet[0];
    result.ui.source=claims.some(x=>x.source==='PRIMARY_STATUS_MARKER')?
      'PRIMARY_STATUS_MARKER':'PRIMARY_EXACT_VISIBLE_LEAF';
  }
  const sameListingUrl=s=>{
    if(typeof s!=='string'||s.length>2048)return false;
    try{
      const u=new URL(s,window.location.href);
      return u.origin===window.location.origin&&
        u.pathname.replace(/\/?$/,'/')===window.location.pathname.replace(/\/?$/,'/');
    }catch{return false;}
  };
  const matched=[];
  const walk=(node,depth=0)=>{
    if(!node||depth>5||matched.length>12)return;
    if(Array.isArray(node)){for(const x of node.slice(0,15))walk(x,depth+1);return;}
    if(typeof node!=='object')return;
    const types=Array.isArray(node['@type'])?node['@type']:[node['@type']];
    if(types.some(t=>typeof t==='string'&&t.split('/').pop()==='Product')){
      const x=node.url||node.mainEntityOfPage;
      const ref=typeof x==='string'?x:x&&typeof x==='object'?x['@id']:null;
      if(sameListingUrl(ref))matched.push(node);
    }
    if(node['@graph'])walk(node['@graph'],depth+1);
  };
  for(const script of [...document.querySelectorAll('script[type="application/ld+json"]')].slice(0,8)){
    const data=script.textContent||'';
    if(data.length>30000)continue;
    try{walk(JSON.parse(data));}catch{}
  }
  result.jsonld.matching_product_count=clamp(matched.length);
  const values=[];
  for(const product of matched){
    let offers=product.offers;
    if(Array.isArray(offers))offers=offers.length===1?offers[0]:null;
    if(!offers||typeof offers!=='object')continue;
    const a=String(offers.availability||'').split('/').pop();
    const kinds={InStock:'IN_STOCK',OutOfStock:'OUT_OF_STOCK',
      SoldOut:'SOLD_OUT',PreOrder:'PRE_ORDER',PreSale:'PRE_SALE'};
    if(kinds[a])values.push(kinds[a]);
    else if(typeof offers.availability==='string')values.push('OTHER');
  }
  result.jsonld.candidates=clamp(values.length);
  if(matched.length>1||new Set(values).size>1){
    result.jsonld.kind='AMBIGUOUS';
  }else if(matched.length===1&&values.length===1){
    result.jsonld.kind=values[0];
    result.jsonld.source='MATCHED_PRODUCT_JSONLD';
  }
  return result;
}""".strip()


def sanitize(raw):
    """Discard everything except audited enums and bounded counts."""
    if not isinstance(raw,dict):return {'status':'INVALID_PROBE'}
    def bound(v):
        return v if type(v) is int and 0<=v<=100 else None
    def source(name):
        val=raw.get(name) if isinstance(raw.get(name),dict) else {}
        def allowed(key,enums,default):
            found=val.get(key)
            return found if isinstance(found,str) and found in enums else default
        if name=='ui':
            return {'state':allowed('state',SALE_STATE,'NOT_OBSERVABLE'),
                    'source':allowed('source',SOURCES,'NONE'),
                    'candidates':bound(val.get('candidates')),
                    'semantic_candidates':bound(val.get('semantic_candidates')),
                    'visible_leaf_candidates':bound(val.get('visible_leaf_candidates'))}
        return {'kind':allowed('kind',state.AVAILABILITY_KINDS,'NOT_OBSERVABLE'),
                'source':val.get('source') if val.get('source') == 'MATCHED_PRODUCT_JSONLD'
                    else 'NONE',
                'candidates':bound(val.get('candidates')),
                'matching_product_count':bound(val.get('matching_product_count'))}
    return {'status':'OBSERVED',
            'valid_primary':raw.get('valid_primary') is True,
            'primary_heading_count':bound(raw.get('primary_heading_count')),
            'ui':source('ui'),'jsonld':source('jsonld')}


async def probe_sources(page):
    try:
        raw=await asyncio.wait_for(page.evaluate(SOURCES_JS),timeout=7)
        return sanitize(raw)
    except Exception as ex:
        return {'status':'ERROR_'+type(ex).__name__}


def compare_sources(probe,identity_ok=True,canonical_record=None):
    """No v4.21 coarse sale mapping or fallback: compare canonical evidence only."""
    if not identity_ok:return 'IDENTITY_NOT_MATCHED'
    if not isinstance(probe,dict) or probe.get('status')!='OBSERVED' or not probe.get('valid_primary'):
        return 'SOURCES_NOT_OBSERVABLE'
    return source_comparison(canonical_record)


def aggregate(rows):
    """v4.26 complete source evaluation consumes only validated canonical records."""
    statuses=Counter()
    context_rows=[]
    canonical_views=[]
    for row in rows:
        d=row.get('v420_detail_audit') or {}
        observed=d.get('samples') or []
        counts=Counter()
        projected=[]
        for item in observed:
            record=item.get('v424_state_model')
            view=consume(record,'SOURCE')
            comp=source_comparison(record)
            canonical_views.append(view)
            counts[comp]+=1
            statuses[comp]+=1
            projected.append({'rank':item.get('source_rank'),
                'identity_confirmed':item.get('same_listing_identity') is True,
                'page_status':item.get('page_status'),
                'ui':(item.get('v421_sale_sources') or {}).get('ui'),
                'jsonld':(item.get('v421_sale_sources') or {}).get('jsonld'),
                'comparison':comp,'v425_consumer':view,'v425_comparison':comp})
        context_rows.append({
            'context':row.get('context'),
            'route_count':row.get('route_count'),
            'route_correlated':row.get('route_correlated') is True,
            'detail_status':d.get('status'),
            'selected_sample_count':d.get('selected_sample_count'),
            'page_visits':d.get('page_visits'),
            'status_counts':dict(sorted(counts.items())),
            'samples':projected})
    coverage=summarize(canonical_views,expected_count=MAX_SAMPLED)
    complete=len(rows)==3 and coverage['status']=='CANONICAL_COVERAGE_COMPLETE' and all(
        row.get('route_correlated') is True and
        (row.get('v420_detail_audit') or {}).get('status')=='DETAIL_SAMPLE_AUDITED' and
        (row.get('v420_detail_audit') or {}).get('page_visits')==3 and
        (row.get('v420_detail_audit') or {}).get('selected_sample_count')==3 and
        all(isinstance(item.get('v421_sale_sources'),dict) and
            item['v421_sale_sources'].get('status')=='OBSERVED' and
            item.get('same_listing_identity') is True
            for item in (row.get('v420_detail_audit') or {}).get('samples',[]))
        for row in rows)
    blocked=any((r.get('v420_detail_audit') or {}).get('stop_access') is True for r in rows)
    explicit_conflicts=statuses['CANONICAL_SEMANTIC_CONFLICT_QUARANTINED']
    compatible=statuses['CANONICAL_UI_AND_STOCK_COMPATIBLE']
    metadata_only=statuses['CANONICAL_METADATA_NOT_PRIMARY_UI_PROOF']
    if blocked:verdict='STOP_ACCESS_RESTRICTION'
    elif not complete:verdict='INCONCLUSIVE_CANONICAL_SAMPLE_INCOMPLETE'
    elif explicit_conflicts:verdict='CANONICAL_CONFLICTS_QUARANTINED'
    elif compatible==MAX_SAMPLED:verdict='CANONICAL_UI_STOCK_COMPATIBLE_ALL_SAMPLES'
    elif metadata_only==MAX_SAMPLED:verdict='CANONICAL_METADATA_ONLY_NO_PRIMARY_UI_PROOF'
    else:verdict='CANONICAL_PARTIAL_OR_UNOBSERVABLE'
    return {'status':verdict,'capture_complete':complete,
        'sampled_detail_visits':sum(statuses.values()),
        'independently_concordant_samples':compatible,
        'visible_ui_status_observed_samples':sum(v['schema_valid'] and
            v['primary_transaction_status'] in ('FOR_SALE','RESERVED','SOLD')
            for v in canonical_views),
        'non_quarantined_primary_ui_samples':coverage['primary_ui_proven_records'],
        'jsonld_only_samples':metadata_only,
        'explicit_ui_jsonld_conflicts':explicit_conflicts,
        'per_source_comparison_counts':dict(sorted(statuses.items())),
        'every_route_item_sale_status_verified':False,
        'jsonld_instock_is_visible_ui_evidence':False,
        'original_detail_sample_gate_overridden':False,
        'historical_filter_applied_verified_overridden':False,
        'strict_listing_approved_count':0,
        'v425_canonical_consumer':coverage,
        'context_results':context_rows}


def report(data):
    e=data['evaluation']
    lines=['# v4.26 — canonical primary UI transaction and exact stock evidence','',
      f"- Canonical source verdict: **{e['status']}**",
      f"- Complete bounded sample: {e['capture_complete']}",
      f"- Detail visits: {e['sampled_detail_visits']}",
      f"- Verified primary UI statuses: {e['visible_ui_status_observed_samples']}",
      f"- JSON-LD without independent primary UI: {e['jsonld_only_samples']}",
      f"- UI and stock compatible: {e['independently_concordant_samples']}",
      f"- Quarantined semantic conflicts: {e['explicit_ui_jsonld_conflicts']}",
      f"- Canonical coverage: {e['v425_canonical_consumer']['status']}",
      '- JSON-LD availability cannot prove FOR_SALE, RESERVED, or SOLD.',
      '- OutOfStock and SoldOut are distinct inventory values, not transaction states.',
      '- No sampled result bypasses the strict filter gate or approves listings.','']
    return '\n'.join(lines)


async def run(options):
    options.filter_recheck_v15=True
    options.detail_probe_v420=True
    options.sale_sources_v421=True
    options.state_model_v424=True
    options.filter_dom_v16=False
    options.filter_activation_v161=False
    salt=secrets.token_bytes(32)
    observations=[]
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=not options.headed)
            try:
                for name,region in [('cheonan_a','cheonan'),('asan_control','asan'),
                                     ('cheonan_b','cheonan')]:
                    row=await full.capture(browser,name,region,options,salt)
                    observations.append(row)
                    d=row.get('v420_detail_audit') or {}
                    print('v4.21',name,'Route',row.get('route_count'),
                          'detail',d.get('status'),
                          'sources',[(s.get('v421_sale_comparison','NOT_CAPTURED'))
                             for s in d.get('samples',[])])
                    if row.get('status','').startswith('STOP_') or row.get('access_blocked'):
                        break
                    if d.get('status','').startswith('STOP_'):
                        break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as ex:
        observations.append({'context':'browser','status':'STOP_'+type(ex).__name__,
                             'route_correlated':False})
    outcome=aggregate(observations)
    doc={'version':'4.21',
        'consumer_schema_version':'4.26','canonical_state_schema_version':'4.24','timestamp_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
         'experiment':{'category_id':1,'available_only':True,'max_price_krw':50000,
                       'regions':['cheonan_a','asan_control','cheonan_b'],
                       'planned_sample_visits':MAX_SAMPLED,
                       'exact_public_detail_robots_before_navigation':True,
                       'source_level_evidence_separated':True,
                       'whole_route_verification_claimed':False},
         'evaluation':outcome,
         'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    options.output_dir.mkdir(parents=True,exist_ok=True)
    (options.output_dir/'v421_sale_sources_results.json').write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (options.output_dir/'v421_sale_sources_report.md').write_text(
        report(doc),encoding='utf-8')
    (options.output_dir/'v421_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if outcome['capture_complete'] and not outcome['explicit_ui_jsonld_conflicts'] else 2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=Path('v421_output'))
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
