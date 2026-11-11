# -*- coding: utf-8 -*-
"""v4.8 bounded public search price-band cross-check (research only).

Compare maximum-only search results against two explicit price bands using
observed UI actions and route-correlated responses. Store per-run pseudonyms,
not public listing URLs, and never export verified shopping listings.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import daangn_v4_1_core as core
import daangn_browser_v4_4_1 as prior
import daangn_browser_v4_6 as v46
import daangn_price_ladder_v4_7 as v47
import daangn_v4_5_evidence as ev
import daangn_v4_4_gate as gate
from app_v5.region_proof import verified_region

ROOT=Path(__file__).resolve().parent
CAPS=v47.CAPS
PROFILES={
    'cap_20000':(0,20000),'cap_50000':(0,50000),
    'cap_100000':(0,100000),
    'band_20001_50000':(20001,50000),
    'band_50001_100000':(50001,100000),
}
RUNS=(('target_a','target',tuple(PROFILES)),
      ('control_a','control',('cap_50000',)),
      ('target_b','target',tuple(reversed(tuple(PROFILES)))),
      ('control_b','control',('cap_50000',)))


def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')


def profile_args(args,key):
    minimum,maximum=PROFILES[key]
    return SimpleNamespace(**{**vars(args),'min_price':minimum,'max_price':maximum})


def range_shape(value,minimum,maximum):
    """Interpret only observed numeric bounds; this is NOT server-enforcement proof.

    Max-only notation was established by v4.7 UI. For a lower bound, admit
    exactly the two numeric bounds with a double-underscore separator as a
    candidate; any other format remains unverified and is recorded as observed.
    """
    if minimum==0:return value==f'__{maximum}'
    m=re.fullmatch(r'([1-9][0-9]{0,8})__([1-9][0-9]{0,8})',value or '')
    return bool(m and (int(m.group(1)),int(m.group(2)))==(minimum,maximum))


def matched_route(event,key,region,*,allow_missing_region_url=False):
    minimum,maximum=PROFILES[key]
    request=(event.get('public_request') or {})
    p=request.get('public_params') or {}
    model=event.get('model') or {}
    region_ok=(p.get('in')==region['slug'] or
               (allow_missing_region_url and 'in' not in p and
                str(model.get('region_id'))==region['id'] and
                str(model.get('filter_region_id'))==region['id']))
    return bool(request.get('valid') and p.get('q')=='HDD' and
                region_ok and p.get('category_id')=='1' and
                p.get('only_on_sale')=='true' and
                request.get('price_query_evidence',{}).get('unique') is True and
                range_shape(p.get('price'),minimum,maximum))


def identity_rows(model,salt):
    """Same-run HMAC pseudonyms allow exact overlap without publishing URLs.

    The per-run salt is never exported; price values are public. Invalid listing
    URL/price => price unknown, not an implicitly passing price predicate.
    """
    rows={}
    for x in (model or {}).get('articles',[]):
        if not isinstance(x,dict):continue
        url=core.normalized_listing(x.get('href'))
        ident=gate.stable_article_id(url) if url else None
        if not ident:continue
        token=hmac.new(salt,ident.encode('ascii'),hashlib.sha256).hexdigest()[:24]
        price=ev.int_price(x.get('price'))
        if token in rows and rows[token]!=price:rows[token]=None
        else:rows[token]=price
    return rows


def bounded_stage(stage,model,salt,key,ui=None):
    minimum,maximum=PROFILES[key]
    stage['profile_key']=key
    stage['observed_items']=[{'token':k,'price':v} for k,v in sorted(identity_rows(model,salt).items())]
    stage['price_profile']=v47.aggregate_articles(model,maximum)
    stage['price_profile']['below_minimum']=sum(v is not None and v<minimum for v in identity_rows(model,salt).values())
    if ui is not None:
        stage['ui_recheck']={'status':ui.get('observation_status'),
                             'failure_reason':ui.get('failure_reason')}
    # No salt, cookies, request payloads or listing URLs are included.
    return stage


async def capture_apply(page,args,name,region,key,salt,*,picker_selected=False):
    a=profile_args(args,key)
    minimum,maximum=PROFILES[key]
    steps=[];net=v46.Network();page.on('response',net.hook)
    try:
        button,selected=await v46.set_filter(page,a,steps)
        steps.append('CLICK_APPLY');await button.click(timeout=6000)
        steps.append('SETTLE_APPLIED_RESULTS');await page.wait_for_timeout(a.settle_ms)
        steps.append('READ_SEARCH_NETWORK_RESPONSES');await net.drain()
    finally:page.remove_listener('response',net.hook)
    dom,boot=await v46.snap(page);observed_url=page.url
    ui=await v46.check_after(page,a,steps)
    parsed=ev.public_url(observed_url)
    matched=[x for x in net.events if matched_route(
        x,key,a.regions[region],allow_missing_region_url=picker_selected)]
    doc=bool(200 in net.document_status and parsed.get('valid'))
    # The picker-based path cannot use the navigation's stale boot loader.
    model=matched[-1]['model'] if matched else (
        boot if doc and not picker_selected else None)
    authority=None
    if picker_selected:
        # Only a unique fresh response observed after the actual Apply click
        # may corroborate the visible selected region. A click alone is not proof.
        ui_region=await core.observe_selected_region_control(
            page,a.regions[region])
        # picker_selected can only be set by v4.14 after a unique, visible
        # public UI suggestion was actually selected. No assumed URL region.
        ui_region['unique_option_clicked']=picker_selected is True
        authority=verified_region(
            a.regions[region],observed_url,
            matched[0] if len(matched)==1 else None,ui_region,
            picker_selected=True,keyword=a.keyword)
    proof=ev.validated_predicates(model,observed_url,a.regions[region]['id'],
        v46.ui_ok(selected,a) and v46.ui_ok(ui,a),bool(matched or doc),
        ui_observation_status=ui.get('observation_status'),
        expected=v46.expected_for(a),require_response_filters=True)
    stage=v46.stage(a,name,region,3,dom,model,observed_url,200,proof,
        'spa_route' if matched else 'document' if doc else 'unmatched_route',
        region_authority=authority)
    stage['region_authority_status']=(authority or {}).get(
        'status','LEGACY_REGION_URL_WITNESS')
    stage['region_authority']=authority
    stage['id']=f'v48_filtered:{name}:{key}:apply'
    stage['matched_route_count']=len(matched)
    stage['unmatched_route_count']=len(net.events)-len(matched)
    stage['price_url_shape_observed']=range_shape(parsed.get('public_params',{}).get('price'),minimum,maximum)
    stage['matched_route_digest']=[x['digest'] for x in matched[-1:]]
    # Keep non-sensitive diagnostics on a failed APPLY step. A mismatched
    # route must never be promoted, but hiding the actual observed query
    # prevents identifying whether the UI encoded a different range.
    stage['observed_route_queries']=[x['public_request'] for x in net.events[-3:]]
    stage['document_statuses']=net.document_status[-3:]
    stage['model_present']=bool(model)
    stage['loader_region_id']=(model or {}).get('region_id')
    stage['dom_visible_count']=len(dom.get('dom_visible',[]))
    stage['dom_validation']=bool(stage.get('dom_ok'))
    stage['region_validation']=bool(stage.get('region_ok'))
    stage['ui_selected']=v46.ui_ok(selected,a)
    bounded_stage(stage,model,salt,key,ui)
    return stage,net.blocked,steps


async def capture_repeat(page,args,name,region,key,url,salt):
    a=profile_args(args,key)
    minimum,maximum=PROFILES[key]
    response=await page.goto(url,wait_until='domcontentloaded',timeout=a.timeout*1000)
    await page.wait_for_timeout(a.settle_ms)
    dom,model=await v46.snap(page)
    ui=await v46.check_after(page,a)
    proof=ev.validated_predicates(model,page.url,a.regions[region]['id'],v46.ui_ok(ui,a),
        bool(response and response.status==200),ui_observation_status=ui.get('observation_status'),
        expected=v46.expected_for(a),require_response_filters=True)
    stage=v46.stage(a,name,region,4,dom,model,page.url,response.status if response else None,proof)
    stage['id']=f'v48_filtered:{name}:{key}:repeat'
    keys=('q','in','category_id','only_on_sale','price')
    expected=ev.public_url(url).get('public_params',{})
    actual=ev.public_url(page.url).get('public_params',{})
    stage['url_persistence']='PERSISTED_IN_URL' if all(k in expected and expected[k]==actual.get(k) for k in keys) else 'URL_STATE_CHANGED'
    stage['price_url_shape_observed']=range_shape(actual.get('price'),minimum,maximum)
    bounded_stage(stage,model,salt,key,ui)
    return stage


async def run_context(browser,args,name,region,order,salt):
    ctx=await browser.new_context(locale='ko-KR',viewport={'width':1280,'height':850})
    page=await ctx.new_page();page.set_default_timeout(args.timeout*1000)
    p={'context':name,'region':region,'order':list(order),'baseline':[],'profiles':[],
       'status':'INCOMPLETE','phase':None,'error':None}
    try:
        for i in (1,2):
            p['phase']=f'BASELINE_{i}'
            stage=await v46.document(page,args,name,region,i)
            p['baseline'].append(stage)
            if not stage['core_valid']:raise RuntimeError('BASELINE_NOT_VALID')
            await asyncio.sleep(args.pause_ms/1000)
        for key in order:
            p['phase']='RESET_'+key
            response=await page.goto(core.search_url(args.keyword,args.regions[region]),
                                     wait_until='domcontentloaded',timeout=args.timeout*1000)
            if response is None or response.status!=200:raise RuntimeError('BASELINE_RESET_FAILED')
            await page.wait_for_timeout(args.settle_ms)
            await asyncio.sleep(args.pause_ms/1000)
            p['phase']='APPLY_'+key
            applied,network_blocked,steps=await capture_apply(page,args,name,region,key,salt)
            if network_blocked:raise RuntimeError('ACCESS_RESTRICTION')
            # Do not silently use a stale boot loader if no route/document proof.
            if not applied['core_valid']:
                p['failure_observation']=applied
                raise RuntimeError('APPLY_INVALID')
            await asyncio.sleep(args.pause_ms/1000)
            p['phase']='REPEAT_'+key
            repeated=await capture_repeat(page,args,name,region,key,page.url,salt)
            p['profiles'].append({'key':key,'min':PROFILES[key][0],'max':PROFILES[key][1],
                                  'apply':applied,'repeat':repeated,'steps':steps})
            if not repeated['core_valid']:raise RuntimeError('REPEAT_INVALID')
            if any((x.get('filter_evidence') or {}).get('status','').startswith('QUARANTINED')
                   for x in (applied,repeated)):
                raise RuntimeError('EXPLICIT_FILTER_VIOLATION')
            await asyncio.sleep(args.pause_ms/1000)
        p['status']='CAPTURED_ALL_PROFILES'
    except Exception as exc:
        p['status']='STOP_'+type(exc).__name__
        p['error']=str(exc)[:140] if isinstance(exc,RuntimeError) else type(exc).__name__
    finally:await ctx.close()
    return p


def item_map(stage):
    return {r['token']:r['price'] for r in stage.get('observed_items',[])
            if isinstance(r,dict) and isinstance(r.get('token'),str) and len(r['token'])==24}


def set_comparison(a,b):
    left=set(a);right=set(b);both=left&right
    return {'left':len(left),'right':len(right),'common':len(both),
            'missing_in_right':len(left-right),'novel_in_right':len(right-left),
            'jaccard':round(len(both)/len(left|right),6) if left or right else None}


def analyze_context(profile_maps):
    """Exact set comparisons; 'missing' always means absent from observed response."""
    if not all(k in profile_maps for k in PROFILES):return {'complete':False}
    cap20=profile_maps['cap_20000'];cap50=profile_maps['cap_50000'];cap100=profile_maps['cap_100000']
    band50=profile_maps['band_20001_50000'];band100=profile_maps['band_50001_100000']
    union=set().union(*(set(m) for m in profile_maps.values()))
    cap_union=set(cap20)|set(cap50)|set(cap100)
    band_union=set(band50)|set(band100)
    by_band={
        '0_to_20000':set(k for m in profile_maps.values() for k,v in m.items() if v is not None and v<=20000),
        '20001_to_50000':set(k for m in profile_maps.values() for k,v in m.items() if v is not None and 20000<v<=50000),
        '50001_to_100000':set(k for m in profile_maps.values() for k,v in m.items() if v is not None and 50000<v<=100000),
    }
    # Same pseudonym with distinct visible price: possible listing update / inconsistency.
    price_sets={}
    for m in profile_maps.values():
        for tok,v in m.items():
            if v is not None:price_sets.setdefault(tok,set()).add(v)
    conflicts=sum(len(v)>1 for v in price_sets.values())
    caps_counts=[len(cap20),len(cap50),len(cap100)]
    near_plateau=bool(min(caps_counts)>=240 and max(caps_counts)-min(caps_counts)<=20)
    return {'complete':True,'counts':{k:len(v) for k,v in profile_maps.items()},
            'union_all':len(union),'union_caps_only':len(cap_union),
            'union_disjoint_price_bins':{k:len(v) for k,v in by_band.items()},
            'additional_from_explicit_bands':len(band_union-cap_union),
            'missing_from_100k_response':len(union-set(cap100)),
            'observed_100k_coverage_of_union':round(len(union&set(cap100))/len(union),6) if union else None,
            'observed_100k_coverage_of_caps_union':round(len(cap_union&set(cap100))/len(cap_union),6) if cap_union else None,
            'cap_20k_not_in_50k':len(set(cap20)-set(cap50)),
            'cap_20k_not_in_100k':len(set(cap20)-set(cap100)),
            'cap_50k_not_in_100k':len(set(cap50)-set(cap100)),
            'band_20001_50000_not_in_cap_50000':len(set(band50)-set(cap50)),
            'band_50001_100000_not_in_cap_100000':len(set(band100)-set(cap100)),
            'cross_queries':{
                'cap20_to_cap50':set_comparison(cap20,cap50),
                'cap50_to_cap100':set_comparison(cap50,cap100),
                'cap20_to_cap100':set_comparison(cap20,cap100),
                'band20_50_to_cap50':set_comparison(band50,cap50),
                'band50_100_to_cap100':set_comparison(band100,cap100)},
            'distinct_price_values_per_token_conflicts':conflicts,
            'near_equal_cap_response_count':near_plateau,
            'candidate_truncation_signature':bool(near_plateau and len(union-set(cap100))>0),
            'fixed_server_result_cap_proven':False,
            'full_inventory_recall_proven':False}


def validate_observation(plan,key):
    levels={x['key']:x for x in plan['profiles']}
    if key not in levels:return False
    entry=levels[key]
    minimum,maximum=PROFILES[key]
    apply=entry['apply'];repeat=entry['repeat']
    if not apply.get('core_valid') or not repeat.get('core_valid'):return False
    if not (apply.get('matched_route_count',0)>0 and apply.get('price_url_shape_observed') and
            repeat.get('price_url_shape_observed') and
            repeat.get('url_persistence')=='PERSISTED_IN_URL'):return False
    if (apply.get('response_filter_fields') or {}).get('categoryId') not in (1,'1'):return False
    if (apply.get('response_filter_fields') or {}).get('onlyOnSale') is not True:return False
    for stage in (apply,repeat):
        sample=item_map(stage)
        if not sample or len(sample)!=stage.get('count'):return False
        if any(v is None or v<minimum or v>maximum for v in sample.values()):return False
        if (stage.get('price_profile') or {}).get('unknown') or (stage.get('price_profile') or {}).get('price_above_bound') or (stage.get('price_profile') or {}).get('below_minimum'):return False
    if set_comparison(item_map(apply),item_map(repeat))['jaccard']<.98:return False
    return True


def as_v47_plans(plans):
    translated=[]
    for plan in plans:
        levels=[]
        for row in plan.get('profiles',[]):
            if row['key'].startswith('cap_'):
                levels.append({'maximum':row['max'],'apply':row['apply'],'repeat':row['repeat']})
        translated.append({'context':plan['context'],'region':plan['region'],
            'baseline':plan['baseline'],'levels':levels,'status':plan['status']})
    return translated


def evaluate(plans,history,*,complete):
    """Never upgrade server implementation evidence or shopping approvals."""
    expected_keys=set(PROFILES)
    indexes={p['context']:p for p in plans}
    full=bool(complete and set(indexes)=={'target_a','target_b','control_a','control_b'} and
       all(p['status']=='CAPTURED_ALL_PROFILES' for p in plans) and
       all({x['key'] for x in indexes[n]['profiles']}==expected_keys for n in ('target_a','target_b')) and
       all({x['key'] for x in indexes[n]['profiles']}=={'cap_50000'} for n in ('control_a','control_b')))
    v47e=v47.evaluate(as_v47_plans(plans),history,complete=full)
    contexts={};validations={}
    for name in ('target_a','target_b'):
        p=indexes.get(name)
        if not p:continue
        validations[name]={k:validate_observation(p,k) for k in PROFILES}
        maps={x['key']:item_map(x['repeat']) for x in p['profiles']}
        contexts[name]=analyze_context(maps)
    all_valid=bool(full and len(validations)==2 and all(all(x.values()) for x in validations.values()))
    hard_bad=any(any(any(r.get('price_profile',{}).get(key,0)>0 for key in ('price_above_bound','below_minimum'))
              for r in (x['apply'],x['repeat'])) for p in plans for x in p.get('profiles',[]))
    cross_context={}
    if all_valid:
        ta={x['key']:item_map(x['repeat']) for x in indexes['target_a']['profiles']}
        tb={x['key']:item_map(x['repeat']) for x in indexes['target_b']['profiles']}
        cross_context={k:set_comparison(ta[k],tb[k]) for k in PROFILES}
        all_valid=all(x['jaccard'] is not None and x['jaccard']>=.98 for x in cross_context.values())
    v47_gate_ok=bool(v47e.get('checks',{}).get('baseline_and_50k_region_gate'))
    safe=bool(all_valid and v47_gate_ok and not hard_bad)
    status=('STOP_INCOMPLETE' if not full else
            'QUARANTINED_PRICE_BAND_VIOLATION' if hard_bad else
            'OBSERVED_NONMONOTONIC_SEARCH_COVERAGE' if safe and
                 any(x.get('missing_from_100k_response',0)>0 for x in contexts.values()) else
            'OBSERVED_NO_MEASURABLE_COVERAGE_DIFFERENCE' if safe else 'UNVERIFIED_BAND_CROSSCHECK')
    return {'status':status,'capture_complete':full,'all_profile_evidence_valid':safe,
            'hard_filter_violation':hard_bad,'backend_price_enforcement_proven':False,
            'server_fixed_result_cap_proven':False,'approved_for_listing_export':False,
            'v47_gate_passed':v47_gate_ok,'v47_comparison_status':v47e['status'],
            'context_validations':validations,'contexts':contexts,'cross_context':cross_context,
            'v47_checks':v47e['checks']}


def report(data):
    evl=data['evaluation']
    lines=['# v4.8 price-band cross-check — actual public route responses','',
      f"- Status: **{evl['status']}**; capture complete: `{evl['capture_complete']}`.",
      f"- All profile evidence valid: `{evl['all_profile_evidence_valid']}`; listing export: **false**.",
      '- Observed absences are within sampled result sets, never measured inventory omissions.',
      '- A plateau near 260 rows is **not** proof of a fixed server result cap.',
      '', '| Context | Cap20 | Cap50 | Cap100 | Band20–50 | Band50–100 | Unique union | Missing from cap100 | Band novel vs cap-only | Candidate truncation |',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for n in ('target_a','target_b'):
        c=evl['contexts'].get(n,{})
        if c.get('complete'):
            x=c['counts'];lines.append('| '+' | '.join(str(v) for v in
              (n,x['cap_20000'],x['cap_50000'],x['cap_100000'],x['band_20001_50000'],
               x['band_50001_100000'],c['union_all'],c['missing_from_100k_response'],
               c['additional_from_explicit_bands'],c['candidate_truncation_signature']))+' |')
    lines.extend(['','## Independent profile repeat evidence',''])
    for n,v in evl['context_validations'].items():
        lines.append(f"- `{n}`: "+', '.join(f'{k}={ok}' for k,ok in v.items()))
    for p in data.get('plans',[]):
        if p.get('failure_observation'):
            f=p['failure_observation']
            lines.extend(['',f"## Incomplete step — {p.get('context')} / {p.get('phase')}",'',
                f"- Core valid: `{f.get('core_valid')}`; route matches: `{f.get('matched_route_count')}`; DOM valid: `{f.get('dom_ok')}`; region valid: `{f.get('region_ok')}`",
                f"- Public price parameter: `{(f.get('url') or {}).get('public_params',{}).get('price')}`",
                f"- Observed route query values: `{[(x.get('public_params') or {}).get('price') for x in f.get('observed_route_queries',[])]}`"])
    lines.extend(['','## Interpretation','',
      '- `missing_from_100k_response` = observed distinct listings under narrower cap or interval conditions but absent from the sampled 100k response.',
      '- A listing may be newly posted, removed, updated or reordered during measurement; cache, ranking and finite result windows are alternative explanations.',
      '- No pagination or total inventory metadata is claimed where not present.',
      '- Stable pseudonyms come from an ephemeral HMAC key; the key and original listing URLs are not exported.',
      '- Server price metadata missing and UI NOT_OBSERVABLE remain explicit uncertainty; no listing is approved.',
      '- Robots and access restrictions stop the experiment; no bypass or retry escalation.',''])
    return '\n'.join(lines)


def publish(outdir,plans,evaluation):
    def safe_stage(stage):return {k:v for k,v in stage.items() if not k.startswith('_')}
    clean=[]
    for p in plans:
        cp={k:v for k,v in p.items() if k not in ('baseline','profiles','failure_observation')}
        if p.get('failure_observation') is not None:
            cp['failure_observation']=safe_stage(p['failure_observation'])
        cp['baseline']=[safe_stage(s) for s in p['baseline']]
        cp['profiles']=[{**{k:v for k,v in lv.items() if k not in ('apply','repeat')},
                         'apply':safe_stage(lv['apply']),'repeat':safe_stage(lv['repeat'])} for lv in p['profiles']]
        clean.append(cp)
    doc={'version':'4.8','time_utc':now(),
         'design':{'target':'cheonan','control':'asan','keyword':'HDD',
                   'category_id':1,'available_only':True,'price_profiles':PROFILES,
                   'two_target_contexts':True,'reversed_order':True},
         'run_level':{'status':evaluation['status'],'blocked':True,'accepted_count':0},
         'plans':clean,'evaluation':evaluation,'credentials_stored':False}
    outdir.mkdir(parents=True,exist_ok=True)
    (outdir/'daangn_price_bands_v4_8_results.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (outdir/'daangn_price_bands_v4_8_report.md').write_text(report(doc),encoding='utf-8')
    (outdir/'daangn_price_bands_v4_8_limited_accept.json').write_text(json.dumps({'version':'4.8','blocked':True,'samples':[],'allowed_count':0},indent=2)+'\n',encoding='utf-8')
    print('v4.8:',evaluation['status'],'complete:',evaluation['capture_complete'],
          'profile evidence valid:',evaluation['all_profile_evidence_valid'],'approved:',0)
    return 0 if evaluation['capture_complete'] and not evaluation['hard_filter_violation'] else 2


async def run(args):
    historical=prior.evidence_reference(args.reference)
    if not core.public_robots_check('HDD').get('allowed'):
        e=evaluate([],historical,complete=False);e['status']='STOP_ROBOTS_NOT_ALLOWED'
        return publish(args.output_dir,[],e)
    try:from playwright.async_api import async_playwright
    except ImportError:
        e=evaluate([],historical,complete=False);e['status']='STOP_PLAYWRIGHT_MISSING'
        return publish(args.output_dir,[],e)
    plans=[];salt=secrets.token_bytes(32)
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=not args.headed)
            try:
                for i,(name,region,order) in enumerate(RUNS):
                    p=await run_context(browser,args,name,region,order,salt)
                    plans.append(p)
                    print('context',name,p['status'],'counts',[(lv['key'],lv['repeat']['count']) for lv in p['profiles']])
                    if p['status']!='CAPTURED_ALL_PROFILES':break
                    if i<len(RUNS)-1:await asyncio.sleep(args.pause_ms/1000)
            finally:await browser.close()
    except Exception as exc:
        plans.append({'context':'browser','region':'unknown','order':[],'baseline':[],
                      'profiles':[],'status':'STOP_BROWSER','error':type(exc).__name__})
    complete=len(plans)==4 and all(p['status']=='CAPTURED_ALL_PROFILES' for p in plans)
    evaluation=evaluate(plans,historical,complete=complete)
    return publish(args.output_dir,plans,evaluation)


def main():
    p=argparse.ArgumentParser(description='Owner-approved public search band cross-check v4.8')
    p.add_argument('--output-dir',type=Path,default=Path('v48_output'))
    p.add_argument('--reference',type=Path,default=ROOT/'evidence/reference_runs.json')
    p.add_argument('--headed',action='store_true')
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--pause-ms',type=int,default=2000)
    args=p.parse_args()
    args.regions={'target':dict(core.BY_KEY['cheonan']),'control':dict(core.BY_KEY['asan'])}
    args.keyword='HDD';args.category_id=1;args.category_name=v46.CATALOG[1]
    args.available_only=True;args.min_price=0;args.max_price=50000
    args.timeout=max(15,min(args.timeout,45));args.settle_ms=max(800,min(4000,args.settle_ms))
    args.pause_ms=max(1000,min(8000,args.pause_ms));args.output_dir=args.output_dir.resolve()
    return asyncio.run(run(args))

if __name__=='__main__':raise SystemExit(main())
