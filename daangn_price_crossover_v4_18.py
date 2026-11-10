# -*- coding: utf-8 -*-
"""v4.18: UI-controlled, Route-body-correlated price-cap crossover study.

This observes actual public search responses, not backend source code.
Never invent cursor/pagination, infer server enforcement from URL alone,
export raw listing identifiers/URLs, or relax historical listing approval.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import secrets
from types import SimpleNamespace

import daangn_v4_1_core as core
import daangn_v4_5_evidence as evidence
import daangn_browser_v4_6 as v46
import daangn_price_bands_v4_8 as bands
import daangn_price_ladder_v4_7 as ladder
import daangn_full_route_v4_14 as full
import daangn_filter_recheck_v4_15 as recheck
import daangn_render_gap_v4_12 as render
import daangn_network_flow_v4_11 as network

PROFILES=('cap_20000','cap_50000','cap_100000')
DESIGN=(
    ('cheonan_a','cheonan',('cap_20000','cap_50000','cap_100000')),
    ('asan_control','asan',('cap_50000',)),
    ('cheonan_b','cheonan',('cap_100000','cap_50000','cap_20000')))
EXPECTED_CONTEXTS={(name,key) for name,_,keys in DESIGN for key in keys}
MIN_REPEAT_JACCARD=0.80


def price_shape(model,cap):
    articles=(model or {}).get('articles') or []
    vals=[evidence.int_price(x.get('price')) if isinstance(x,dict) else None for x in articles]
    valid=[n for n in vals if n is not None]
    return {
        'raw_array_rows':len(articles),
        'known_price_rows':len(valid),
        'unknown_price_rows':len(vals)-len(valid),
        'above_requested_cap':sum(n>cap for n in valid),
        'price_min_krw':min(valid) if valid else None,
        'price_max_krw':max(valid) if valid else None,
        'bins':{
            'at_most_20000':sum(n<=20000 for n in valid),
            '20001_to_50000':sum(20000<n<=50000 for n in valid),
            '50001_to_100000':sum(50000<n<=100000 for n in valid),
            'above_100000':sum(n>100000 for n in valid)}
    }


def matched_model(bodies,stage,key,region):
    expected=stage.get('matched_route_digest') or []
    if len(expected)!=1:return None
    valid=[event for event in bodies.events if event.get('digest')==expected[0] and
           bands.matched_route(event,key,core.BY_KEY[region])]
    return valid[0] if len(valid)==1 else None


def read_ui_proof(diag):
    spa=(diag.get('spa') or {}).get('final') or {}
    reload=(diag.get('reload') or {}).get('final') or {}
    return {
        'spa':spa.get('status','NOT_OBSERVABLE'),
        'reload':reload.get('status','NOT_OBSERVABLE'),
        'persisted_url':diag.get('same_filter_url_after_reload') is True,
        'verified_both':diag.get('stable_selection_verified') is True and
            spa.get('region_id_matches') is True and reload.get('region_id_matches') is True,
        'spa_maximum_krw':((spa.get('panel_probe') or {}).get('interpretation') or {}).get('maximum'),
        'reload_maximum_krw':((reload.get('panel_probe') or {}).get('interpretation') or {}).get('maximum'),
        'access_restricted':diag.get('access_restricted') is True
    }


async def capture(browser,name,region,key,salt,options):
    """One new logged-out context and one real UI-applied max-only cap."""
    cap=bands.PROFILES[key][1]
    result={'context':name,'region':region,'profile':key,'max_price_krw':cap,
            'status':'INCOMPLETE','route_correlated':False,'raw_route_rows':None,
            'price_shape':{},'matched_ui_route_count':None,
            'observed_url_shape':False,'ui':{},'response_price_metadata':False,
            'response_filter_status':'NOT_EVALUATED','error_type':None,
            'access_restricted':False,'collector_errors':0,'token_count':0,
            '_rows':{}}
    ctx=await browser.new_context(locale='ko-KR',viewport={'width':1280,'height':850})
    page=await ctx.new_page()
    page.set_default_timeout(options.timeout*1000)
    recorder=network.NetworkRecorder()
    ctx.on('request',recorder.on_request)
    ctx.on('response',recorder.on_response)
    try:
        baseline=await page.goto(core.search_url('HDD',core.BY_KEY[region]),
             wait_until='domcontentloaded',timeout=options.timeout*1000)
        if baseline is None or baseline.status!=200:
            raise RuntimeError('BASELINE_HTTP_INVALID')
        await page.wait_for_timeout(options.settle_ms)
        await recorder.drain()
        if core.region_id_in_url(page.url)!=core.BY_KEY[region]['id']:
            raise RuntimeError('BASELINE_REGION_MISMATCH')
        if (await render.snapshot(page)).get('restricted') or recorder.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
        args=SimpleNamespace(keyword='HDD',regions={'target':dict(core.BY_KEY[region])},
            category_id=1,category_name=v46.CATALOG[1],available_only=True,
            min_price=0,max_price=cap,settle_ms=options.settle_ms,timeout=options.timeout)
        probe=None
        if getattr(options,'filter_structure_v419',False):
            # Lazy import keeps v4.18 backwards compatible despite the
            # v4.19 evaluator importing this module for its existing runner.
            from daangn_filter_schema_v4_19 import inspect_payload
            probe=lambda raw,model: inspect_payload(raw,model,cap)
        bodies=full.RouteBodies(field_probe=probe)
        recorder.phase='FILTER_APPLY'
        page.on('response',bodies.on_response)
        try:
            stage,blocked,_steps=await bands.capture_apply(page,args,name,'target',key,salt)
        finally:
            page.remove_listener('response',bodies.on_response)
            await bodies.drain()
        await recorder.drain()
        if blocked or bodies.blocked or recorder.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
        result['collector_errors']=bodies.errors+recorder.errors
        if result['collector_errors'] or recorder.overflow:
            raise RuntimeError('COLLECTOR_INCOMPLETE')
        result['matched_ui_route_count']=stage.get('matched_route_count')
        result['observed_url_shape']=stage.get('price_url_shape_observed') is True
        if stage.get('matched_route_count')!=1 or not result['observed_url_shape']:
            raise RuntimeError('UI_ROUTE_NOT_UNIQUELY_CORRELATED')
        matching=matched_model(bodies,stage,key,region)
        if matching is None:
            raise RuntimeError('RAW_ROUTE_SHA_MISMATCH')
        if len(matching.get('model',{}).get('articles') or [])!=matching['raw_count']:
            raise RuntimeError('ROUTE_ARRAY_TRUNCATED')
        if core.region_id_in_url(page.url)!=core.BY_KEY[region]['id']:
            raise RuntimeError('FILTER_REGION_MISMATCH')
        if (await render.snapshot(page)).get('restricted'):
            raise RuntimeError('ACCESS_RESTRICTION')
        result['route_correlated']=True
        if probe is not None:
            result['v419_filter_structure']=matching.get('v419_filter_structure')
        result['raw_route_rows']=matching['raw_count']
        result['price_shape']=price_shape(matching['model'],cap)
        result['_rows']=bands.identity_rows(matching['model'],salt)
        result['token_count']=len(result['_rows'])
        observed_url=page.url
        diag=await recheck.durable_recheck(
            page,args,observed_url,options.settle_ms,stage.get('ui_recheck'))
        result['ui']=read_ui_proof(diag)
        if result['ui']['access_restricted']:
            raise RuntimeError('ACCESS_RESTRICTION')
        ui_ok=result['ui']['verified_both'] and (
            result['ui']['spa_maximum_krw']==cap and
            result['ui']['reload_maximum_krw']==cap)
        proof=evidence.validated_predicates(
            matching['model'],observed_url,core.BY_KEY[region]['id'],
            ui_ok,True,
            ui_observation_status='OBSERVED_MATCH' if ui_ok else 'NOT_OBSERVABLE',
            expected=v46.expected_for(args),require_response_filters=True)
        result['response_filter_status']=proof['status']
        result['response_price_metadata']=bool(
            (proof.get('criteria') or {}).get('max_price',{}).get('server_metadata_confirmed'))
        result['response_price_source']=(
            (proof.get('criteria') or {}).get('max_price',{}).get('source'))
        result['response_category_source']=(
            (proof.get('criteria') or {}).get('category',{}).get('source'))
        result['response_availability_source']=(
            (proof.get('criteria') or {}).get('available_only',{}).get('source'))
        result['status']='CAPTURED_ROUTE_AND_UI' if ui_ok else 'CAPTURED_ROUTE_UI_UNVERIFIED'
    except Exception as exc:
        name_only=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
        permitted={'BASELINE_HTTP_INVALID','BASELINE_REGION_MISMATCH','ACCESS_RESTRICTION',
                   'COLLECTOR_INCOMPLETE','UI_ROUTE_NOT_UNIQUELY_CORRELATED',
                   'RAW_ROUTE_SHA_MISMATCH','ROUTE_ARRAY_TRUNCATED','FILTER_REGION_MISMATCH'}
        result['status']='STOP_'+type(exc).__name__
        result['error_type']=name_only if name_only in permitted else type(exc).__name__
        result['access_restricted']=name_only=='ACCESS_RESTRICTION'
    finally:
        await recorder.drain()
        result['access_restricted']=result['access_restricted'] or recorder.blocked
        result['collector_errors']=result['collector_errors'] or recorder.errors
        await ctx.close()
    return result


def set_stats(left,right):
    a=set(left);b=set(right);both=a&b
    return {'left':len(a),'right':len(b),'shared':len(both),
        'left_only':len(a-b),'right_only':len(b-a),
        'jaccard':round(len(both)/len(a|b),6) if a|b else None}


def cross_comparison(rows):
    """Sample-set analysis. Absent token never means absent from marketplace."""
    keyed={(x.get('context'),x.get('profile')):x for x in rows}
    expected=EXPECTED_CONTEXTS
    captured=set(keyed)==expected and len(rows)==len(expected) and all(
        x.get('route_correlated') and x.get('status') in
            ('CAPTURED_ROUTE_AND_UI','CAPTURED_ROUTE_UI_UNVERIFIED') and
        x.get('raw_route_rows',0)>0 and
        (x.get('price_shape') or {}).get('raw_array_rows')==x['raw_route_rows']
        for x in rows)
    restricted=any(x.get('access_restricted') for x in rows)
    violating=[(x.get('context'),x.get('profile')) for x in rows if
        (x.get('price_shape') or {}).get('above_requested_cap',0)>0]
    missing=[(x.get('context'),x.get('profile')) for x in rows if
        (x.get('price_shape') or {}).get('unknown_price_rows',0)>0]
    ui_verified=bool(captured and all(
        x.get('status')=='CAPTURED_ROUTE_AND_UI' and
        (x.get('ui') or {}).get('verified_both') and
        x['ui'].get('spa_maximum_krw')==x.get('max_price_krw') and
        x['ui'].get('reload_maximum_krw')==x.get('max_price_krw')
        for x in rows))
    repeat={};contrasts={};differences={};controls={}
    if captured:
        for key in PROFILES:
            left=keyed[('cheonan_a',key)]['_rows']
            right=keyed[('cheonan_b',key)]['_rows']
            repeat[key]=set_stats(left,right)
        for name in ('cheonan_a','cheonan_b'):
            cap20=keyed[(name,'cap_20000')]
            cap50=keyed[(name,'cap_50000')]
            cap100=keyed[(name,'cap_100000')]
            high50=cap100['price_shape']['bins']['50001_to_100000']
            mid=cap50['price_shape']['bins']['20001_to_50000']
            contrasts[name]={
                'max20_has_no_above_20k':cap20['price_shape']['above_requested_cap']==0,
                'max50_has_no_above_50k':cap50['price_shape']['above_requested_cap']==0,
                'max100_has_no_above_100k':cap100['price_shape']['above_requested_cap']==0,
                'middle_band_seen_in_50k':mid,
                'higher_than_50k_seen_in_100k':high50,
                'upper_tail_response_contrast':bool(mid>0 and high50>0)}
            differences[name]={
                '20k_vs_50k':set_stats(cap20['_rows'],cap50['_rows']),
                '50k_vs_100k':set_stats(cap50['_rows'],cap100['_rows']),
                '20k_vs_100k':set_stats(cap20['_rows'],cap100['_rows']),
                'nonmonotone_sets_are_not_violations':True}
        controls={
            'cheonan_a_vs_asan_50k':set_stats(
                keyed[('cheonan_a','cap_50000')]['_rows'],
                keyed[('asan_control','cap_50000')]['_rows']),
            'cheonan_b_vs_asan_50k':set_stats(
                keyed[('cheonan_b','cap_50000')]['_rows'],
                keyed[('asan_control','cap_50000')]['_rows'])}
    repeat_consistent=bool(repeat and all(
        row.get('jaccard') is not None and row['jaccard']>=MIN_REPEAT_JACCARD
        for row in repeat.values()))
    positive_contrast=bool(contrasts and all(
        x['upper_tail_response_contrast'] for x in contrasts.values()))
    full_price_coverage=bool(captured and not missing and all(
        (x.get('price_shape') or {}).get('known_price_rows')==x.get('raw_route_rows')
        for x in rows))
    control_distinct=bool(controls and all(c.get('jaccard') is not None and
        c.get('shared')<min(c.get('left',0),c.get('right',0))
        for c in controls.values()))
    behavioral=bool(captured and ui_verified and full_price_coverage and
        not violating and positive_contrast and repeat_consistent and control_distinct)
    response_declares=bool(captured and all(
        x.get('response_price_metadata') is True for x in rows))
    if restricted:status='STOP_ACCESS_RESTRICTION'
    elif not captured:status='INCONCLUSIVE_ROUTE_CROSSOVER_INCOMPLETE'
    elif violating:status='QUARANTINED_ROUTE_PRICE_CAP_VIOLATION'
    elif not full_price_coverage:status='UNVERIFIED_UNKNOWN_LISTING_PRICES'
    elif not ui_verified:status='UNVERIFIED_UI_PRICE_SELECTION'
    elif behavioral:status='OBSERVED_SERVER_PRICE_CAP_BEHAVIOR_SUPPORTED'
    elif positive_contrast:status='OBSERVED_CAP_CONTRAST_WITH_REPEAT_OR_CONTROL_UNCERTAINTY'
    else:status='INSUFFICIENT_PRICE_BAND_CONTRAST'
    return {'status':status,'capture_complete':captured,
        'ui_all_caps_verified':ui_verified,
        'all_item_prices_known':full_price_coverage,
        'price_cap_violations':violating,
        'unknown_price_contexts':missing,
        'positive_tail_contrast_both_target_repeats':positive_contrast,
        'same_cap_target_repeat_consistent':repeat_consistent,
        'independent_control_distinct':control_distinct,
        'behavioral_server_price_cap_supported':behavioral,
        'response_declares_max_price_cap_all_profiles':response_declares,
        'backend_implementation_proven':False,
        'historical_strict_listing_approval_changed':False,
        'strict_listing_approved_count':0,
        'fixed_server_result_cap_proven':False,
        'whole_marketplace_inventory_proven':False,
        'repeat_by_cap':repeat,'target_within_context':differences,
        'target_price_contrasts':contrasts,'regional_control':controls,
        'run_expected_profile_count':len(expected),
        'run_captured_profile_count':sum(x.get('route_correlated') for x in rows)}


def safe_row(row):
    """Drop per-listing HMAC tokens and all raw response/URL fields."""
    keys=('context','region','profile','max_price_krw','status',
          'route_correlated','raw_route_rows','price_shape','matched_ui_route_count',
          'observed_url_shape','ui','response_price_metadata',
          'response_filter_status','response_price_source',
          'response_category_source','response_availability_source',
          'error_type','access_restricted','collector_errors','token_count')
    return {k:row.get(k) for k in keys}


def report(doc):
    e=doc['evaluation']
    lines=['# v4.18 — actual Route response price-cap crossover','',
        f"- Verdict: **{e['status']}**",
        f"- Complete: {e['capture_complete']}, all selected UI price caps verified: {e['ui_all_caps_verified']}",
        f"- Behavioral server price-cap differentiation supported: **{e['behavioral_server_price_cap_supported']}**",
        f"- Direct response maximum price metadata for all profiles: {e['response_declares_max_price_cap_all_profiles']}",
        '- Backend internal implementation, total marketplace recall and strict listing approvals are not proven.',
        '', '| Context | Max KRW | Route rows | Above cap | Max observed price KRW | SPA/reload UI | Response max field |',
        '|---|---:|---:|---:|---:|---|---|']
    for x in doc['observations']:
        p=x.get('price_shape') or {}
        u=x.get('ui') or {}
        lines.append('| '+' | '.join(map(str,(x.get('context'),
            x.get('max_price_krw'),x.get('raw_route_rows'),
            p.get('above_requested_cap'),p.get('price_max_krw'),
            'verified' if u.get('verified_both') else 'unverified',
            x.get('response_price_metadata'))))+' |')
    lines+=['','## Context-independent contrast evidence','']
    for name,contrast in e['target_price_contrasts'].items():
        lines.append(f"- {name}: (20k,50k] items in 50k response: {contrast['middle_band_seen_in_50k']}; "
            f"(50k,100k] items in 100k response: {contrast['higher_than_50k_seen_in_100k']}")
    lines+=['','## Interpretation','',
        '- Each price cap was entered using the actual public filter UI; the emitted Route JSON body was correlated by SHA-256 and exact public request parameters.',
        '- Actual UI checked state and maximum input value were re-observed in both SPA and exact filtered-URL reload.',
        '- The response-price contrast is strong *behavioral* evidence of price sensitivity in server-returned results; it does not disclose the backend query implementation or guarantee every relevant listing is returned.',
        '- Inconsistent set inclusion is expected with ranking/windowing and concurrent listing changes; it is not, alone, proof of a broken server price filter.',
        '- Unknown prices, any observed over-cap prices, or incomplete UI evidence are not promoted as positive conclusions.',
        '- No listing URL, stable ID, raw body, HMAC key or per-item token is persisted. The strict listing approval remains 0.','']
    return '\n'.join(lines)


async def run(options):
    observations=[]
    salt=secrets.token_bytes(32)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=not options.headed)
            try:
                for name,region,keys in DESIGN:
                    for key in keys:
                        row=await capture(browser,name,region,key,salt,options)
                        observations.append(row)
                        print('v4.18',name,key,row['status'],
                              row.get('raw_route_rows'),
                              (row.get('price_shape') or {}).get('above_requested_cap'))
                        if row.get('status','').startswith('STOP_') or row.get('access_restricted'):
                            break
                        await asyncio.sleep(2)
                    if observations and (observations[-1]['status'].startswith('STOP_') or
                                         observations[-1].get('access_restricted')):
                        break
            finally:
                await browser.close()
    except Exception as exc:
        observations.append({'context':'browser','profile':None,'status':'STOP_'+type(exc).__name__,
                             'access_restricted':False,'_rows':{}})
    decision=cross_comparison(observations)
    doc={'version':'4.18','utc_time':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'design':{'keyword':'HDD','category_id':1,'available_only':True,
                  'target':'cheonan','control':'asan',
                  'target_caps_krw':[20000,50000,100000],
                  'target_orders':{'cheonan_a':[20000,50000,100000],
                                   'cheonan_b':[100000,50000,20000]},
                  'control_cap_krw':50000,
                  'per_profile_new_browser_context':True,
                  'first_party_route_sha_correlated':True,
                  'persisted_raw_listing_urls':False},
        'evaluation':decision,
        'observations':[safe_row(x) for x in observations],
        'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    options.output_dir.mkdir(parents=True,exist_ok=True)
    (options.output_dir/'v418_price_crossover_results.json').write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (options.output_dir/'v418_price_crossover_report.md').write_text(
        report(doc),encoding='utf-8')
    (options.output_dir/'v418_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if decision['capture_complete'] and not decision['price_cap_violations'] else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v418_output'))
    p.add_argument('--headed',action='store_true')
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    options=p.parse_args()
    options.output_dir=options.output_dir.resolve()
    options.timeout=max(15,min(45,options.timeout))
    options.settle_ms=max(800,min(3500,options.settle_ms))
    return asyncio.run(run(options))


if __name__=='__main__':
    raise SystemExit(main())
