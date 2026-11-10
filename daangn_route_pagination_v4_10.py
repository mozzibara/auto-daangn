# -*- coding: utf-8 -*-
"""v4.10: correlated public search-route pagination/total-count structural audit.

Read-only study: same bounded price-band design as v4.8, with a passive
response-body *shape* recorder. Observed result windows are not a proof of a
server-wide fixed cap or backend implementation. No listing exports.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import secrets
from datetime import datetime,timezone
from pathlib import Path

import daangn_v4_1_core as core
import daangn_browser_v4_4_1 as prior
import daangn_browser_v4_6 as v46
import daangn_price_bands_v4_8 as v48
import daangn_route_structure_v4_10 as structure

ROOT=Path(__file__).resolve().parent


def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')


async def capture_apply(page,args,name,region,key,salt):
    """Correlate a second passive response listener by SHA256 + exact public query."""
    probe=structure.RouteStructureRecorder()
    page.on('response',probe.hook)
    try:
        stage,blocked,steps=await v48.capture_apply(page,args,name,region,key,salt)
    finally:
        page.remove_listener('response',probe.hook)
        await probe.drain()
    stage['route_structure_evidence']=structure.select_correlated_structure(
        stage,probe,key,args.regions[region])
    return stage,bool(blocked or probe.blocked),steps


async def capture_repeat(page,args,name,region,key,url,salt):
    stage=await v48.capture_repeat(page,args,name,region,key,url,salt)
    try:
        boot=await structure.inspect_remix_loader(page)
        stage['document_loader_structure']={'status':boot.get('status'),
                                             'structure':boot,
                                             'pagination':structure.summary_flags(boot)}
    except Exception as exc:
        stage['document_loader_structure']={'status':'UNVERIFIED_DOM_EVALUATION_'+type(exc).__name__}
    return stage


def route_observation_safe(applied):
    """Only authorize a *structural observation*, not any listing export.

    v4.8 `core_valid` requires live DOM item overlap. SPA rendering can lag a
    successful first-party Route fetch. Preserve that failed DOM gate while
    allowing bounded study of a request/digest-correlated response body.
    """
    proof=applied.get('filter_evidence') or {}
    profile=applied.get('price_profile') or {}
    r=applied.get('route_structure_evidence') or {}
    filt=applied.get('response_filter_fields') or {}
    return bool(r.get('status')=='CORRELATED_ROUTE_STRUCTURE' and
                applied.get('region_ok') is True and
                applied.get('matched_route_count',0)>0 and
                applied.get('price_url_shape_observed') is True and
                applied.get('ui_selected') is True and
                filt.get('categoryId') in ('1',1) and filt.get('onlyOnSale') is True and
                proof.get('region_ok') is True and
                all(int(proof.get(k,0))==0 for k in
                   ('price_unknown','price_violations','min_price_violations',
                    'category_violations','sold_violations')) and
                profile.get('rows',0)>0 and
                not r.get('access_blocked'))


def repeat_observation_safe(repeated):
    proof=repeated.get('filter_evidence') or {}
    return bool(repeated.get('region_ok') is True and
                repeated.get('url_persistence')=='PERSISTED_IN_URL' and
                repeated.get('price_url_shape_observed') is True and
                repeated.get('count',0)>0 and
                all(int(proof.get(k,0))==0 for k in
                   ('price_unknown','price_violations','min_price_violations',
                    'category_violations','sold_violations')))


async def run_context(browser,args,name,region,order,salt):
    ctx=await browser.new_context(locale='ko-KR',viewport={'width':1280,'height':850})
    page=await ctx.new_page();page.set_default_timeout(args.timeout*1000)
    p={'context':name,'region':region,'order':list(order),'status':'INCOMPLETE',
       'baseline':[],'profiles':[],'phase':None,'error':None}
    try:
        for i in (1,2):
            p['phase']=f'BASELINE_{i}'
            stage=await v46.document(page,args,name,region,i)
            p['baseline'].append(stage)
            if not stage['core_valid']:raise RuntimeError('BASELINE_INVALID')
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
            applied['structural_audit_only']=not applied['core_valid']
            applied['structural_audit_eligible']=route_observation_safe(applied)
            if not applied['core_valid'] and not applied['structural_audit_eligible']:
                p['failure_observation']=applied
                raise RuntimeError('APPLY_INVALID')
            await asyncio.sleep(args.pause_ms/1000)
            p['phase']='REPEAT_'+key
            repeat=await capture_repeat(page,args,name,region,key,page.url,salt)
            p['profiles'].append({'key':key,'min':v48.PROFILES[key][0],
                                  'max':v48.PROFILES[key][1],
                                  'apply':applied,'repeat':repeat,'steps':steps})
            repeat['structural_audit_only']=not repeat['core_valid']
            repeat['structural_audit_eligible']=repeat_observation_safe(repeat)
            if not repeat['core_valid'] and not repeat['structural_audit_eligible']:
                raise RuntimeError('REPEAT_INVALID')
            if any((s.get('filter_evidence') or {}).get('status','').startswith('QUARANTINED')
                   for s in (applied,repeat)):
                raise RuntimeError('EXPLICIT_FILTER_VIOLATION')
            await asyncio.sleep(args.pause_ms/1000)
        p['status']='CAPTURED_ALL_PROFILES'
    except Exception as exc:
        p['status']='STOP_'+type(exc).__name__
        p['error']=str(exc)[:140] if isinstance(exc,RuntimeError) else type(exc).__name__
    finally:await ctx.close()
    return p


def observations(plans):
    """One row per *actual* public filtered route, with correspondence status."""
    rows=[]
    for p in plans:
        for profile in p.get('profiles',[]):
            s=profile['apply'];r=s.get('route_structure_evidence') or {}
            obj=r.get('structure') or {};flags=r.get('pagination') or {}
            repeated=profile['repeat']
            boot=(repeated.get('document_loader_structure') or {}).get('structure') or {}
            rows.append({'context':p['context'],'region':p['region'],'profile':profile['key'],
                         'bounds':[profile['min'],profile['max']],
                         'route_correlated':r.get('status')=='CORRELATED_ROUTE_STRUCTURE',
                         'route_status':r.get('status','MISSING'),
                         'url_price_param':r.get('request_price'),
                         'route_response_count':obj.get('raw_articles_count'),
                         'repeat_count':repeated.get('count'),
                         'repeat_loader_count':boot.get('raw_articles_count'),
                         'repeat_loader_status':boot.get('status'),
                         'route_pagination_status':flags.get('status'),
                         'explicit_window_signal':flags.get('explicit_window_signal',False),
                         'possible_more_results':flags.get('possible_more_results'),
                         'reported_total':flags.get('reported_total'),
                         'reported_page_size':flags.get('reported_page_size'),
                         'client_extraction_cap_reached':obj.get('client_extraction_cap_reached'),
                         'route_pagination_fields':obj.get('pagination_fields',[]),
                         'route_loader_keys':obj.get('loader_keys',[]),
                         'route_header_evidence':obj.get('headers',{}),
                         'repeat_pagination_fields':boot.get('pagination_fields',[]),
                         'route_match_count':s.get('matched_route_count',0),
                         'observed_stage_valid':bool(s.get('core_valid') and repeated.get('core_valid')),
                         'structural_audit_only':bool(s.get('structural_audit_only') or repeated.get('structural_audit_only')),
                         'structural_audit_eligible':bool(s.get('structural_audit_eligible') and repeated.get('structural_audit_eligible'))})
    return rows


def judge(plans, historical, *, complete):
    # Reuse the earlier strict evidence gate to identify invalid/reordered samples.
    old=v48.evaluate(plans,historical,complete=complete)
    rows=observations(plans)
    eligible=[r for r in rows if r['region']=='target']
    correlated=[r for r in eligible if r['route_correlated']]
    structure_complete=bool(complete and len(eligible)==len(v48.PROFILES)*2 and
                            len(correlated)==len(eligible))
    window=[r for r in correlated if r['explicit_window_signal']]
    counts=[r['route_response_count'] for r in correlated if isinstance(r['route_response_count'],int)]
    caps=[r['route_response_count'] for r in correlated
          if r['profile'].startswith('cap_') and isinstance(r['route_response_count'],int)]
    near260=sum(250<=n<=275 for n in counts)
    observed_cap_plateau=bool(len(caps)==6 and max(caps)-min(caps)<=12)
    # No evidence of implementation internals from shape alone.
    level=('EXPLICIT_WINDOW_SIGNALS_IN_SEARCH_ROUTE' if window else
           'NO_EXPLICIT_PAGINATION_FIELD_IN_CORRELATED_ROUTES' if structure_complete else
           'STRUCTURE_CORRELATION_INCOMPLETE')
    has_more=bool(window)
    return {'status':level,'capture_complete':bool(complete),
            'all_target_route_structures_correlated':structure_complete,
            'profiles_expected':len(v48.PROFILES)*2,'profiles_correlated':len(correlated),
            'target_returned_counts':counts,'target_count_min':min(counts) if counts else None,
            'target_count_max':max(counts) if counts else None,
            'near_260_rows_count':near260,'observed_cap_profile_count_plateau':observed_cap_plateau,
            'explicit_window_signal_profiles':[f"{x['context']}:{x['profile']}" for x in window],
            'explicit_window_signals_present':has_more,
            'client_cap_truncation_count':sum(x['client_extraction_cap_reached'] is True for x in correlated),
            'observations':rows,
            'previous_v48_evaluation_status':old['status'],
            'previous_v48_capture_complete':old['capture_complete'],
            'previous_v48_contexts':old.get('contexts',{}),
            'previous_v48_profile_validation':old.get('context_validations',{}),
            'hard_price_or_region_violation':old['hard_filter_violation'],
            'fixed_server_return_count_limit_proven':False,
            'fixed_return_limit_value':None,
            'backend_pagination_implementation_proven':False,
            'full_inventory_completeness_proven':False,
            'approved_listing_count':0}


def report(doc):
    a=doc['evaluation']
    s=['# v4.10 — actual Route response pagination and count evidence','',
       f"- Status: **{a['status']}**; complete: `{a['capture_complete']}`; correlated target responses: `{a['profiles_correlated']}/{a['profiles_expected']}`.",
       f"- v4.8 prior gate: `{a['previous_v48_evaluation_status']}`; fixed backend cap proven: **False**.",
       f"- Response count range across correlated target profiles: `{a['target_count_min']}–{a['target_count_max']}`.",
       f"- Responses near 260 rows (250–275): **{a['near_260_rows_count']}**; cap-only plateau: `{a['observed_cap_profile_count_plateau']}`.",
       f"- Explicit window signals: `{a['explicit_window_signal_profiles']}`; client truncation (>650): `{a['client_cap_truncation_count']}`.",
       '', '| Context | Price interval | Route items | Repeat items | Loader items | Pagination status | Reported total | Page size |',
       '|---|---|---:|---:|---:|---|---:|---:|']
    for row in a['observations']:
        s.append('| '+' | '.join(str(row.get(k)) for k in ('context','profile','route_response_count',
             'repeat_count','repeat_loader_count','route_pagination_status','reported_total','reported_page_size'))+' |')
    s.extend(['','## Observed pagination field paths and types',''])
    for r in a['observations']:
        fields=r['route_pagination_fields']
        s.append(f"- `{r['context']}:{r['profile']}` — route correlation: `{r['route_correlated']}`; fields: `{[(x['path'],x['type'],x.get('value') if x['type'] in ('bool','int','decimal_string') else x.get('present')) for x in fields]}`")
    s.extend(['','## Scope limits','',
      '- Exact public search-Route response JSON is inspected only **in memory**; raw bodies, cursor values and listing URLs are not saved.',
      '- The route article-array count is measured **before** the existing 650-item local extraction cap.',
      '- Absence of pagination fields means only that none was found in these **inspected response structures**, not that other endpoints or internal pagination cannot exist.',
      '- A ~260-item count plateau, even with a page-size field, does **not** prove a universal fixed server cap.',
      '- A response total greater than returned items or `hasMore=true` is a signal of an observed window, not proof of how missing items are ranked.',
      '- The earlier v4.8 Jaccard/price/region acceptance policy is maintained independently; no shopping listing is approved.',''])
    return '\n'.join(s)


def publish(outdir,plans,analysis):
    outdir.mkdir(parents=True,exist_ok=True)
    # Never include per-listing URLs or DOM paths, including failure observations.
    def safe_stage(stage):
        return {k:v for k,v in stage.items() if not k.startswith('_') and k!='observed_items'}
    clean=[]
    for p in plans:
        cp={k:v for k,v in p.items() if k not in ('baseline','profiles','failure_observation')}
        cp['baseline']=[safe_stage(s) for s in p.get('baseline',[])]
        cp['profiles']=[{'key':row['key'],'min':row['min'],'max':row['max'],
                         'apply':safe_stage(row['apply']),
                         'repeat':safe_stage(row['repeat'])} for row in p.get('profiles',[])]
        if p.get('failure_observation') is not None:
            cp['failure_observation']=safe_stage(p['failure_observation'])
        clean.append(cp)
    doc={'version':'4.10','time_utc':now(),
         'design':{'region':'cheonan','control_region':'asan','keyword':'HDD',
                   'price_profiles':v48.PROFILES,'read_only_route_inspection':True},
         'run_level':{'status':analysis['status'],'blocked':True,'approved_count':0},
         'evaluation':analysis,'plans':clean,'credentials_stored':False}
    (outdir/'daangn_route_pagination_v4_10_results.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (outdir/'daangn_route_pagination_v4_10_report.md').write_text(report(doc),encoding='utf-8')
    (outdir/'daangn_route_pagination_v4_10_limited_accept.json').write_text('{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    print('v4.10:',analysis['status'],'route correlated:',analysis['profiles_correlated'],
          'capture:',analysis['capture_complete'],'approved:',0)
    return 0 if analysis['capture_complete'] and not analysis['hard_price_or_region_violation'] else 2


async def run(args):
    historic=prior.evidence_reference(args.reference)
    if not core.public_robots_check('HDD').get('allowed'):
        a=judge([],historic,complete=False);a['status']='STOP_ROBOTS_UNVERIFIED_OR_DENIED'
        return publish(args.output_dir,[],a)
    try:from playwright.async_api import async_playwright
    except ImportError:
        a=judge([],historic,complete=False);a['status']='STOP_PLAYWRIGHT_UNAVAILABLE'
        return publish(args.output_dir,[],a)
    plans=[];salt=secrets.token_bytes(32)
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=not args.headed)
            try:
                for i,(name,region,order) in enumerate(v48.RUNS):
                    plan=await run_context(browser,args,name,region,order,salt)
                    plans.append(plan)
                    print('context:',name,plan['status'],'profiles:',len(plan.get('profiles',[])))
                    if plan['status']!='CAPTURED_ALL_PROFILES':break
                    if i<len(v48.RUNS)-1:await asyncio.sleep(args.pause_ms/1000)
            finally:await browser.close()
    except Exception as exc:
        plans.append({'context':'browser','region':'unknown','order':[],
                      'baseline':[],'profiles':[],'status':'STOP_BROWSER',
                      'error':type(exc).__name__})
    complete=len(plans)==4 and all(p['status']=='CAPTURED_ALL_PROFILES' for p in plans)
    a=judge(plans,historic,complete=complete)
    return publish(args.output_dir,plans,a)


def main():
    p=argparse.ArgumentParser(description='v4.10 public Route pagination structural audit')
    p.add_argument('--output-dir',type=Path,default=Path('v410_output'))
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
