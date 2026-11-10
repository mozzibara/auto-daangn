# -*- coding: utf-8 -*-
"""v4.12 public UI: locate the 270-ish loader vs 32 DOM listing discrepancy.

Research only: never export listing links, IDs, raw response JSON, screenshots,
cookies, DOM text, CSS selectors or secret cursor values. Matches are aggregated
inside the browser and only counts and integer rank statistics cross the boundary.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import daangn_v4_1_core as core
import daangn_browser_v4_6 as v46
import daangn_price_bands_v4_8 as v48
import daangn_network_flow_v4_11 as v411
import daangn_v4_5_evidence as ev
import daangn_route_structure_v4_10 as shape410

# The code executes inside the browser. No URL or identifier leaves this function.
RELATION_JS = r"""() => {
  const data = window.__remixContext?.state?.loaderData || {};
  const loader = data['routes/kr.search.buy-sell._index'] ||
    data[Object.keys(data).find(k => /search.*buy-sell/.test(k))] || null;
  const raw = Array.isArray(loader?.buySellArticles) ? loader.buySellArticles : null;
  const normalize = (href) => {
    if (typeof href !== 'string') return null;
    try {
      const u = new URL(href, location.href);
      if (u.protocol !== 'https:' || u.hostname !== 'www.daangn.com' ||
          !/^\/kr\/buy-sell\/[^/]+-[A-Za-z0-9]{10,}\/?$/.test(u.pathname)) return null;
      return u.pathname.replace(/\/$/, '') + '/';
    } catch { return null; }
  };
  const originRows = raw || [];
  const rawUrls = originRows.map(x => normalize(x?.href));
  const indexes = new Map();
  rawUrls.forEach((url, rank) => {
    if (url && !indexes.has(url)) indexes.set(url, rank);
  });
  const cardElements = [...document.querySelectorAll('a[href]')];
  const all = [];
  const visible = [];
  for (const element of cardElements) {
    const href = normalize(element.getAttribute('href'));
    if (!href) continue;
    all.push(href);
    const style = getComputedStyle(element);
    const shown = element.getClientRects().length > 0 &&
      style.display !== 'none' && style.visibility !== 'hidden';
    if (shown) visible.push(href);
  }
  const domUnique = [...new Set(all)];
  const visibleUnique = [...new Set(visible)];
  const ranks = domUnique.filter(u => indexes.has(u)).map(u => indexes.get(u));
  const sorted = [...ranks].sort((a,b)=>a-b);
  const first32 = new Set(rawUrls.slice(0,32).filter(Boolean));
  const last32 = new Set(rawUrls.slice(-32).filter(Boolean));
  const sameOrder = domUnique.every((url,i)=>i < rawUrls.length && url===rawUrls[i]);
  const prefixSet = domUnique.length === 32 && domUnique.every(u=>first32.has(u));
  const positions = sorted.length ? {
    minimum:sorted[0], maximum:sorted[sorted.length-1],
    median:sorted[Math.floor(sorted.length/2)],
    first_32:sorted.filter(x=>x<32).length,
    first_64:sorted.filter(x=>x<64).length,
    last_32:sorted.filter(x=>x>=Math.max(0,rawUrls.length-32)).length,
    contiguous_prefix:sorted.every((x,i)=>x===i),
    sample_first_8:sorted.slice(0,8),
    sample_last_8:sorted.slice(-8)
  } : null;
  const buttons=[...document.querySelectorAll('button,[role="button"],a')];
  const more = buttons.filter(e => /^(더\s*보기|더\s*불러오기|모두\s*보기|load\s*more|show\s*more)$/i
      .test((e.innerText || e.getAttribute('aria-label') || '').trim().slice(0,50)));
  const body = (document.body?.innerText || '').slice(0,6000);
  const restriction = /captcha|verify you are human|access denied|unusual traffic|비정상적인 접근|자동화된 접근|로그인이 필요합니다|로그인 후 이용/i.test(body);
  const articleArrayKind = raw ? 'ARRAY' : loader ? 'NO_ARRAY' : 'LOADER_MISSING';
  return {
    article_array_kind:articleArrayKind,
    loader_article_count:raw ? raw.length : null,
    raw_href_valid_count:rawUrls.filter(Boolean).length,
    raw_unique_href_count:indexes.size,
    raw_duplicate_href_count:rawUrls.filter(Boolean).length-indexes.size,
    raw_invalid_href_count:raw ? rawUrls.filter(x=>!x).length : null,
    loader_region_matches_page: String(loader?.searchRegion?.id ?? '') ===
      ((new URL(location.href)).searchParams.get('in') || '').split('-').at(-1),
    dom_anchor_count:all.length,dom_unique_count:domUnique.length,
    dom_visible_count:visible.length,dom_visible_unique_count:visibleUnique.length,
    matched_unique_count:ranks.length,dom_only_unique_count:domUnique.length-ranks.length,
    loader_not_in_dom_unique_count:indexes.size-ranks.length,
    same_order_as_loader_prefix:sameOrder,
    exactly_first_32_set:prefixSet,
    match_positions:positions,
    explicit_more_control_count:more.length,
    article_data_class:'loader_buySellArticles',
    restricted:restriction
  };
}""".strip()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def classify_snapshot(shape):
    if not isinstance(shape,dict) or shape.get('article_array_kind')!='ARRAY':
        return 'UNVERIFIED_LOADER'
    if shape.get('restricted'):
        return 'ACCESS_RESTRICTION'
    total=shape.get('loader_article_count')
    rendered=shape.get('dom_unique_count')
    matched=shape.get('matched_unique_count')
    if not all(type(x) is int for x in (total,rendered,matched)):
        return 'INVALID_COUNTS'
    if total<1 or rendered<1 or rendered>total or matched>rendered:
        return 'INCONCLUSIVE_COUNTS'
    if shape.get('raw_invalid_href_count') or shape.get('raw_duplicate_href_count'):
        return 'DUPLICATE_OR_INVALID_LOADER_IDENTIFIERS'
    if shape.get('dom_only_unique_count'):
        return 'MIXED_DOM_LISTINGS_NOT_ALL_FROM_LOADER'
    if total>rendered and matched==rendered:
        if shape.get('exactly_first_32_set') and rendered==32:
            return 'FIRST_32_LOADER_ITEMS_PRESENT_IN_DOM'
        if shape.get('match_positions',{}).get('contiguous_prefix') is True:
            return 'LOADER_PREFIX_PRESENT_IN_DOM'
        return 'SUBSET_OF_LOADER_PRESENT_IN_DOM'
    if total==rendered and matched==rendered:
        return 'FULL_LOADER_RENDERED'
    return 'INCONCLUSIVE_RELATION'


async def snapshot(page):
    return await page.evaluate(RELATION_JS)


async def scroll_and_snapshot(page,settle_ms):
    before=await snapshot(page)
    if before['restricted']:
        raise RuntimeError('ACCESS_RESTRICTION')
    for _ in range(8):
        await page.mouse.wheel(0,1450)
        await page.wait_for_timeout(max(350,min(900,settle_ms//2)))
    await page.wait_for_timeout(settle_ms)
    after=await snapshot(page)
    if after['restricted']:
        raise RuntimeError('ACCESS_RESTRICTION')
    return {'before':before,'after':after,'scroll_steps':8}


async def javascript_disabled_ssr(browser, observed_url, region, timeout):
    """Revisit only a UI-observed URL in an isolated no-JS browser: SSR anchors."""
    context=await browser.new_context(java_script_enabled=False,locale='ko-KR',
                                      viewport={'width':1280,'height':850})
    try:
        page=await context.new_page()
        response=await page.goto(observed_url,wait_until='domcontentloaded',timeout=timeout*1000)
        if not response or response.status!=200:
            return {'status':'SSR_HTTP_UNVERIFIED','http_status':response.status if response else None}
        if core.region_id_in_url(page.url)!=core.BY_KEY[region]['id']:
            return {'status':'SSR_REGION_MISMATCH'}
        # Counts via locator; do not evaluate on no-JavaScript page, and do not
        # read href values or HTML into Python.
        links=page.locator('a[href*="/kr/buy-sell/"]')
        return {'status':'SSR_OBSERVED','all_listing_anchors':await links.count()}
    except Exception as exc:
        return {'status':'SSR_UNVERIFIED_'+type(exc).__name__}
    finally:
        await context.close()




class CorrelatedRouteRows:
    """Hold actual response rows only in RAM; publish only aggregate statistics."""
    def __init__(self):
        self.events=[]
        self.tasks=set()
        self.errors=0

    def hook(self, response):
        try:
            if (response.status!=200 or
                    response.request.resource_type not in ('xhr','fetch') or
                    not core._is_search_route_response(response.url)):
                return
            ct=str(response.headers.get('content-type','')).lower()
            if 'json' not in ct and 'remix' not in ct:
                return
            size=response.headers.get('content-length','')
            if size.isdigit() and int(size)>core.MAX_BODY:
                self.errors+=1
                return

            async def collect():
                try:
                    raw=await asyncio.wait_for(response.body(),timeout=12)
                    if len(raw)>core.MAX_BODY:
                        self.errors+=1
                        return
                    struct=shape410.inspect_payload(raw)
                    parsed=ev.extract_model(raw)
                    if struct.get('status')!='SEARCH_LOADER_STRUCT_CAPTURED' or parsed is None:
                        self.errors+=1
                        return
                    articles=parsed.get('articles') or []
                    n=struct['raw_articles_count']
                    if n != len(articles):
                        # The extractor's 650-item cap must not silently pass.
                        self.errors+=1
                        return
                    urls=[core.normalized_listing(a.get('href')) for a in articles]
                    self.events.append({'sha256':hashlib.sha256(raw).hexdigest(),
                        'public_request':ev.public_url(response.url),
                        'count':n,'urls':urls})
                except Exception:
                    self.errors+=1
            task=asyncio.create_task(collect())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except Exception:
            self.errors+=1

    async def drain(self):
        if self.tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*list(self.tasks),
                                      return_exceptions=True),timeout=14)
            except asyncio.TimeoutError:
                self.errors+=1

    def matched(self, stage, region):
        expected=set(stage.get('matched_route_digest') or [])
        matches=[x for x in self.events if x['sha256'] in expected and
                 v48.matched_route({'public_request':x['public_request']},
                                   'cap_50000',core.BY_KEY[region])]
        return matches[-1] if matches else None


def route_relation(route_rows, dom_rows):
    """Exact order-preserving membership check, never return row identifiers."""
    source=[core.normalized_listing(u) for u in route_rows]
    dom=[core.normalized_listing(u) for u in dom_rows]
    source_valid=[x for x in source if x]
    dom_unique=list(dict.fromkeys(x for x in dom if x))
    index={}
    for i,value in enumerate(source):
        if value and value not in index:
            index[value]=i
    ranks=sorted(index[x] for x in dom_unique if x in index)
    first32=set(x for x in source[:32] if x)
    matched=len(ranks)
    positions=({'minimum':ranks[0],'maximum':ranks[-1],
        'median':ranks[len(ranks)//2],
        'first_32':sum(i<32 for i in ranks),
        'first_64':sum(i<64 for i in ranks),
        'last_32':sum(i>=max(0,len(source)-32) for i in ranks),
        'contiguous_prefix':all(i==v for i,v in enumerate(ranks)),
        'sample_first_8':ranks[:8],'sample_last_8':ranks[-8:]}
        if ranks else None)
    result={'article_array_kind':'ARRAY','loader_article_count':len(source),
        'raw_href_valid_count':len(source_valid),
        'raw_unique_href_count':len(index),
        'raw_duplicate_href_count':len(source_valid)-len(index),
        'raw_invalid_href_count':len(source)-len(source_valid),
        'dom_anchor_count':len(dom),
        'dom_unique_count':len(dom_unique),
        'dom_visible_count':len(dom),
        'dom_visible_unique_count':len(dom_unique),
        'matched_unique_count':matched,
        'dom_only_unique_count':len(dom_unique)-matched,
        'loader_not_in_dom_unique_count':len(index)-matched,
        'same_order_as_loader_prefix':dom_unique==source[:len(dom_unique)],
        'exactly_first_32_set':len(dom_unique)==32 and all(x in first32 for x in dom_unique),
        'match_positions':positions,
        'explicit_more_control_count':None,
        'article_data_class':'CORRELATED_ROUTE_RESPONSE',
        'restricted':False}
    result['classification']=classify_snapshot(result)
    return result


async def capture(browser,name,region,options,include_ssr=False):
    ctx=await browser.new_context(locale='ko-KR',viewport={'width':1280,'height':850})
    page=await ctx.new_page()
    page.set_default_timeout(options.timeout*1000)
    net=v411.NetworkRecorder()
    ctx.on('request',net.on_request)
    ctx.on('response',net.on_response)
    result={'context':name,'region':region,'status':'INCOMPLETE',
            'baseline':None,'filtered':None,'after_scroll':None,
            'repeat':None,'ssr':{'status':'NOT_REQUESTED'},'route_count':None,
            'filter_correlated':False,'error_type':None}
    try:
        response=await page.goto(core.search_url('HDD',core.BY_KEY[region]),
                                 wait_until='domcontentloaded',timeout=options.timeout*1000)
        if response is None or response.status!=200:
            raise RuntimeError('BASELINE_HTTP_INVALID')
        await page.wait_for_timeout(options.settle_ms)
        await net.drain()
        if core.region_id_in_url(page.url)!=core.BY_KEY[region]['id']:
            raise RuntimeError('REGION_MISMATCH')
        result['baseline']=await snapshot(page)
        if result['baseline']['restricted'] or net.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
        args=SimpleNamespace(keyword='HDD',regions={'target':dict(core.BY_KEY[region])},
             category_id=1,category_name=v46.CATALOG[1],
             available_only=True,min_price=0,max_price=50000,
             settle_ms=options.settle_ms,timeout=options.timeout)
        net.phase='FILTER_APPLY'
        raw_rec=CorrelatedRouteRows()
        page.on('response',raw_rec.hook)
        try:
            stage,blocked,_=await v48.capture_apply(page,args,name,'target',
                                  'cap_50000',secrets.token_bytes(32))
        finally:
            page.remove_listener('response',raw_rec.hook)
            await raw_rec.drain()
        await net.drain()
        if blocked or net.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
        result['filter_correlated']=bool(stage.get('matched_route_count',0)>0
             and stage.get('price_url_shape_observed') and stage.get('region_ok')
             and stage.get('ui_selected') and
             core.region_id_in_url(page.url)==core.BY_KEY[region]['id'])
        if not result['filter_correlated']:
            raise RuntimeError('FILTER_ROUTE_UNVERIFIED')
        route=[x for x in net.events if x['phase']=='FILTER_APPLY'
               and x['kind']=='SEARCH_ROUTE' and x['status']==200]
        if route:
            result['route_count']=(route[-1].get('response_shape') or {}).get('search_route_count')
        correlated=raw_rec.matched(stage,region)
        result['raw_route_collector_errors']=raw_rec.errors
        if not correlated or raw_rec.errors:
            raise RuntimeError('CORRELATED_RAW_ROUTE_MISSING')
        route_rows=correlated['urls']
        if result['route_count']!=len(route_rows):
            raise RuntimeError('ROUTE_RESPONSE_COUNT_MISMATCH')
        # window.__remixContext loaderData may be stale after SPA navigation:
        # keep its count independently, NEVER use its rows to rank filtered DOM.
        result['loader_state_after_apply']=await snapshot(page)
        if result['loader_state_after_apply']['restricted']:
            raise RuntimeError('ACCESS_RESTRICTION')
        dom,_=await v46.snap(page)
        result['filtered']=route_relation(route_rows,dom.get('dom_visible',[]))
        result['filtered']['browser_loader_count_after_apply']=result['loader_state_after_apply'].get('loader_article_count')
        result['filtered']['browser_loader_stale_count']=(
            result['route_count']!=result['loader_state_after_apply'].get('loader_article_count'))
        net.phase='SCROLL_FILTERED'
        result['after_scroll']=await scroll_and_snapshot(page,options.settle_ms)
        if net.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
        scrolled_dom,_=await v46.snap(page)
        result['after_scroll']['actual_route_relation']=route_relation(
            route_rows,scrolled_dom.get('dom_visible',[]))
        net.phase='REVISIT_FILTERED'
        observed_url=page.url
        if include_ssr:
            result['ssr']=await javascript_disabled_ssr(browser,observed_url,region,options.timeout)
        # Reload exactly the URL created by the real UI (no fabricated params).
        response=await page.goto(observed_url,wait_until='domcontentloaded',timeout=options.timeout*1000)
        if not response or response.status!=200:
            raise RuntimeError('REPEAT_HTTP_INVALID')
        await page.wait_for_timeout(options.settle_ms)
        repeated_state=await snapshot(page)
        if repeated_state['restricted'] or core.region_id_in_url(page.url)!=core.BY_KEY[region]['id']:
            raise RuntimeError('REPEAT_REGION_OR_ACCESS_INVALID')
        repeated_dom,_=await v46.snap(page)
        result['repeat']=route_relation(route_rows,repeated_dom.get('dom_visible',[]))
        result['repeat']['reloaded_browser_loader_count']=repeated_state.get('loader_article_count')
        result['repeat']['same_listing_set_as_filtered']=(set(dom.get('dom_visible',[]))==set(repeated_dom.get('dom_visible',[])))
        repeated_state['classification']=classify_snapshot(repeated_state)
        result['repeat_current_loader_projection']=repeated_state
        result['status']='CAPTURED'
    except Exception as exc:
        result['status']='STOP_'+type(exc).__name__
        msg=str(exc)
        allow={'ACCESS_RESTRICTION','REGION_MISMATCH','BASELINE_HTTP_INVALID',
               'FILTER_ROUTE_UNVERIFIED','ROUTE_LOADER_COUNT_NOT_CORRELATED',
               'REPEAT_HTTP_INVALID','REPEAT_REGION_OR_ACCESS_INVALID'}
        result['error_type']=msg if msg in allow else type(exc).__name__
    finally:
        await net.drain()
        result['network_error_count']=net.errors
        result['network_overflow']=net.overflow
        result['network_access_blocked']=net.blocked
        result['scroll_fetch_xhr_count']=sum(
            x['phase']=='SCROLL_FILTERED' and x['resource_type'] in ('fetch','xhr')
            for x in net.events)
        await ctx.close()
    for key in ('baseline','filtered','repeat'):
        if result.get(key) is not None:
            result[key]['classification']=classify_snapshot(result[key])
    if result.get('after_scroll'):
        for key in ('before','after'):
            result['after_scroll'][key]['classification']=classify_snapshot(result['after_scroll'][key])
    return result


def decide(rows):
    completed=len(rows)==3 and all(row['status']=='CAPTURED' for row in rows)
    complete=completed and all(row.get('filter_correlated') and
         row.get('route_count')==row['filtered'].get('loader_article_count') and
         not row.get('network_overflow') and row.get('network_error_count',0)==0 and
         not row.get('network_access_blocked') for row in rows)
    rows_ok=[row for row in rows if row['status']=='CAPTURED' and row.get('filtered')]
    classifications=[row['filtered'].get('classification') or classify_snapshot(row['filtered']) for row in rows_ok]
    stable=bool(complete and all(
        ((row.get('after_scroll') or {}).get('actual_route_relation') or row['after_scroll']['after']).get('dom_unique_count')==row['filtered']['dom_unique_count']
        and row['repeat']['dom_unique_count']==row['filtered']['dom_unique_count']
        and ((row.get('after_scroll') or {}).get('actual_route_relation') or row['after_scroll']['after']).get('matched_unique_count',row['filtered']['matched_unique_count'])==row['filtered']['matched_unique_count']
        and row['repeat'].get('matched_unique_count',row['filtered']['matched_unique_count'])==row['filtered']['matched_unique_count']
        for row in rows))
    filtered_prefix=bool(complete and all(
        (row['filtered'].get('classification') or classify_snapshot(row['filtered']))=='FIRST_32_LOADER_ITEMS_PRESENT_IN_DOM'
        and row['filtered'].get('dom_unique_count')==32 for row in rows))
    scroll_prefix=bool(filtered_prefix and all(
        (((row.get('after_scroll') or {}).get('actual_route_relation')
         or (row.get('after_scroll') or {}).get('after') or {}).get('classification')
         or classify_snapshot(((row.get('after_scroll') or {}).get('actual_route_relation')
               or (row.get('after_scroll') or {}).get('after') or {})))
          =='FIRST_32_LOADER_ITEMS_PRESENT_IN_DOM'
        and row.get('scroll_fetch_xhr_count',0)==0 for row in rows))
    revisit_prefix=bool(complete and all(
        (row.get('repeat_current_loader_projection') or {}).get('classification')
          =='FIRST_32_LOADER_ITEMS_PRESENT_IN_DOM' for row in rows))
    if any(row.get('network_access_blocked') or row.get('error_type')=='ACCESS_RESTRICTION' for row in rows):
        status='STOP_ACCESS_RESTRICTION'
    elif not complete:
        status='INCONCLUSIVE_INCOMPLETE_CAPTURE'
    elif filtered_prefix and scroll_prefix and (revisit_prefix or stable):
        status='REPRODUCED_FIRST_32_PER_RESPONSE_RENDER_WINDOW'
    elif filtered_prefix and scroll_prefix:
        status='FIRST_32_FILTERED_AND_SCROLL_CONFIRMED_REVISIT_UNVERIFIED'
    elif all(v in ('FIRST_32_LOADER_ITEMS_PRESENT_IN_DOM',
                   'LOADER_PREFIX_PRESENT_IN_DOM',
                   'SUBSET_OF_LOADER_PRESENT_IN_DOM') for v in classifications) and stable:
        status='REPRODUCED_CLIENT_SUBSET_RENDER_WINDOW'
    else:
        status='INCONCLUSIVE_DIFFERENT_RENDER_PATTERN'
    return {'status':status,'capture_complete':complete,
        'contexts_expected':3,'contexts_captured':len(rows_ok),
        'stable_dom_after_scroll_and_reload':stable,
        'filtered_first_32_reproduced':filtered_prefix,
        'same_response_scroll_prefix_reproduced':scroll_prefix,
        'fresh_reload_loader_prefix_reproduced':revisit_prefix,
        'same_listing_set_on_revisit':[x.get('repeat',{}).get('same_listing_set_as_filtered') for x in rows_ok],
        'observed_loader_counts':[x['filtered']['loader_article_count'] for x in rows_ok],
        'observed_dom_counts':[x['filtered']['dom_unique_count'] for x in rows_ok],
        'stale_browser_loader_after_apply':[x['filtered'].get('browser_loader_stale_count') for x in rows_ok],
        'classification_by_context':classifications,
        'ssr_no_js_observed':next((x['ssr'] for x in rows if x['ssr']['status']=='SSR_OBSERVED'),None),
        'fixed_backend_cap_proven':False,
        'literal_source_slice_32_proven':False,
        'all_search_items_rendered_proven':False,
        'approved_listing_count':0}


def make_report(doc):
    a=doc['evaluation']
    lines=['# v4.12 public search Route vs DOM render diagnostics','',
           f"- Verdict: **{a['status']}**; complete: **{a['capture_complete']}**",
           f"- Route loader item counts: {a['observed_loader_counts']}; DOM unique listing anchors: {a['observed_dom_counts']}",
           f"- Filtered first 32: {a['filtered_first_32_reproduced']}; same-response scroll prefix: {a['same_response_scroll_prefix_reproduced']}",
           f"- Fresh reload prefix: {a['fresh_reload_loader_prefix_reproduced']}; same listing set across reload: {a['same_listing_set_on_revisit']}",
           '', '| Context | Loader | DOM unique | DOM matched | First 32 | Max rank | Scroll DOM | Reload DOM | Classification |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for row in doc['contexts']:
        s=row.get('filtered') or {}
        p=s.get('match_positions') or {}
        after=(row.get('after_scroll') or {}).get('after') or {}
        repeat=row.get('repeat') or {}
        lines.append('| '+' | '.join(map(str,(
            row['context'],s.get('loader_article_count'),s.get('dom_unique_count'),
            s.get('matched_unique_count'),p.get('first_32'),p.get('maximum'),
            after.get('dom_unique_count'),repeat.get('dom_unique_count'),
            s.get('classification'))))+' |')
    lines+=['', '## Causal inference limits',
            '- Matching the first 32 loader entries to 32 DOM links localizes the discrepancy to the UI rendering path but cannot prove an actual source code slice(0,32).',
            '- A subset match with scattered ranks can indicate UI ranking/reordering, filtering, or another client projection. These remain hypotheses.',
            '- No direct API pagination is attempted. Backend fixed caps and hidden endpoints are not inferred.',
            '- No original listing URLs, hashed IDs, CSS or DOM content are retained. Research does not approve any listing.','']
    return '\n'.join(lines)


async def run(options):
    rows=[]
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=not options.headed)
            try:
                for name,region,ssr in (('cheonan_a','cheonan',True),
                                        ('asan_control','asan',False),
                                        ('cheonan_b','cheonan',False)):
                    row=await capture(browser,name,region,options,include_ssr=ssr)
                    rows.append(row)
                    print('v4.12',name,row['status'], 'route',row['route_count'],
                          'dom', (row.get('filtered') or {}).get('dom_unique_count'))
                    if row['status'].startswith('STOP_') or row['network_access_blocked']:
                        break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as exc:
        rows.append({'context':'browser','region':'unknown',
                     'status':'STOP_'+type(exc).__name__,
                     'ssr':{'status':'NOT_REQUESTED'},'network_access_blocked':False})
    analysis=decide(rows)
    doc={'version':'4.12','time_utc':now(),
         'scope':{'keyword':'HDD','target':'cheonan','control':'asan',
             'observed_filter':'cap_50000','research_only':True},
         'evaluation':analysis,'contexts':rows,
         'approved_listings':[], 'credentials_stored':False}
    options.output_dir.mkdir(parents=True,exist_ok=True)
    (options.output_dir/'v412_render_results.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (options.output_dir/'v412_render_report.md').write_text(make_report(doc),encoding='utf-8')
    (options.output_dir/'v412_limited_accept.json').write_text('{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    print('v4.12:',analysis['status'],'completed:',analysis['capture_complete'])
    return 0 if analysis['capture_complete'] else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v412_output'))
    p.add_argument('--headed',action='store_true')
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    args=p.parse_args()
    args.output_dir=args.output_dir.resolve()
    args.timeout=max(15,min(45,args.timeout))
    args.settle_ms=max(800,min(3500,args.settle_ms))
    return asyncio.run(run(args))


if __name__=='__main__':
    raise SystemExit(main())
