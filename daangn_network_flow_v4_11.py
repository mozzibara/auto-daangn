# -*- coding: utf-8 -*-
"""v4.11 passive public search browser network-flow audit; no synthetic paging."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

import daangn_v4_1_core as core
import daangn_browser_v4_6 as v46
import daangn_price_bands_v4_8 as v48
import daangn_route_structure_v4_10 as st

MAX_EVENTS = 160
MAX_JSON_RESPONSES = 60
COLLECTIONS = {'items', 'results', 'listings', 'products', 'articles',
               'buysellarticles', 'edges', 'nodes', 'data'}
WRAPPERS = {'data', 'meta', 'pagination', 'pageinfo', 'response', 'result', 'search'}
PAGE_NAMES = set(st.TOTAL_KEYS | st.MORE_KEYS | st.CURSOR_KEYS | st.PAGE_KEYS |
                 st.CONTINUATION_KEYS)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def request_info(url, resource_type):
    """The response never contains raw paths, query values or opaque cursor tokens."""
    if resource_type not in ('fetch', 'xhr', 'document'):
        return None
    try:
        p = urlsplit(url)
        host = p.hostname or ''
        if p.scheme != 'https' or not (host == 'daangn.com' or host.endswith('.daangn.com')):
            return None
        origin_class = 'search_origin' if host == 'www.daangn.com' else 'daangn_owned_origin'
        pairs = parse_qsl(p.query, keep_blank_values=True, max_num_fields=100)
        if origin_class != 'search_origin':
            kind = 'DAANGN_SUBDOMAIN_REQUEST'
        elif p.path == core.SEARCH_PATH:
            kind = 'SEARCH_ROUTE' if core._is_search_route_response(url) else 'SEARCH_DOCUMENT'
        elif p.path == core.REGION_API:
            kind = 'REGION_API'
        elif p.path.startswith(('/api/', '/kr/api/')):
            kind = 'OTHER_API'
        else:
            kind = 'OTHER_FIRST_PARTY'
        fields = [{'key': k, **st.scalar_description(k, v)}
                  for k, v in pairs if k.lower() in PAGE_NAMES and st.safe_key(k)][:20]
        return {'kind':kind, 'resource_type':resource_type, 'origin_class':origin_class,
                'endpoint_sha256_16': hashlib.sha256((host+p.path).encode()).hexdigest()[:16],
                'query_pagination_fields':fields,
                'has_search_query':any(k=='q' for k,v in pairs),
                'has_region_query':any(k=='in' for k,v in pairs),
                'has_price_query':any(k=='price' for k,v in pairs)}
    except (ValueError, TypeError):
        return None


def generic_json_shape(raw):
    """Iterate dictionaries, never visit listing arrays or their individual records."""
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError, TypeError):
        return {'status':'NON_JSON_PAYLOAD','pagination_fields':[],'collections':[]}
    if not isinstance(obj, (dict, list)):
        return {'status':'NON_CONTAINER','pagination_fields':[],'collections':[]}
    fields, collections, stack, nodes = [], [], [(obj, (), 0)], 0
    while stack and nodes < 240 and len(fields)<24 and len(collections)<16:
        value, path, depth = stack.pop()
        nodes+=1
        if depth>5 or not isinstance(value,dict):
            continue
        for key, child in list(value.items())[:80]:
            if not st.safe_key(key):
                continue
            if st.PAGINATION.fullmatch(key):
                fields.append({'path':'.'.join(path+(key,)),'key':key,
                               **st.scalar_description(key,child)})
            if isinstance(child,list) and key.lower() in COLLECTIONS:
                collections.append({'key':key,'length':len(child)})
            elif isinstance(child,dict):
                safe_segment = key.lower() if key.lower() in WRAPPERS else 'wrapper'
                stack.append((child,path+(safe_segment,),depth+1))
    return {'status':'JSON_SHAPE_CAPTURED', 'pagination_fields':fields[:24],
            'collections':collections[:16], 'nodes_inspected':nodes,
            'traversal_truncated':bool(stack)}


def inspect_json(raw, kind):
    if kind != 'SEARCH_ROUTE':
        return generic_json_shape(raw)
    obj=st.inspect_payload(raw)
    flag=st.summary_flags(obj)
    return {'status':obj.get('status'), 'search_route_count':obj.get('raw_articles_count'),
            'loader_depth':obj.get('loader_depth'),
            'pagination_fields':obj.get('pagination_fields',[])[:30],
            'pagination_status':flag.get('status'),
            'explicit_window_signal':bool(flag.get('explicit_window_signal')),
            'client_cap_truncated':obj.get('client_extraction_cap_reached')}


def signals(event):
    shape=event.get('response_shape') or {}
    params=event.get('query_pagination_fields') or []
    fields=params+(shape.get('pagination_fields') or [])
    continuation=any((x['key'].lower() in st.MORE_KEYS and x.get('value') is True)
                     or (x['key'].lower() in st.CONTINUATION_KEYS and x.get('present') is True)
                     for x in fields)
    return {'pagination_metadata_present':bool(fields),
            'continuation_signal':continuation,
            'query_pagination_present':bool(params)}


class NetworkRecorder:
    def __init__(self):
        self.phase='LOAD'
        self.events=[]
        self.index={}
        self.tasks=set()
        self.body_count=0
        self.overflow=False
        self.blocked=False
        self.errors=0

    def on_request(self, request):
        try:
            item=request_info(request.url,request.resource_type)
            if item is None:
                return
            if len(self.events)>=MAX_EVENTS:
                self.overflow=True
                return
            item.update({'phase':self.phase,'status':None,'body_sha256':None,
                         'response_shape':None})
            self.index[request]=len(self.events)
            self.events.append(item)
        except Exception:
            self.errors+=1

    def on_response(self, response):
        try:
            i=self.index.get(response.request)
            if i is None:
                return
            item=self.events[i]
            item['status']=response.status
            if response.status in core.BLOCK_STATUS:
                self.blocked=True
            if response.status!=200 or item['resource_type'] not in ('fetch','xhr'):
                return
            ctype=str(response.headers.get('content-type','')).split(';')[0].lower()
            if 'json' not in ctype and 'remix' not in ctype:
                return
            if self.body_count>=MAX_JSON_RESPONSES:
                self.overflow=True
                return
            size=response.headers.get('content-length','')
            if size.isdigit() and int(size)>core.MAX_BODY:
                item['response_shape']={'status':'OVERSIZE_SKIPPED'}
                return
            self.body_count+=1

            async def inspect():
                try:
                    raw=await asyncio.wait_for(response.body(),timeout=12)
                    if len(raw)>core.MAX_BODY:
                        item['response_shape']={'status':'OVERSIZE_SKIPPED'}
                    else:
                        item['body_sha256']=hashlib.sha256(raw).hexdigest()
                        item['response_shape']=inspect_json(raw,item['kind'])
                except Exception:
                    self.errors+=1
                    item['response_shape']={'status':'RESPONSE_INSPECTION_FAILED'}
            task=asyncio.create_task(inspect())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except Exception:
            self.errors+=1

    async def drain(self):
        if self.tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*list(self.tasks),return_exceptions=True),timeout=15)
            except asyncio.TimeoutError:
                self.errors+=1

    def sanitized(self):
        return [{**e,'signals':signals(e)} for e in self.events]


async def dom_shape(page):
    """Return counts only: no links, DOM text, HTML, IDs, screenshots or cookies."""
    obj=await page.evaluate("""() => {
       let n=0;
       for(const a of document.querySelectorAll('a[href]')){
         try {
           const u=new URL(a.href,location.href);
           if(u.hostname==='www.daangn.com' &&
               /^\\/kr\\/buy-sell\\/[^/]+-[A-Za-z0-9]{10,}\\/?$/.test(u.pathname)) n++;
         }catch{}
       }
       const t=(document.body?.innerText||'').slice(0,6000);
       return {anchors:n,height:Math.round(document.documentElement.scrollHeight),
               y:Math.round(window.scrollY),
               restricted:/captcha|verify you are human|access denied|unusual traffic|비정상적인 접근|자동화된 접근|로그인이 필요합니다|로그인 후 이용/i.test(t)};
    }""")
    return {'listing_anchor_count':min(int(obj['anchors']),999999),
            'document_height':min(int(obj['height']),9999999),
            'scroll_y':min(int(obj['y']),9999999),
            'restricted':bool(obj['restricted'])}


async def scroll(page,recorder,phase,settle_ms,steps):
    recorder.phase=phase
    before=await dom_shape(page)
    if before['restricted']:
        raise RuntimeError('ACCESS_RESTRICTION')
    for _ in range(steps):
        await page.mouse.wheel(0,1450)
        await page.wait_for_timeout(max(350,min(950,settle_ms//2)))
        if recorder.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
    await page.wait_for_timeout(settle_ms)
    await recorder.drain()
    after=await dom_shape(page)
    if after['restricted'] or recorder.blocked:
        raise RuntimeError('ACCESS_RESTRICTION')
    return {'steps':steps,'before':before,'after':after}


async def capture(browser,name,region,options):
    context=await browser.new_context(locale='ko-KR',viewport={'width':1280,'height':850})
    page=await context.new_page()
    page.set_default_timeout(options.timeout*1000)
    rec=NetworkRecorder()
    context.on('request',rec.on_request)
    context.on('response',rec.on_response)
    row={'context':name,'region':region,'status':'NOT_STARTED','http_status':None,
         'region_ok':False,'initial_scroll':None,'filtered_scroll':None,
         'filter':{'status':'NOT_ATTEMPTED'},'events':[]}
    try:
        response=await page.goto(core.search_url('HDD',core.BY_KEY[region]),
                                 wait_until='domcontentloaded',timeout=options.timeout*1000)
        row['http_status']=response.status if response else None
        if row['http_status']!=200:
            raise RuntimeError('BASELINE_HTTP_INVALID')
        await page.wait_for_timeout(options.settle_ms)
        await rec.drain()
        row['region_ok']=core.region_id_in_url(page.url)==core.BY_KEY[region]['id']
        if not row['region_ok']:
            raise RuntimeError('REGION_MISMATCH')
        if (await dom_shape(page))['restricted'] or rec.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
        row['initial_scroll']=await scroll(page,rec,'SCROLL_INITIAL',options.settle_ms,options.scroll_steps)
        rec.phase='FILTER_APPLY'
        args=SimpleNamespace(keyword='HDD', regions={'target':dict(core.BY_KEY[region])},
            category_id=1,category_name=v46.CATALOG[1],
            available_only=True,min_price=0,max_price=50000,
            settle_ms=options.settle_ms,timeout=options.timeout)
        try:
            stage,blocked,_=await v48.capture_apply(page,args,name,'target','cap_50000',secrets.token_bytes(32))
            await rec.drain()
            ok=bool(stage.get('matched_route_count',0)>0 and
                    stage.get('price_url_shape_observed') and stage.get('region_ok')
                    and stage.get('ui_selected'))
            row['filter']={'status':'CORRELATED_FILTER_ROUTE' if ok else 'FILTER_UNVERIFIED',
                           'matched_route_count':min(int(stage.get('matched_route_count',0)),99),
                           'ui_selected':bool(stage.get('ui_selected')),
                           'region_ok':bool(stage.get('region_ok')),
                           'strict_listing_acceptance':False}
            if blocked or rec.blocked:
                raise RuntimeError('ACCESS_RESTRICTION')
        except RuntimeError:
            raise
        except Exception as exc:
            row['filter']={'status':'FILTER_UNVERIFIED_'+type(exc).__name__}
        if row['filter']['status']=='CORRELATED_FILTER_ROUTE':
            row['filtered_scroll']=await scroll(page,rec,'SCROLL_FILTERED',options.settle_ms,options.scroll_steps)
        row['status']='CAPTURED' if row['filtered_scroll'] else 'PARTIAL_FILTER_UNVERIFIED'
    except Exception as exc:
        row['status']='STOP_'+type(exc).__name__
        msg=str(exc)
        row['error_type']=msg if msg in ('ACCESS_RESTRICTION','REGION_MISMATCH','BASELINE_HTTP_INVALID') else type(exc).__name__
    finally:
        context.remove_listener('request',rec.on_request)
        context.remove_listener('response',rec.on_response)
        await rec.drain()
        row['events']=rec.sanitized()
        row['network_overflow']=rec.overflow
        row['collector_errors']=rec.errors
        row['access_blocked']=rec.blocked
        await context.close()
    return row


def evaluation(rows):
    events=[event for row in rows for event in row.get('events',[])]
    scroll_events=[e for e in events if e.get('phase') in ('SCROLL_INITIAL','SCROLL_FILTERED')
                   and e.get('resource_type') in ('xhr','fetch')]
    nonroute=[e for e in scroll_events if e['kind'] not in ('SEARCH_ROUTE','SEARCH_DOCUMENT')]
    candidates=[e for e in nonroute if
        any(c['length']>0 for c in (e.get('response_shape') or {}).get('collections',[]))]
    routes=[e for e in scroll_events if e['kind']=='SEARCH_ROUTE']
    continuations=[e for e in scroll_events if e['signals']['continuation_signal']]
    parameters=[e for e in scroll_events if e['signals']['query_pagination_present']]
    complete=len(rows)==3 and all(row.get('status')=='CAPTURED' for row in rows)
    truncated=any(row.get('network_overflow') or row.get('collector_errors') for row in rows)
    blocked=any(row.get('access_blocked') or row.get('error_type')=='ACCESS_RESTRICTION' for row in rows)
    if blocked:
        status='STOP_ACCESS_RESTRICTION'
    elif not complete or truncated:
        status='INCONCLUSIVE_INCOMPLETE_OR_TRUNCATED'
    elif parameters or continuations:
        status='PAGINATION_SIGNAL_ON_OBSERVED_SCROLL_REQUEST'
    elif candidates:
        status='NON_ROUTE_JSON_COLLECTION_ON_SCROLL'
    elif routes:
        status='SEARCH_ROUTE_ON_SCROLL'
    else:
        status='NO_ADDITIONAL_SEARCH_DATA_REQUEST_OBSERVED_IN_BOUNDED_FLOW'
    return {'status':status,'capture_complete':complete and not truncated and not blocked,
            'contexts_expected':3,'contexts_captured':sum(row.get('status')=='CAPTURED' for row in rows),
            'first_party_requests':len(events),'scroll_fetch_xhr_requests':len(scroll_events),
            'distinct_scroll_endpoint_fingerprints':len({e['endpoint_sha256_16'] for e in scroll_events}),
            'nonroute_scroll_requests':len(nonroute),'nonroute_collection_candidates':len(candidates),
            'scroll_route_requests':len(routes),'scroll_pagination_param_requests':len(parameters),
            'scroll_continuation_signals':len(continuations),
            'global_endpoint_absence_proven':False,'fixed_server_cap_proven':False,
            'complete_result_set_proven':False,'approved_listing_count':0}


def report(doc):
    a=doc['evaluation']
    lines=['# v4.11 public browser network-flow observations','',
           f"- Verdict: **{a['status']}**; complete: **{a['capture_complete']}**",
           f"- First-party requests: {a['first_party_requests']}; scroll fetch/XHR: {a['scroll_fetch_xhr_requests']}",
           f"- Non-Route scroll requests: {a['nonroute_scroll_requests']}; JSON collection candidates: {a['nonroute_collection_candidates']}",
           f"- Search Route on scroll: {a['scroll_route_requests']}; pagination params: {a['scroll_pagination_param_requests']}; continuation: {a['scroll_continuation_signals']}",
           '','| Context | State | Initial anchors before/after | Filter | Filtered anchors before/after |',
           '|---|---|---|---|---|']
    def anchor(row,name):
        s=row.get(name)
        if not s:return 'not observed'
        return str(s['before']['listing_anchor_count'])+'/'+str(s['after']['listing_anchor_count'])
    for r in doc['contexts']:
        lines.append(f"| {r['context']} | {r['status']} | {anchor(r,'initial_scroll')} | {r['filter']['status']} | {anchor(r,'filtered_scroll')} |")
    lines+=['','- Passive request-time correlation is not proof of scrolling causing a backend page load.',
            '- No cursor replay, speculative endpoint calls, raw URLs, response bodies, listing identifiers or credentials.',
            '- Absence within bounded gestures does not establish the global absence of pagination.',
            '- No fixed server cap is proven. No listings are approved or exported.','']
    return '\n'.join(lines)


async def run(args):
    rows=[]
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(headless=not args.headed)
            try:
                for name,region in (('cheonan_a','cheonan'),('asan_control','asan'),('cheonan_b','cheonan')):
                    row=await capture(browser,name,region,args)
                    rows.append(row)
                    print('v4.11 context',name,row['status'],'events',len(row['events']))
                    if row['status'].startswith('STOP_') or row.get('access_blocked'):
                        break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as exc:
        rows.append({'context':'browser','region':'unknown',
                     'status':'STOP_'+type(exc).__name__,
                     'filter':{'status':'NOT_ATTEMPTED'},'events':[]})
    analysis=evaluation(rows)
    doc={'version':'4.11','time_utc':now(),
         'design':{'target':'cheonan','control':'asan','keyword':'HDD',
                   'ui_price_profile':'cap_50000','scroll_steps':args.scroll_steps,
                   'passive_observation_only':True},
         'evaluation':analysis,'contexts':rows,
         'credentials_stored':False,'approved_listings':[]}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'v411_network_results.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output_dir/'v411_network_report.md').write_text(report(doc),encoding='utf-8')
    (args.output_dir/'v411_limited_accept.json').write_text('{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    print('v4.11',analysis['status'],'complete',analysis['capture_complete'])
    return 0 if analysis['capture_complete'] else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v411_output'))
    p.add_argument('--headed',action='store_true')
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--scroll-steps',type=int,default=8)
    args=p.parse_args()
    args.output_dir=args.output_dir.resolve()
    args.timeout=max(15,min(45,args.timeout))
    args.settle_ms=max(800,min(3500,args.settle_ms))
    args.scroll_steps=max(2,min(12,args.scroll_steps))
    return asyncio.run(run(args))


if __name__=='__main__':
    raise SystemExit(main())
