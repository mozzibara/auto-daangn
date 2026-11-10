# -*- coding: utf-8 -*-
"""Read-only bounded, privacy-safe structural probe of a public Remix search route.

Observe JSON *shape*, pagination-like field names and limited numeric/boolean
metadata. Never store raw response bodies, cursor values, listing links or tokens.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from urllib.parse import urlsplit, parse_qsl

import daangn_v4_1_core as core
import daangn_v4_5_evidence as ev

SAFE_KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
SECRET = re.compile(r'token|secret|auth|cookie|session|csrf|jwt|password|api.?key', re.I)
PAGINATION = re.compile(
    r'(?:^(?:after|before|cursor|next|previous|prev|page|pages|pageInfo|pagination|'
    r'offset|limit|perPage|pageSize|page_size|take|first|last|hasMore|hasNextPage|'
    r'hasPreviousPage|nextPage|nextCursor|previousCursor|endCursor|startCursor|'
    r'totalCount|totalItems|totalResults|totalPages|resultCount|itemCount|'
    r'countTotal|nextOffset|has_more|next_page|total_count)$)', re.I)
TOTAL_KEYS = {'totalcount','totalitems','totalresults','itemcount','counttotal','total_count'}
MORE_KEYS = {'hasmore','hasnextpage','has_more'}
CURSOR_KEYS = {'cursor','nextcursor','endcursor','startcursor','previouscursor','after','before'}
PAGE_KEYS = {'pagesize','page_size','perpage','limit','take','first','offset','page','totalpages','nextoffset','nextpage','next_page'}
SIZE_KEYS = {'pagesize','page_size','perpage','limit','take','first'}
CONTINUATION_KEYS = {'nextcursor','nextpage','next_page'}
MAX_NODES=360
MAX_PATH_DEPTH=7
MAX_BREADTH=14
MAX_OBSERVATIONS=36


def safe_key(k):
    return isinstance(k,str) and bool(SAFE_KEY.fullmatch(k)) and not SECRET.search(k)


def scalar_description(name, value):
    """Never expose cursor/opaque string bodies. Only bounded type/value evidence."""
    n=name.lower()
    if value is None:
        return {'type':'null','present':False}
    if isinstance(value,bool):
        return {'type':'bool','value':value}
    if isinstance(value,int) and not isinstance(value,bool) and 0<=value<=10_000_000_000:
        return {'type':'int','value':value}
    if isinstance(value,float) and value.is_integer() and 0<=value<=10_000_000_000:
        return {'type':'int','value':int(value)}
    if isinstance(value,str):
        # Numeric only for explicit count/page keys; never parse cursor payload.
        if n not in CURSOR_KEYS and n in TOTAL_KEYS|PAGE_KEYS and value.isascii() and re.fullmatch(r'\d{1,10}',value):
            return {'type':'decimal_string','value':int(value)}
        return {'type':'opaque_string','present':bool(value),'length':min(len(value),100_000)}
    if isinstance(value,list):
        return {'type':'array','length':len(value)}
    if isinstance(value,dict):
        return {'type':'object','field_count':min(len(value),10_000)}
    return {'type':type(value).__name__}


def inspect_payload(obj):
    """Return a bounded, non-identifying structural summary of a response JSON."""
    if isinstance(obj,(str,bytes)):
        try:obj=json.loads(obj)
        except (ValueError,UnicodeDecodeError,TypeError):return {'status':'NON_JSON_PAYLOAD'}
    if not isinstance(obj,(dict,list)):
        return {'status':'UNSUPPORTED_ROOT_TYPE','root_type':type(obj).__name__}
    found=[];checked=0
    stack=[(obj,(),0)]
    while stack and checked<MAX_NODES:
        v,path,depth=stack.pop();checked+=1
        if depth>MAX_PATH_DEPTH:continue
        if isinstance(v,dict):
            rows=v.get('buySellArticles')
            if isinstance(rows,list):
                found.append((v,path))
                # Never inspect any item data; only length.
                continue
            for key,child in list(v.items())[:120]:
                if isinstance(child,(dict,list)) and isinstance(key,str) and len(key)<=120 and not SECRET.search(key):
                    stack.append((child,path+(key,),depth+1))
        elif isinstance(v,list):
            for ix,child in enumerate(v[:MAX_BREADTH]):
                if isinstance(child,(dict,list)):
                    stack.append((child,path+(str(ix),),depth+1))
    if not found:
        return {'status':'SEARCH_LOADER_NOT_FOUND','root_type':type(obj).__name__,
                'nodes_inspected':checked,'traversal_truncated':bool(stack)}
    # Prefer a loader with currentFilters and searchRegion, as the existing v4.8 extractor does.
    found.sort(key=lambda pair:(isinstance(pair[0].get('currentFilters'),dict),
                                isinstance(pair[0].get('searchRegion'),dict)),reverse=True)
    loader,path=found[0]
    articles=loader['buySellArticles']
    fields=sorted(k for k in loader if safe_key(k))[:80]
    candidates=[]
    queue=[(loader,(),0)]
    m=0
    while queue and m<MAX_NODES and len(candidates)<MAX_OBSERVATIONS:
        node,nodepath,depth=queue.pop(0);m+=1
        if depth>4:continue
        if isinstance(node,dict):
            for k,val in list(node.items())[:100]:
                if not safe_key(k) or k=='buySellArticles':continue
                if PAGINATION.fullmatch(k):
                    candidates.append({'path':'.'.join(nodepath+(k,)),'key':k,'origin':'search_loader',
                                       **scalar_description(k,val)})
                if isinstance(val,dict) and len(queue)<MAX_NODES:
                    queue.append((val,nodepath+(k,),depth+1))
                elif isinstance(val,list) and k.lower() in ('pageinfo','pagination','edges','pages'):
                    for ix,member in enumerate(val[:MAX_BREADTH]):
                        if isinstance(member,dict):queue.append((member,nodepath+(k,str(ix)),depth+1))
    parent=obj
    # Ancestor metadata can be returned beside the loader. Keep only pagination-like fields.
    for ix,k in enumerate(path):
        if ix>MAX_PATH_DEPTH:break
        if isinstance(parent,dict):
            for f,val in list(parent.items())[:100]:
                if safe_key(f) and PAGINATION.fullmatch(f):
                    candidates.append({'path':'wrapper.'+'.'.join(tuple(x if safe_key(x) else 'route' for x in path[:ix])+(f,)),
                                       'key':f,'origin':'ancestor_ambiguous',**scalar_description(f,val)})
            parent=parent.get(k)
        elif isinstance(parent,list) and k.isdigit() and int(k)<len(parent):
            parent=parent[int(k)]
        else:break
    dedup=[];seen=set()
    for x in candidates[:MAX_OBSERVATIONS]:
        if x['path'] not in seen:dedup.append(x);seen.add(x['path'])
    return {'status':'SEARCH_LOADER_STRUCT_CAPTURED','root_type':type(obj).__name__,
            'loader_depth':len(path),'loader_keys':fields,
            'raw_articles_count':len(articles),
            'client_max_articles':core.MAX_ARTICLES,
            'client_extraction_cap_reached':len(articles)>core.MAX_ARTICLES,
            'pagination_fields':dedup,
            'pagination_field_count':len(dedup),
            'nodes_inspected':checked,'traversal_truncated':bool(stack)}


def header_observation(headers):
    """Only numeric totals and presence of Link next; not raw URLs/header secrets."""
    h={str(k).lower():v for k,v in (headers or {}).items()}
    out={'content_type':str(h.get('content-type','')).split(';')[0][:45],
         'link_header_present':'link' in h,
         'link_rel_next_observed':bool(re.search(r'rel\s*=\s*["\']?next\b',str(h.get('link','')),re.I))}
    for k in ('x-total-count','x-result-count','x-page-count','content-length'):
        v=str(h.get(k,'')).strip()
        out[k.replace('-','_')] = int(v) if re.fullmatch(r'\d{1,12}',v) else None
    return out


def summary_flags(struct):
    """Classify observed metadata; never claim a globally fixed server cap."""
    if (struct or {}).get('status')!='SEARCH_LOADER_STRUCT_CAPTURED':
        return {'status':'STRUCTURE_NOT_CAPTURED','explicit_window_signal':False,
                'possible_more_results':None,'reported_total':None,'reported_page_size':None,
                'backend_fixed_limit_proven':False}
    fields=struct.get('pagination_fields') or []
    # Ancestor wrapper siblings may describe a different response route.
    # Record them but only promote metadata rooted inside search loader.
    bound=[f for f in fields if f.get('origin')=='search_loader']
    count=struct.get('raw_articles_count')
    totals=[e['value'] for e in bound if e['key'].lower() in TOTAL_KEYS and e.get('type') in ('int','decimal_string')]
    limits=[e['value'] for e in bound if e['key'].lower() in SIZE_KEYS and e.get('type') in ('int','decimal_string')]
    more=[e['value'] for e in bound if e['key'].lower() in MORE_KEYS and e.get('type')=='bool']
    cursors=[e for e in bound if e['key'].lower() in CURSOR_KEYS and e.get('present') is True]
    continuations=[e for e in bound if e['key'].lower() in CONTINUATION_KEYS and e.get('present') is True]
    hdr=struct.get('headers') or {}
    for k in ('x_total_count','x_result_count'):
        if isinstance(hdr.get(k),int):totals.append(hdr[k])
    if hdr.get('link_rel_next_observed'):more.append(True)
    total=max(totals) if totals else None
    larger=bool(total is not None and isinstance(count,int) and total>count)
    signal=bool(larger or True in more or continuations)
    return {'status':'EXPLICIT_RESPONSE_WINDOW_SIGNAL' if signal else
            'PAGINATION_METADATA_OBSERVED' if bound or total is not None else
            'WRAPPER_ONLY_AMBIGUOUS_METADATA' if fields else
            'NO_PAGINATION_METADATA_IN_EXAMINED_LOADER',
            'explicit_window_signal':signal,'possible_more_results':signal,
            'reported_total':total,'reported_page_size':min(limits) if limits else None,
            'has_more_true_observed':True in more,
            'cursor_present_observed':bool(cursors),
            'continuation_cursor_observed':bool(continuations),
            'observed_count':count,
            'backend_fixed_limit_proven':False}


class RouteStructureRecorder:
    """Passive first-party response listener: no new HTTP requests or pagination hops."""
    def __init__(self):
        self.events=[];self.tasks=set();self.blocked=False;self.errors=0

    def hook(self,response):
        try:
            url=response.url
            p=urlsplit(url)
            if p.scheme!='https' or p.hostname!='www.daangn.com' or p.path!=core.SEARCH_PATH:return
            if response.status in core.BLOCK_STATUS:self.blocked=True
            if not core._is_search_route_response(url) or response.request.resource_type not in ('fetch','xhr'):return
            async def collect():
                try:
                    ct=str(response.headers.get('content-length',''))
                    if ct.isdigit() and int(ct)>core.MAX_BODY:return
                    raw=await asyncio.wait_for(response.body(),timeout=12)
                    if response.status!=200 or len(raw)>core.MAX_BODY:return
                    shape=inspect_payload(raw)
                    shape['headers']=header_observation(response.headers)
                    self.events.append({'digest':hashlib.sha256(raw).hexdigest(),
                                        'request':ev.public_url(url),
                                        'status':response.status,'structure':shape})
                except Exception:self.errors+=1
            task=asyncio.create_task(collect())
            self.tasks.add(task);task.add_done_callback(self.tasks.discard)
        except Exception:self.errors+=1

    async def drain(self):
        if self.tasks:
            try:await asyncio.wait_for(asyncio.gather(*list(self.tasks),return_exceptions=True),timeout=14)
            except asyncio.TimeoutError:self.errors+=1


def select_correlated_structure(stage,recorder,profile_key,region):
    """No route-count or metadata conclusion unless response digest and query agree."""
    import daangn_price_bands_v4_8 as v48
    digests=set(stage.get('matched_route_digest') or [])
    events=[e for e in recorder.events if e['digest'] in digests and
            v48.matched_route({'public_request':e['request']},profile_key,region)]
    if not events:
        return {'status':'NO_CORRELATED_SEARCH_ROUTE_STRUCTURE','recorded_route_events':len(recorder.events),
                'collector_errors':recorder.errors,'access_blocked':recorder.blocked}
    obj=events[-1]['structure']
    return {'status':'CORRELATED_ROUTE_STRUCTURE' if obj['status']=='SEARCH_LOADER_STRUCT_CAPTURED' else
            'CORRELATED_ROUTE_BUT_LOADER_NOT_FOUND',
            'request_price':events[-1]['request'].get('public_params',{}).get('price'),
            'structure':obj,'pagination':summary_flags(obj),
            'recorded_route_events':len(recorder.events),
            'collector_errors':recorder.errors,'access_blocked':recorder.blocked}


async def inspect_remix_loader(page):
    """Introspect in-page loader via page.evaluate; return only filtered shape.

    Python receives a public in-memory object but never serializes raw articles.
    2MB Remix models were already read in the existing v4.8 pipeline.
    """
    model=await page.evaluate('''() => {
       const l=window.__remixContext?.state?.loaderData || {};
       return l['routes/kr.search.buy-sell._index'] ||
         l[Object.keys(l).find(k => /search.*buy-sell/.test(k))] || null;
    }''')
    return inspect_payload(model)
