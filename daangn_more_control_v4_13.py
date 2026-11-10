# -*- coding: utf-8 -*-
"""v4.13 - verify whether a real 'more' control expands the search UI's first-32 window.

Only click a *discovered*, uniquely identified search-results control. No guessed
pagination URL, cursor replay, raw listing exports, authentication, or bypass.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import daangn_v4_1_core as core
import daangn_browser_v4_6 as v46
import daangn_price_bands_v4_8 as v48
import daangn_render_gap_v4_12 as v412
import daangn_network_flow_v4_11 as v411


CONTROL_JS = r"""() => {
  const names = /^(?:더\s*보기|더\s*불러오기|더\s*많이\s*보기|더\s*많은\s*(?:매물|상품|결과)\s*보기|(?:매물|상품|검색\s*결과)\s*더\s*보기|계속\s*보기|모두\s*보기|load\s*more|show\s*more)(?:\s*\(\d+\))?$/i;
  const listing = /^\/kr\/buy-sell\/[^/]+-[A-Za-z0-9]{10,}\/?$/;
  const cards = [...document.querySelectorAll('a[href]')].filter(a => {
    try { const u=new URL(a.getAttribute('href'),location.href);
      return u.hostname==='www.daangn.com' && listing.test(u.pathname);
    } catch { return false; }
  });
  const bottoms=cards.map(x=>x.getBoundingClientRect().bottom+scrollY);
  const lastBottom=bottoms.length ? Math.max(...bottoms) : null;
  const allButtons=[...document.querySelectorAll('button')];
  const allLinks=[...document.querySelectorAll('a[href]')];
  const all=[...document.querySelectorAll('button,a[href],[role="button"]')];
  const current=new URL(location.href);
  function linkSafe(e) {
    try {
      const u=new URL(e.getAttribute('href'),location.href);
      if(u.origin!==current.origin || u.pathname!==current.pathname || current.pathname!=='/kr/search/buy-sell/') return false;
      return ['q','in','price','category_id','only_on_sale'].every(k=>current.searchParams.get(k)===u.searchParams.get(k));
    } catch {return false;}
  }
  const matches=[];
  for(const el of all) {
    let text=(el.getAttribute('aria-label')||el.innerText||el.textContent||'').trim().replace(/\s+/g,' ');
    if(text.length>90 || !names.test(text)) continue;
    const s=getComputedStyle(el),box=el.getBoundingClientRect(),tag=el.tagName.toLowerCase();
    const visible=box.width>0 && box.height>0 && el.getClientRects().length>0 && s.display!=='none' && s.visibility!=='hidden';
    const enabled=!el.disabled && el.getAttribute('aria-disabled')!=='true';
    const top=box.top+scrollY;
    const near=lastBottom!==null && top>=lastBottom-120 && top<=lastBottom+1400;
    const withinResults=!el.closest('nav,header,footer,[role="dialog"],[role="menu"]');
    const kind=tag==='button'?'BUTTON':tag==='a'?'LINK':'ARIA_BUTTON';
    const safeLink=tag==='a' && linkSafe(el);
    const buttonIndex=tag==='button' ? allButtons.indexOf(el):null;
    const linkIndex=tag==='a'?allLinks.indexOf(el):null;
    const safe=visible && enabled && near && withinResults &&
       ((kind==='BUTTON' && el.type!=='submit') || (kind==='LINK' && safeLink));
    matches.push({kind,visible,enabled,near_results:near,within_results:withinResults,
       safe_search_link:safeLink,actionable:safe,
       control_index:kind==='BUTTON'?buttonIndex:kind==='LINK'?linkIndex:null});
  }
  const body=(document.body?.innerText||'').slice(0,6000);
  return {
    status:cards.length?'OBSERVED_SEARCH_LIST':'NO_SEARCH_LIST_ANCHORS',
    listing_anchor_count:cards.length,
    at_page_bottom:window.scrollY+window.innerHeight>=document.documentElement.scrollHeight-6,
    scroll_height:Math.round(document.documentElement.scrollHeight),
    named_candidate_count:matches.length,
    visible_candidate_count:matches.filter(x=>x.visible).length,
    near_results_count:matches.filter(x=>x.near_results).length,
    actionable_count:matches.filter(x=>x.actionable).length,
    candidates:matches.slice(0,15),
    candidates_truncated:matches.length>15,
    access_restricted:/captcha|verify you are human|access denied|unusual traffic|비정상적인 접근|자동화된 접근|로그인이 필요합니다|로그인 후 이용/i.test(body)
  };
}""".strip()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def select_control(observed):
    """Only unique visible, enabled, result-adjacent actual button or safe search link."""
    if observed.get('access_restricted'):
        return {'status':'STOP_ACCESS_RESTRICTION'}
    if not observed.get('at_page_bottom'):
        return {'status':'UNVERIFIED_NOT_AT_BOTTOM'}
    if observed.get('status')!='OBSERVED_SEARCH_LIST':
        return {'status':'UNVERIFIED_NO_SEARCH_LIST'}
    if observed.get('candidates_truncated'):
        return {'status':'UNVERIFIED_TOO_MANY_CONTROLS'}
    eligible=[x for x in observed.get('candidates',[]) if x.get('actionable')]
    if not eligible:
        if observed.get('named_candidate_count',0)==0:
            return {'status':'NO_NAMED_MORE_CONTROL_OBSERVED'}
        return {'status':'NO_SAFE_RESULT_MORE_CONTROL'}
    if len(eligible)!=1 or observed.get('actionable_count')!=1:
        return {'status':'AMBIGUOUS_MULTIPLE_MORE_CONTROLS'}
    c=eligible[0]
    if c.get('kind') not in ('BUTTON','LINK') or type(c.get('control_index')) is not int or c['control_index']<0:
        return {'status':'UNVERIFIED_CONTROL_LOCATOR'}
    return {'status':'READY_TO_CLICK','kind':c['kind'],'control_index':c['control_index']}


async def observed_controls(page):
    return await page.evaluate(CONTROL_JS)


async def scroll_to_end(page, recorder, settle_ms, max_steps=8):
    recorder.phase='SCROLL_TO_BOTTOM'
    for _ in range(max_steps):
        await page.mouse.wheel(0,1500)
        await page.wait_for_timeout(max(350,min(settle_ms//2,900)))
        if recorder.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
    await page.wait_for_timeout(settle_ms)
    await recorder.drain()
    return await observed_controls(page)


def compare_phase(route_rows, dom_snapshot):
    return v412.route_relation(route_rows,dom_snapshot.get('dom_visible',[]))


def classify_click(before, after, correlation, *, filter_persisted, blocked, request_count):
    """Prove expansion only for a correlated stable search, not any other DOM change."""
    if blocked:
        return 'STOP_ACCESS_RESTRICTION'
    if not filter_persisted:
        return 'UNVERIFIED_FILTER_OR_REGION_CHANGED'
    if not correlation:
        return 'UNVERIFIED_ORIGINAL_ROUTE_MISMATCH'
    n0=before.get('dom_unique_count')
    n1=after.get('dom_unique_count')
    if type(n0) is not int or type(n1) is not int:
        return 'UNVERIFIED_DOM_COUNTS'
    if n1>32 and n1>n0 and after.get('matched_unique_count',0)>32:
        return 'CONTROL_EXPANDED_ROUTE_MATCHED_DOM_BEYOND_32'
    if n1>n0:
        return 'CONTROL_CHANGED_DOM_BUT_NEW_ROWS_UNCORRELATED'
    if request_count>0:
        return 'CONTROL_REQUESTED_DATA_WITHOUT_DOM_EXPANSION'
    return 'CONTROL_DID_NOT_EXPAND_DOM_IN_BOUNDED_OBSERVATION'


async def capture(browser,name,region,options):
    ctx=await browser.new_context(locale='ko-KR',viewport={'width':1280,'height':850})
    page=await ctx.new_page()
    page.set_default_timeout(options.timeout*1000)
    net=v411.NetworkRecorder()
    ctx.on('request',net.on_request)
    ctx.on('response',net.on_response)
    out={'context':name,'region':region,'status':'INCOMPLETE',
         'filter_route_correlated':False,'filtered':None,'scroll':None,
         'controls':None,'selection':None,'click':{'status':'NOT_ATTEMPTED'},
         'access_restricted':False,'collector_error_count':0}
    try:
        res=await page.goto(core.search_url('HDD',core.BY_KEY[region]),
                            wait_until='domcontentloaded',timeout=options.timeout*1000)
        if not res or res.status!=200 or core.region_id_in_url(page.url)!=core.BY_KEY[region]['id']:
            raise RuntimeError('INVALID_BASELINE')
        await page.wait_for_timeout(options.settle_ms)
        await net.drain()
        args=SimpleNamespace(keyword='HDD',regions={'target':dict(core.BY_KEY[region])},
            category_id=1,category_name=v46.CATALOG[1],
            available_only=True,min_price=0,max_price=50000,
            settle_ms=options.settle_ms,timeout=options.timeout)
        raw=v412.CorrelatedRouteRows()
        net.phase='FILTER_APPLY'
        page.on('response',raw.hook)
        try:
            stage,blocked,_=await v48.capture_apply(page,args,name,'target',
                                                      'cap_50000',secrets.token_bytes(32))
        finally:
            page.remove_listener('response',raw.hook)
            await raw.drain()
        await net.drain()
        if blocked or net.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
        out['filter_route_correlated']=bool(stage.get('matched_route_count',0)>0
            and stage.get('price_url_shape_observed') and stage.get('region_ok')
            and stage.get('ui_selected') and
            core.region_id_in_url(page.url)==core.BY_KEY[region]['id'])
        if not out['filter_route_correlated']:
            raise RuntimeError('FILTER_ROUTE_UNVERIFIED')
        correlated=raw.matched(stage,region)
        if not correlated or raw.errors:
            raise RuntimeError('CORRELATED_ROUTE_BODY_MISSING')
        route_rows=correlated['urls']
        route_count=[x.get('response_shape',{}).get('search_route_count')
                     for x in net.events if x['kind']=='SEARCH_ROUTE' and x['phase']=='FILTER_APPLY']
        if not route_count or route_count[-1]!=len(route_rows):
            raise RuntimeError('ROUTE_BODY_COUNT_MISMATCH')
        dom,_=await v46.snap(page)
        if dom.get('challenge') or dom.get('login_wall'):
            raise RuntimeError('ACCESS_RESTRICTION')
        out['filtered']=compare_phase(route_rows,dom)
        out['scroll']=await scroll_to_end(page,net,options.settle_ms)
        if out['scroll']['access_restricted']:
            raise RuntimeError('ACCESS_RESTRICTION')
        bottom_dom,_=await v46.snap(page)
        out['after_scroll']=compare_phase(route_rows,bottom_dom)
        out['controls']=out['scroll']
        decision=select_control(out['scroll'])
        out['selection']=decision
        if decision['status']!='READY_TO_CLICK':
            out['click']={'status':'NOT_CLICKED_'+decision['status']}
            out['status']='CAPTURED_DISCOVERY_ONLY'
        else:
            # Revalidate the actual observed control before the only allowed click.
            check=select_control(await observed_controls(page))
            if check!=decision:
                raise RuntimeError('CONTROL_CHANGED_BEFORE_CLICK')
            count_before=len(net.events)
            before_url=page.url
            net.phase='MORE_CONTROL_CLICK'
            if decision['kind']=='BUTTON':
                loc=page.locator('button').nth(decision['control_index'])
            else:
                loc=page.locator('a[href]').nth(decision['control_index'])
            await loc.click(timeout=min(6000,options.timeout*1000))
            await page.wait_for_timeout(options.settle_ms)
            await net.drain()
            after_dom,_=await v46.snap(page)
            if after_dom.get('challenge') or after_dom.get('login_wall') or net.blocked:
                raise RuntimeError('ACCESS_RESTRICTION')
            after_relation=compare_phase(route_rows,after_dom)
            # UI is still the same search filter. Do not persist the URL itself.
            from daangn_v4_5_evidence import public_url
            prev=public_url(before_url).get('public_params') or {}
            curr=public_url(page.url).get('public_params') or {}
            filter_persisted=bool(prev and all(curr.get(k)==prev.get(k)
                                  for k in ('q','in','category_id','only_on_sale','price'))
                                  and core.region_id_in_url(page.url)==core.BY_KEY[region]['id'])
            new_events=net.events[count_before:]
            request_count=sum(x['resource_type'] in ('fetch','xhr') for x in new_events)
            verdict=classify_click(out['after_scroll'],after_relation,
                                   bool(route_rows),filter_persisted=filter_persisted,
                                   blocked=net.blocked,request_count=request_count)
            out['click']={'status':verdict,'performed':True,'control_kind':decision['kind'],
                          'before_dom_unique':out['after_scroll']['dom_unique_count'],
                          'after_dom_unique':after_relation['dom_unique_count'],
                          'after_correlated_route_count':after_relation['matched_unique_count'],
                          'new_first_party_xhr_fetch':request_count,
                          'same_search_filter':filter_persisted,
                          'search_route_requests':sum(x['kind']=='SEARCH_ROUTE' for x in new_events)}
            out['status']='CAPTURED_CLICK_OBSERVED' if verdict not in (
                'STOP_ACCESS_RESTRICTION','UNVERIFIED_FILTER_OR_REGION_CHANGED',
                'UNVERIFIED_ORIGINAL_ROUTE_MISMATCH') else 'INCONCLUSIVE_AFTER_CLICK'
    except Exception as exc:
        text=str(exc)
        whitelist={'ACCESS_RESTRICTION','INVALID_BASELINE','FILTER_ROUTE_UNVERIFIED',
                   'CORRELATED_ROUTE_BODY_MISSING','ROUTE_BODY_COUNT_MISMATCH',
                   'CONTROL_CHANGED_BEFORE_CLICK'}
        out['status']='STOP_'+type(exc).__name__
        out['error_type']=text if text in whitelist else type(exc).__name__
    finally:
        await net.drain()
        out['network_event_count']=len(net.events)
        out['collector_error_count']=net.errors
        out['network_overflow']=net.overflow
        out['access_restricted']=net.blocked or out.get('error_type')=='ACCESS_RESTRICTION'
        await ctx.close()
    return out


def evaluate(rows):
    complete=len(rows)==3 and all(r.get('status') in (
        'CAPTURED_DISCOVERY_ONLY','CAPTURED_CLICK_OBSERVED') for r in rows)
    valid=complete and all(r.get('filter_route_correlated') and
          not r.get('access_restricted') and
          not r.get('network_overflow') and
          r.get('collector_error_count')==0 and
          (r.get('scroll') or {}).get('at_page_bottom') for r in rows)
    clicks=[r.get('click',{}).get('status') for r in rows]
    before32=bool(valid and all((r.get('filtered') or {}).get('classification')==
        'FIRST_32_LOADER_ITEMS_PRESENT_IN_DOM' and
        (r.get('after_scroll') or {}).get('dom_unique_count')==32 for r in rows))
    if any(r.get('access_restricted') for r in rows):
        status='STOP_ACCESS_RESTRICTION'
    elif not valid:
        status='INCONCLUSIVE_INCOMPLETE_OR_TRUNCATED'
    elif any(c=='CONTROL_EXPANDED_ROUTE_MATCHED_DOM_BEYOND_32' for c in clicks):
        status='OBSERVED_MORE_CONTROL_RELEASES_32_WINDOW'
    elif all(c=='NOT_CLICKED_NO_NAMED_MORE_CONTROL_OBSERVED' for c in clicks):
        status='NO_NAMED_MORE_CONTROL_IN_BOUNDED_SEARCH_UI'
    elif all(c and c.startswith('NOT_CLICKED_') for c in clicks):
        status='MORE_CONTROL_UNAVAILABLE_OR_UNSAFE_TO_TEST'
    elif all(c=='CONTROL_DID_NOT_EXPAND_DOM_IN_BOUNDED_OBSERVATION' for c in clicks):
        status='CLICKED_MORE_CONTROL_WITHOUT_DOM_EXPANSION'
    else:
        status='INCONCLUSIVE_MIXED_MORE_CONTROL_RESULTS'
    return {'status':status,'capture_complete':valid,'contexts_expected':3,
        'contexts_captured':sum(r.get('status','').startswith('CAPTURED_') for r in rows),
        'filtered_first_32_baseline':before32,
        'named_controls':[r.get('controls',{}).get('named_candidate_count') for r in rows],
        'actionable_controls':[r.get('controls',{}).get('actionable_count') for r in rows],
        'per_context_click_verdicts':clicks,
        'global_more_control_absence_proven':False,
        'backend_fixed_cap_proven':False,
        'all_results_exhausted_proven':False,
        'approved_listings':0}


def report(doc):
    e=doc['evaluation']
    lines=['# v4.13 search UI more-control experiment','',
           f"- Status: **{e['status']}**; complete: **{e['capture_complete']}**",
           f"- Filtered first-32 reproduced: {e['filtered_first_32_baseline']}",'',
           '| Context | Route | DOM after scroll | Bottom | Named controls | Actionable | Click outcome |',
           '|---|---:|---:|---|---:|---:|---|']
    for r in doc['contexts']:
        lines.append('| '+ ' | '.join(map(str,[
            r.get('context'),(r.get('filtered') or {}).get('loader_article_count'),
            (r.get('after_scroll') or {}).get('dom_unique_count'),
            (r.get('controls') or {}).get('at_page_bottom'),
            (r.get('controls') or {}).get('named_candidate_count'),
            (r.get('controls') or {}).get('actionable_count'),
            (r.get('click') or {}).get('status')]))+' |')
    lines+=['','## Limits',
            '- A negative result covers exact/near labels and accessible elements in three bounded public search UIs only.',
            '- Other labels, viewport sizes, logged-in states, or later website versions are outside the observation.',
            '- Only real, uniquely identified search-result-adjacent controls may be clicked. No fabricated cursor/page calls.',
            '- URL, DOM text, raw listings, response bodies and session identifiers were not written.',
            '- This audit never approves listings or proves a fixed backend result cap.','']
    return '\n'.join(lines)


async def run(options):
    rows=[]
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=not options.headed)
            try:
                for name,region in [('cheonan_a','cheonan'),
                                    ('asan_control','asan'),
                                    ('cheonan_b','cheonan')]:
                    row=await capture(browser,name,region,options)
                    rows.append(row)
                    print('v4.13',name,row['status'],
                          'controls',(row.get('controls') or {}).get('named_candidate_count'),
                          'click',(row.get('click') or {}).get('status'))
                    if row.get('status','').startswith('STOP_') or row.get('access_restricted'):
                        break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as exc:
        rows.append({'context':'browser','status':'STOP_'+type(exc).__name__,
                     'access_restricted':False})
    evaluation_result=evaluate(rows)
    doc={'version':'4.13','utc_time':now(),'profile':{
        'keyword':'HDD','target':'cheonan','control':'asan',
        'price_max_krw':50000,'owner_approved_only':True},
        'evaluation':evaluation_result,'contexts':rows,
        'approved_listings':[],'raw_urls_saved':False}
    options.output_dir.mkdir(parents=True,exist_ok=True)
    (options.output_dir/'v413_more_results.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (options.output_dir/'v413_more_report.md').write_text(report(doc),encoding='utf-8')
    (options.output_dir/'v413_limited_accept.json').write_text('{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    print('v4.13 result',evaluation_result['status'])
    return 0 if evaluation_result['capture_complete'] else 2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=Path('v413_output'))
    parser.add_argument('--headed',action='store_true')
    parser.add_argument('--timeout',type=int,default=25)
    parser.add_argument('--settle-ms',type=int,default=1600)
    args=parser.parse_args()
    args.output_dir=args.output_dir.resolve()
    args.timeout=max(15,min(args.timeout,45))
    args.settle_ms=max(800,min(args.settle_ms,3500))
    return asyncio.run(run(args))


if __name__=='__main__':
    raise SystemExit(main())
