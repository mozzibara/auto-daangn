# -*- coding: utf-8 -*-
"""Read-only v4.7 price-ladder experiment. No automatic listing export.

Compare frontend price cap changes and actual route-response article prices across
independent, counterbalanced browser contexts. The experiment is observational:
even differentiated server-rendered responses do not disclose the backend's
internal query execution. The conservative v4.4.1 gates remain in effect.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import daangn_v4_1_core as core
import daangn_browser_v4_4_1 as prior
import daangn_browser_v4_6 as v46
import daangn_v4_5_evidence as ev

ROOT=Path(__file__).resolve().parent
CAPS=(20000,50000,100000)
CONTEXTS=(('target_a','target',(20000,50000,100000)),
          ('control_a','control',(50000,)),
          ('target_b','target',(100000,50000,20000)),
          ('control_b','control',(50000,)))


def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')


def aggregate_articles(model, maximum):
    """Return non-identifying price distribution from observed article rows.

    Counts cover only articles with normalized public listing URLs; if item price
    is absent this is *unknown*, not a pass. No article URL is written to JSON.
    """
    rows=[a for a in (model or {}).get('articles',[]) if isinstance(a,dict) and
          core.normalized_listing(a.get('href'))]
    vals=[ev.int_price(a.get('price')) for a in rows]
    known=[p for p in vals if p is not None]
    return {'rows':len(rows),'priced':len(known),'unknown':len(rows)-len(known),
            'price_min':min(known) if known else None,
            'price_max':max(known) if known else None,
            'price_median':statistics.median(known) if known else None,
            'price_above_bound':sum(p>maximum for p in known),
            'bins':{'0_to_20000':sum(p<=20000 for p in known),
                    '20001_to_50000':sum(20000<p<=50000 for p in known),
                    '50001_to_100000':sum(50000<p<=100000 for p in known),
                    'above_100000':sum(p>100000 for p in known)},
            'category_id_missing':sum(x.get('categoryId') is None for x in rows),
            'sale_status_missing':sum(x.get('isSoldOut') is None for x in rows)}


def ctx_args(args,maximum):
    d=vars(args).copy();d['max_price']=maximum
    return SimpleNamespace(**d)


def matched_route_event(event, maximum, region):
    """Admit only search-route responses to the exact requested price profile."""
    p=(event.get('public_request') or {}).get('public_params',{})
    if not p:return False
    return (p.get('price')==f'__{maximum}' and p.get('q')=='HDD'
            and p.get('category_id')=='1' and p.get('only_on_sale')=='true'
            and p.get('in')==region['slug'])


async def capture_apply(page,args,name,region,maximum):
    """Use actual UI; collect actual route loader, not stale bootstrap data."""
    a=ctx_args(args,maximum)
    steps=[];net=v46.Network();page.on('response',net.hook)
    try:
        button,selected=await v46.set_filter(page,a,steps)
        steps.append('CLICK_APPLY');await button.click(timeout=6000)
        steps.append('SETTLE_APPLIED_RESULTS');await page.wait_for_timeout(a.settle_ms)
        steps.append('READ_SEARCH_NETWORK_RESPONSES');await net.drain()
    finally:
        page.remove_listener('response',net.hook)
    steps.append('CAPTURE_APPLIED_RESULTS')
    dom,boot=await v46.snap(page);url=page.url
    state=await v46.check_after(page,a,steps)
    urlp=ev.public_url(url)
    documented=bool('price' in urlp.get('public_params',{}) and 200 in net.document_status)
    matched=[e for e in net.events if matched_route_event(e,maximum,a.regions[region])]
    m=matched[-1]['model'] if matched else boot if documented else None
    transport=bool(matched or documented)
    proof=ev.validated_predicates(m,url,a.regions[region]['id'],
        v46.ui_ok(selected,a) and v46.ui_ok(state,a),transport,
        ui_observation_status=state.get('observation_status'),
        expected=v46.expected_for(a),require_response_filters=True)
    stage=v46.stage(a,name,region,3,dom,m,url,200,proof,
                    'spa_route' if net.events else 'document')
    stage['id']=f'v47_filtered:{name}:{maximum}:apply'
    stage['price_profile']=aggregate_articles(m,maximum)
    stage['network_route_fetches']=len(matched)
    stage['route_response_digests']=[x['digest'] for x in matched[-2:]]
    stage['unmatched_route_responses']=len(net.events)-len(matched)
    stage['ui_recheck']={'status':state.get('observation_status'),
                         'failure_reason':state.get('failure_reason')}
    return stage,{'selected':selected,'after':state,'filter_steps':steps,
                  'network_blocked':net.blocked}


async def capture_repeat(page,args,name,region,maximum,expected_url):
    a=ctx_args(args,maximum)
    response=await page.goto(expected_url,wait_until='domcontentloaded',timeout=a.timeout*1000)
    await page.wait_for_timeout(a.settle_ms)
    dom,m=await v46.snap(page)
    state=await v46.check_after(page,a)
    proof=ev.validated_predicates(m,page.url,a.regions[region]['id'],v46.ui_ok(state,a),
        bool(response and response.status==200),
        ui_observation_status=state.get('observation_status'),
        expected=v46.expected_for(a),require_response_filters=True)
    st=v46.stage(a,name,region,4,dom,m,page.url,response.status if response else None,proof)
    st['id']=f'v47_filtered:{name}:{maximum}:repeat'
    st['price_profile']=aggregate_articles(m,maximum)
    st['ui_recheck']={'status':state.get('observation_status'),
                      'failure_reason':state.get('failure_reason')}
    keys=('q','in','category_id','only_on_sale','price')
    left=ev.public_url(expected_url).get('public_params',{})
    right=ev.public_url(page.url).get('public_params',{})
    st['url_persistence']=('PERSISTED_IN_URL' if all(k in left and right.get(k)==left[k] for k in keys)
                            else 'URL_STATE_CHANGED')
    return st


async def context(browser,args,name,region,cap_order):
    ctx=await browser.new_context(locale='ko-KR',viewport={'width':1280,'height':850})
    page=await ctx.new_page();page.set_default_timeout(args.timeout*1000)
    out={'context':name,'region':region,'order':list(cap_order),'status':'INCOMPLETE',
         'baseline':[],'levels':[],'error':None,'phase':None}
    try:
        # Baselines remain independent for v4.4.1 cold-document collision checks.
        for i in (1,2):
            out['phase']='BASELINE_'+str(i)
            st=await v46.document(page,args,name,region,i)
            out['baseline'].append(st)
            if not st['core_valid']:raise RuntimeError('BASELINE_NOT_VALID')
            await asyncio.sleep(args.pause_ms/1000)
        for cap in cap_order:
            out['phase']=f'RESET_FOR_{cap}'
            base_url=core.search_url(args.keyword,args.regions[region])
            resp=await page.goto(base_url,wait_until='domcontentloaded',timeout=args.timeout*1000)
            if not resp or resp.status!=200:raise RuntimeError('BASELINE_RESET_FAILED')
            await page.wait_for_timeout(args.settle_ms)
            await asyncio.sleep(args.pause_ms/1000)
            out['phase']=f'APPLY_{cap}'
            applied,ui=await capture_apply(page,args,name,region,cap)
            if ui['network_blocked']:raise RuntimeError('ACCESS_RESTRICTION')
            await asyncio.sleep(args.pause_ms/1000)
            out['phase']=f'REPEAT_{cap}'
            repeated=await capture_repeat(page,args,name,region,cap,page.url)
            out['levels'].append({'maximum':cap,'apply':applied,'repeat':repeated,
                                  'selected_ui':ui['selected'],'after_ui':ui['after'],
                                  'steps':ui['filter_steps']})
            if not applied['core_valid'] or not repeated['core_valid']:
                raise RuntimeError('FILTERED_DOCUMENT_INVALID')
            if (applied['filter_evidence'] or {}).get('status','').startswith('QUARANTINED') or \
               (repeated['filter_evidence'] or {}).get('status','').startswith('QUARANTINED'):
                raise RuntimeError('EXPLICIT_FILTER_VIOLATION')
            await asyncio.sleep(args.pause_ms/1000)
        out['status']='CAPTURED_ALL_LEVELS'
    except Exception as exc:
        out['status']='STOP_'+type(exc).__name__
        out['error']=str(exc)[:120] if isinstance(exc,RuntimeError) else type(exc).__name__
    finally:
        await ctx.close()
    return out


def pair_data(a,b):
    left=a.get('_urls',[]);right=b.get('_urls',[])
    return ev.compare(left,right) if left and right else None


def evaluate(plans,reference,*,complete):
    """Pre-registered criteria; observed association != proof of backend internals."""
    target=[p for p in plans if p['region']=='target']
    control=[p for p in plans if p['region']=='control']
    by_context={p['context']:{x['maximum']:x for x in p['levels']} for p in plans}
    per_cap={};all_levels=[]
    for cap in CAPS:
        levels=[by_context.get(k,{}).get(cap) for k in ('target_a','target_b')]
        if any(x is None for x in levels):
            per_cap[str(cap)]={'complete':False,'reason':'INDEPENDENT_SAMPLE_MISSING'}
            continue
        observed=[]
        for context_name,lv in zip(('target_a','target_b'),levels):
            a=lv['apply'];b=lv['repeat'];ap=a['price_profile'];rp=b['price_profile']
            query=(a.get('url') or {}).get('price_query_evidence') or {}
            filt=a.get('response_filter_fields') or {}
            same=pair_data(a,b)
            obs={'context':context_name,'apply_count':a['count'],'repeat_count':b['count'],
                 'apply_profile':ap,'repeat_profile':rp,'within_jaccard':same['jaccard'] if same else None,
                 'url_price':query.get('safe_value'),'price_url_matches':bool(query.get('unique') and
                      query.get('observed_max_price_krw')==cap),
                 'category_server':str(filt.get('categoryId'))=='1',
                 'available_server':filt.get('onlyOnSale') is True,
                 'server_price_metadata':bool(a.get('filter_evidence',{}).get('criteria',{}).get('max_price',{}).get('server_metadata_confirmed')),
                 'route_response_observed':a.get('network_route_fetches',0)>0,
                 'url_persistence':b.get('url_persistence'),
                 'ui_after':a.get('ui_recheck',{}).get('status'),
                 'hard_filter_violation':bool(ap['price_above_bound'] or rp['price_above_bound'])}
            observed.append(obs);all_levels.append((cap,a,b,obs))
        comparison=pair_data(levels[0]['repeat'],levels[1]['repeat'])
        per_cap[str(cap)]={'complete':True,'samples':observed,
                           'independent_repeat_jaccard':comparison['jaccard'] if comparison else None,
                           'observed_url_cap_in_both':all(x['price_url_matches'] for x in observed),
                           'server_filter_fields_in_both':all(x['category_server'] and x['available_server'] for x in observed)}
    cross={}
    for ctxname in ('target_a','target_b'):
        levels=by_context.get(ctxname,{})
        if all(n in levels for n in CAPS):
            cross[ctxname]={f'{a}_to_{b}':pair_data(levels[a]['repeat'],levels[b]['repeat'])
                            for a,b in ((20000,50000),(50000,100000),(20000,100000))}
    base=[s for p in plans for s in p['baseline']]
    at50=[]
    for p in plans:
        lv=by_context.get(p['context'],{}).get(50000)
        if lv:
            for step,label in ((lv['apply'],1),(lv['repeat'],2)):
                cp=dict(step);cp['id']=f'v46_filtered:{p["context"]}:{label}:{p["region"]}'
                cp['step']=label;cp['phase']='cold_first' if label==1 else 'same_url_repeat'
                at50.append(cp)
    known=prior.historical_collision_signatures(reference)
    checked=bool(complete and len(base)==8 and len(at50)==8)
    base_gate=ev.gate_run(base,'v47_base',known,'CAPTURED_COMPLETE' if checked else 'STOP_INCOMPLETE',
                          region_ids={'target':core.BY_KEY['cheonan']['id'],'control':core.BY_KEY['asan']['id']},keyword='HDD')
    filtered_gate=ev.gate_run(at50,'v47_50000',known,'CAPTURED_COMPLETE' if checked else 'STOP_INCOMPLETE',
                          region_ids={'target':core.BY_KEY['cheonan']['id'],'control':core.BY_KEY['asan']['id']},keyword='HDD')
    all_url_ok=bool(len(all_levels)==6 and all(o['price_url_matches'] and
                         o['url_persistence']=='PERSISTED_IN_URL' for _,_,_,o in all_levels))
    all_route=bool(len(all_levels)==6 and all(o['route_response_observed'] for _,_,_,o in all_levels))
    all_priced=bool(len(all_levels)==6 and all(o['apply_profile']['rows']>0 and
                         o['apply_profile']['unknown']==0 and o['repeat_profile']['unknown']==0 for _,_,_,o in all_levels))
    no_violation=bool(len(all_levels)==6 and not any(o['hard_filter_violation'] for _,_,_,o in all_levels))
    repeat_stable=bool(len(all_levels)==6 and all(o['within_jaccard'] is not None and
                        o['within_jaccard']>=.98 for _,_,_,o in all_levels))
    independent_stable=all(per_cap[str(cap)].get('independent_repeat_jaccard',0) is not None and
                           per_cap[str(cap)].get('independent_repeat_jaccard',0)>=.98 for cap in CAPS)
    band20_50=all(by_context.get(n,{}).get(50000,{}).get('repeat',{}).get('price_profile',{}).get('bins',{}).get('20001_to_50000',0)>0
                   for n in ('target_a','target_b'))
    band50_100=all(by_context.get(n,{}).get(100000,{}).get('repeat',{}).get('price_profile',{}).get('bins',{}).get('50001_to_100000',0)>0
                   for n in ('target_a','target_b'))
    gate_non_collision=bool(checked and not base_gate['run_level']['blocked'] and
                             not filtered_gate['run_level']['blocked'])
    route_comparison_possible=bool(checked and all_url_ok and all_route and all_priced and
                                  no_violation and repeat_stable and independent_stable and gate_non_collision)
    actual_effect=bool(route_comparison_possible and band20_50 and band50_100)
    any_hard_bad=bool(any(o['hard_filter_violation'] for _,_,_,o in all_levels))
    status=('STOP_INCOMPLETE' if not checked else
            'QUARANTINED_PRICE_VIOLATION' if any_hard_bad else
            'OBSERVED_PRICE_SENSITIVE_ROUTE_RESPONSES' if actual_effect else
            'OBSERVED_NO_SUFFICIENT_PRICE_SEPARATION' if route_comparison_possible else
            'UNVERIFIED_COMPARATIVE_EVIDENCE')
    return {'status':status,'capture_complete':checked,'price_ladder_caps':list(CAPS),
            'comparative_route_effect_observed':actual_effect,
            'backend_enforcement_proven':False,'approved_for_listing_export':False,
            'server_price_metadata_all_caps':bool(len(all_levels)==6 and all(o['server_price_metadata'] for _,_,_,o in all_levels)),
            'checks':{'url_caps_and_persistence':all_url_ok,'route_fetch_models':all_route,
                      'priced_article_coverage':all_priced,'zero_explicit_price_violations':no_violation,
                      'repeat_stability_ge_098':repeat_stable,'independent_stability_ge_098':independent_stable,
                      'baseline_and_50k_region_gate':gate_non_collision,
                      '50k_has_items_20001_to_50000':band20_50,
                      '100k_has_items_50001_to_100000':band50_100},
            'per_cap':per_cap,'cross_cap_sets':cross,
            'baseline_gate':base_gate,'filtered_50000_gate':filtered_gate}


def report(data):
    eva=data['evaluation'];lines=['# Daangn v4.7 price ceiling comparative experiment','',
    '- Fixed: Cheonan (Buldang-dong), HDD, category 1 digital devices, only on sale; Asan comparison for regional collision gate.',
    '- UI cap order counterbalanced: target A 20k→50k→100k; target B 100k→50k→20k.',
    '- No listing URLs or private browser state are exported. Observed response association is not proof of backend query implementation.',
    f"- Status: **{eva['status']}**. Capture complete: `{eva['capture_complete']}`. Comparative response effect: `{eva['comparative_route_effect_observed']}`.",
    f"- Backend enforcement proven: **{eva['backend_enforcement_proven']}**. Listing export approved: **{eva['approved_for_listing_export']}**.",
    '', '## Price-cap observations','',
    '| Max | Context | UI-generated price | Route response | Items | Priced | Unknown | > cap | 0–20k | 20–50k | 50–100k | Repeat Jaccard | Independent Jaccard |',
    '|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c in CAPS:
        row=eva['per_cap'].get(str(c),{})
        for o in row.get('samples',[]):
            pr=o['repeat_profile'];bins=pr['bins']
            lines.append(f"| {c:,} | {o['context']} | `{o['url_price']}` | {o['route_response_observed']} | {pr['rows']} | {pr['priced']} | {pr['unknown']} | {pr['price_above_bound']} | {bins['0_to_20000']} | {bins['20001_to_50000']} | {bins['50001_to_100000']} | {o['within_jaccard']} | {row.get('independent_repeat_jaccard')} |")
    lines+=['','## Evidence gates','']
    for k,v in eva['checks'].items():lines.append(f'- `{k}`: `{v}`')
    lines+=['','## Interpretation','',
       '- A route-fetch response with a changed article-price distribution under UI-generated cap changes supports an observed price-sensitive **response effect**, not necessarily the implementation details of server-side filtering.',
       '- Missing price metadata in currentFilters means strict server-enforcement approval remains withheld.',
       '- List sizes can increase under narrower filters because ranking/candidate limits differ; exact set inclusion is not assumed.',
       '- No relative-price assumptions are made when price is absent; unknown prices invalidate the complete-coverage gate.',
       '- Same-region repeat and independent context similarity as well as v4.4.1 cross-region initial-list quarantine remain mandatory.',
       '- Access limitations, site rules, or failure to capture route responses stop the experiment; no bypass or scraping escalation.','']
    return '\n'.join(lines)


def publish(outdir,plans,evaluation):
    def safe_stage(s):return {k:v for k,v in s.items() if not k.startswith('_')}
    clean_plans=[]
    for p in plans:
        clean_plans.append({k:([safe_stage(s) for s in v] if k=='baseline' else
                         [{**{k2:v2 for k2,v2 in level.items() if k2 not in ('apply','repeat')},
                           'apply':safe_stage(level['apply']),'repeat':safe_stage(level['repeat'])}
                          for level in v] if k=='levels' else v)
             for k,v in p.items()})
    data={'version':'4.7','timestamp_utc':now(),
          'design':{'target':'cheonan','control':'asan','keyword':'HDD',
                    'category_id':1,'available_only':True,'caps':list(CAPS),
                    'counterbalanced':True,'independent_target_contexts':2},
          'run_level':{'status':evaluation['status'],'blocked':True,
                       'accepted_count':0,'comparative_response_effect':evaluation['comparative_route_effect_observed']},
          'plans':clean_plans,'evaluation':evaluation,'private_credentials_stored':False}
    outdir.mkdir(parents=True,exist_ok=True)
    (outdir/'daangn_price_ladder_v4_7_results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (outdir/'daangn_price_ladder_v4_7_report.md').write_text(report(data),encoding='utf-8')
    (outdir/'daangn_price_ladder_v4_7_limited_accept.json').write_text(json.dumps({'version':'4.7','run_level_blocked':True,'samples':[],'allowed_sample_count':0},indent=2)+'\n',encoding='utf-8')
    print('v4.7 experiment:',evaluation['status'],'effect:',evaluation['comparative_route_effect_observed'],
          'backend proven:',False,'accepted:',0)
    return 0 if evaluation['capture_complete'] and not evaluation['status'].startswith('QUARANTINED_') else 2


async def run(args):
    history=prior.evidence_reference(args.reference)
    robots=core.public_robots_check('HDD')
    if not robots.get('allowed'):
        result=evaluate([],history,complete=False)
        result['status']='STOP_ROBOTS_NOT_ALLOWED'
        return publish(args.output_dir,[],result)
    try:from playwright.async_api import async_playwright
    except ImportError:
        result=evaluate([],history,complete=False);result['status']='STOP_PLAYWRIGHT_MISSING'
        return publish(args.output_dir,[],result)
    plans=[]
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=not args.headed)
            try:
                for index,(name,region,caps) in enumerate(CONTEXTS):
                    plan=await context(browser,args,name,region,caps)
                    plans.append(plan)
                    print('context:',name,plan['status'],'cap counts:',[(x['maximum'],x['repeat']['count']) for x in plan['levels']])
                    if plan['status']!='CAPTURED_ALL_LEVELS':break
                    if index<len(CONTEXTS)-1:await asyncio.sleep(args.pause_ms/1000)
            finally:await browser.close()
    except Exception as exc:
        plans.append({'context':'browser','region':'unknown','order':[],'status':'STOP_BROWSER',
                      'baseline':[],'levels':[],'error':type(exc).__name__,'phase':'BROWSER'})
    completed=(len(plans)==4 and all(p['status']=='CAPTURED_ALL_LEVELS' for p in plans) and
               len([s for p in plans for s in p['baseline']])==8 and
               sum(len(p['levels']) for p in plans)==8)
    assessment=evaluate(plans,history,complete=completed)
    return publish(args.output_dir,plans,assessment)


def main():
    p=argparse.ArgumentParser(description='v4.7 approved read-only bounded price ladder (Cheonan HDD)')
    p.add_argument('--output-dir',type=Path,default=Path('v47_output'))
    p.add_argument('--reference',type=Path,default=ROOT/'evidence/reference_runs.json')
    p.add_argument('--headed',action='store_true')
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--pause-ms',type=int,default=2000)
    args=p.parse_args()
    args.regions={'target':dict(core.BY_KEY['cheonan']),'control':dict(core.BY_KEY['asan'])}
    args.keyword='HDD';args.category_id=1;args.category_name=v46.CATALOG[1]
    args.available_only=True;args.min_price=0;args.max_price=50000
    args.timeout=max(15,min(45,args.timeout));args.settle_ms=max(800,min(4000,args.settle_ms))
    args.pause_ms=max(1000,min(8000,args.pause_ms));args.output_dir=args.output_dir.resolve()
    return asyncio.run(run(args))

if __name__=='__main__':raise SystemExit(main())
