# -*- coding: utf-8 -*-
"""v4.14: observe EVERY item in the real UI-correlated Route response, not DOM 32.

Never fabricate pagination or export unredacted product URLs, IDs, response JSON,
cookies, HTML, or user content. Research observation != verified candidate !=
approved listing. A separate strict sample gate controls any promotion.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from types import SimpleNamespace

import daangn_v4_1_core as core
import daangn_v4_4_gate as old_gate
import daangn_v4_5_evidence as evidence
import daangn_browser_v4_6 as v46
import daangn_price_bands_v4_8 as bands
import daangn_network_flow_v4_11 as network
import daangn_render_gap_v4_12 as render
import daangn_route_structure_v4_10 as shape


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class RouteBodies:
    """Bounded, passive in-memory collector; models must match known UI responses."""
    def __init__(self,field_probe=None):
        self.field_probe=field_probe
        self.events=[]
        self.tasks=set()
        self.errors=0
        self.blocked=False

    def on_response(self, response):
        try:
            if not core._is_search_route_response(response.url):
                return
            if response.status in core.BLOCK_STATUS:
                self.blocked=True
                return
            if response.status!=200 or response.request.resource_type not in ('xhr','fetch'):
                return
            content_type=str(response.headers.get('content-type','')).lower()
            if 'json' not in content_type and 'remix' not in content_type:
                return
            length=response.headers.get('content-length','')
            if length.isdigit() and int(length)>core.MAX_BODY:
                self.errors+=1
                return
            if len(self.events)+len(self.tasks)>8:
                self.errors+=1
                return

            async def receive():
                try:
                    raw=await asyncio.wait_for(response.body(),timeout=12)
                    if len(raw)>core.MAX_BODY:
                        self.errors+=1
                        return
                    structure=shape.inspect_payload(raw)
                    model=evidence.extract_model(raw)
                    count=structure.get('raw_articles_count')
                    if not isinstance(count,int) or count<1 or count>core.MAX_ARTICLES or model is None:
                        self.errors+=1
                        return
                    if len(model.get('articles',[]))!=count:
                        self.errors+=1
                        return
                    model,field_shape=enhance_observed_fields(raw,model)
                    if model is None:
                        self.errors+=1
                        return
                    # Optional bounded structural probe sees raw only in RAM.
                    # Never emit the response body or user-derived raw values.
                    probe=None
                    if self.field_probe is not None:
                        probe=self.field_probe(raw,model)
                    self.events.append({'digest':hashlib.sha256(raw).hexdigest(),
                        'public_request':evidence.public_url(response.url),
                        'model':model,'raw_count':count,
                        'item_field_shape':field_shape,
                        'v419_filter_structure':probe})
                except Exception:
                    self.errors+=1
            task=asyncio.create_task(receive())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except Exception:
            self.errors+=1

    async def drain(self):
        if self.tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*list(self.tasks),
                                       return_exceptions=True),timeout=15)
            except asyncio.TimeoutError:
                self.errors+=1

    def matched(self,stage,region):
        expected=stage.get('matched_route_digest') or []
        if len(expected)!=1:
            return None
        candidates=[row for row in self.events
            if row['digest']==expected[0] and
            bands.matched_route(row,'cap_50000',core.BY_KEY[region])]
        return candidates[0] if len(candidates)==1 else None



def enhance_observed_fields(raw, model):
    """Fill nested category.id only when explicitly present in matched response."""
    try:
        value=json.loads(raw)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None,{'status':'BAD_JSON'}
    candidates=[]
    stack=[(value,0)]
    while stack:
        obj,depth=stack.pop()
        if depth>7:
            continue
        if isinstance(obj,dict):
            if isinstance(obj.get('buySellArticles'),list):
                candidates.append(obj)
            for child in obj.values():
                if isinstance(child,(dict,list)):
                    stack.append((child,depth+1))
        elif isinstance(obj,list):
            for child in obj[:30]:
                if isinstance(child,(dict,list)):
                    stack.append((child,depth+1))
    if not candidates:
        return None,{'status':'NO_ARTICLES'}
    candidates.sort(key=lambda x:(isinstance(x.get('searchRegion'),dict),
                                  isinstance(x.get('currentFilters'),dict)),reverse=True)
    original=candidates[0]['buySellArticles']
    if len(original)!=len(model.get('articles',[])):
        return None,{'status':'MODEL_RAW_ARRAY_MISMATCH'}
    cats=Counter()
    sales=Counter()
    for observed,row in zip(original,model['articles']):
        if not isinstance(observed,dict):
            return None,{'status':'NON_OBJECT_ARTICLE'}
        if (observed.get('href') or observed.get('url') or '') != row.get('href'):
            return None,{'status':'MODEL_RAW_ROW_ORDER_MISMATCH'}
        if row.get('categoryId') is not None:
            cats['flat']+=1
        else:
            nested=observed.get('category')
            found=nested.get('id') if isinstance(nested,dict) else None
            if found is not None and not isinstance(found,(dict,list)):
                row['categoryId']=found
                cats['category.id']+=1
            else:
                cats['missing']+=1
        sales['flat' if row.get('isSoldOut') is not None else 'missing']+=1
    return model,{'status':'OBSERVED_ITEM_FIELD_SHAPE',
                  'category_sources':dict(cats),'availability_sources':dict(sales)}


def classify_article(article):
    """Require explicit per-item attributes; missing is not an implicit pass."""
    if not isinstance(article,dict):
        return 'INVALID_ITEM',None
    link=core.normalized_listing(article.get('href'))
    if not link or not old_gate.stable_article_id(link):
        return 'INVALID_LISTING_ID',None
    price=evidence.int_price(article.get('price'))
    if price is None:
        return 'UNKNOWN_PRICE',link
    if price>50000:
        return 'PRICE_OUT_OF_RANGE',link
    cat=article.get('categoryId')
    if cat is None:
        return 'UNKNOWN_CATEGORY',link
    if str(cat)!='1' or isinstance(cat,bool):
        return 'WRONG_CATEGORY',link
    sold=article.get('isSoldOut')
    if sold is None:
        return 'UNKNOWN_SALE_STATUS',link
    if sold is not False and sold!=0:
        return 'UNAVAILABLE_OR_UNRECOGNIZED_STATUS',link
    return 'ITEM_CRITERIA_MATCH',link


def inventory(model, salt):
    """Capture every array position in order, including invalid/quarantined rows."""
    articles=(model or {}).get('articles')
    if not isinstance(articles,list):
        return {'status':'INVALID_ARRAY','rows':[],'raw_count':0}
    if len(articles)>core.MAX_ARTICLES:
        return {'status':'LOCAL_EXTRACTION_CAP_EXCEEDED','rows':[],'raw_count':len(articles)}
    rows=[]
    seen=set()
    for i,article in enumerate(articles):
        verdict,link=classify_article(article)
        identity=old_gate.stable_article_id(link) if link else None
        token=hmac.new(salt,identity.encode('ascii'),hashlib.sha256).hexdigest()[:24] if identity else None
        if token is not None and token in seen:
            verdict='DUPLICATE_LISTING_ID'
        elif token is not None:
            seen.add(token)
        price=evidence.int_price(article.get('price')) if isinstance(article,dict) else None
        rows.append({'source_rank':i,'token':token,'price_krw':price,
                     'item_verdict':verdict})
    stats=dict(sorted(Counter(x['item_verdict'] for x in rows).items()))
    return {'status':'ALL_ROUTE_ARRAY_POSITIONS_CAPTURED',
            'raw_count':len(articles),'unique_valid_identifiers':len(seen),
            'item_criteria_match_count':stats.get('ITEM_CRITERIA_MATCH',0),
            'exception_counts':{k:v for k,v in stats.items() if k!='ITEM_CRITERIA_MATCH'},
            'rows':rows}


def publishable_evidence(filter_evidence,inv,region_ok,matched_digest,dom_relation):
    """Candidate admission, not the historical independent-listing approval."""
    proof=filter_evidence or {}
    return bool(proof.get('status')=='FILTER_APPLIED_VERIFIED' and
                proof.get('approved') is True and
                proof.get('evidence_tier')=='VERIFIED_SERVER_AND_UI' and
                region_ok and matched_digest and
                inv.get('status')=='ALL_ROUTE_ARRAY_POSITIONS_CAPTURED' and
                inv.get('raw_count',0)>32 and
                (dom_relation or {}).get('dom_unique_count',0)>=1 and
                (dom_relation or {}).get('dom_only_unique_count',1)==0 and
                (dom_relation or {}).get('matched_unique_count',0)>=1)


async def capture(browser,name,region,options,salt):
    context=await browser.new_context(locale='ko-KR',viewport={'width':1280,'height':850})
    page=await context.new_page()
    page.set_default_timeout(options.timeout*1000)
    passive=network.NetworkRecorder()
    context.on('request',passive.on_request)
    context.on('response',passive.on_response)
    result={'context':name,'region':region,'status':'INCOMPLETE',
            'filter_proof_status':'NOT_OBSERVED','route_correlated':False,
            'route_count':None,'inventory':{'rows':[]},'candidate_gate':False,
            'error_type':None}
    try:
        baseline=await page.goto(core.search_url('HDD',core.BY_KEY[region]),
            wait_until='domcontentloaded',timeout=options.timeout*1000)
        if not baseline or baseline.status!=200:
            raise RuntimeError('BASELINE_HTTP_INVALID')
        await page.wait_for_timeout(options.settle_ms)
        await passive.drain()
        if core.region_id_in_url(page.url)!=core.BY_KEY[region]['id']:
            raise RuntimeError('REGION_MISMATCH')
        if (await render.snapshot(page))['restricted'] or passive.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
        if getattr(options,'filter_recheck_v15',False):
            from daangn_filter_recheck_v4_15 import surface
            result['baseline_surface']=await surface(page)
        if getattr(options,'filter_dom_v16',False):
            from daangn_filter_dom_v4_16 import inspect
            result['baseline_dom_v16']=await inspect(page)
        args=SimpleNamespace(keyword='HDD',regions={'target':dict(core.BY_KEY[region])},
            category_id=1,category_name=v46.CATALOG[1],available_only=True,
            min_price=0,max_price=50000,settle_ms=options.settle_ms,timeout=options.timeout)
        bodies=RouteBodies()
        passive.phase='FILTER_APPLY'
        page.on('response',bodies.on_response)
        try:
            stage,blocked,_=await bands.capture_apply(page,args,name,'target','cap_50000',salt)
        finally:
            page.remove_listener('response',bodies.on_response)
            await bodies.drain()
        await passive.drain()
        if blocked or bodies.blocked or passive.blocked:
            raise RuntimeError('ACCESS_RESTRICTION')
        filter_evidence=stage.get('filter_evidence') or {}
        result['filter_proof_status']=filter_evidence.get('status','UNVERIFIED')
        ui_correlated=bool(stage.get('matched_route_count')==1 and
            stage.get('price_url_shape_observed') and stage.get('ui_selected') and
            stage.get('region_ok') and core.region_id_in_url(page.url)==core.BY_KEY[region]['id'])
        matched=bodies.matched(stage,region)
        if not matched or not ui_correlated or bodies.errors:
            raise RuntimeError('CORRELATED_ROUTE_MISSING')
        structure=[e for e in passive.events if e['kind']=='SEARCH_ROUTE' and
              e['phase']=='FILTER_APPLY' and e.get('status')==200]
        if len(structure)<1 or structure[-1].get('response_shape',{}).get('search_route_count')!=matched['raw_count']:
            raise RuntimeError('ROUTE_LENGTH_MISMATCH')
        result['route_correlated']=True
        result['route_count']=matched['raw_count']
        result['item_field_shape']=matched.get('item_field_shape')
        dom,_=await v46.snap(page)
        if dom.get('challenge') or dom.get('login_wall'):
            raise RuntimeError('ACCESS_RESTRICTION')
        relation=render.route_relation(
            [row.get('href') for row in matched['model']['articles']],dom.get('dom_visible',[]))
        result['dom_evidence']={
            'dom_unique_count':relation['dom_unique_count'],
            'matched_route_count':relation['matched_unique_count'],
            'dom_only_unique_count':relation['dom_only_unique_count'],
            'first_32_match':relation['exactly_first_32_set']}
        inv=inventory(matched['model'],salt)
        if inv['raw_count']!=matched['raw_count'] or inv['status']!='ALL_ROUTE_ARRAY_POSITIONS_CAPTURED':
            raise RuntimeError('LOCAL_EXTRACTION_TRUNCATED')
        result['inventory']=inv
        if getattr(options,'filter_recheck_v15',False):
            from daangn_filter_recheck_v4_15 import durable_recheck
            # The first-party Route body is already frozen in RAM and correlated
            # to UI-filter actions. Only reload the actual UI-produced search URL.
            observed_filter_url=page.url
            probe=None
            if getattr(options,'filter_dom_v16',False):
                from daangn_filter_dom_v4_16 import inspect
                probe=inspect
            diag=await durable_recheck(page,args,observed_filter_url,
                options.settle_ms,stage.get('ui_recheck'),dom_probe=probe)
            result['ui_persistence']=diag
            if diag.get('access_restricted'):
                raise RuntimeError('ACCESS_RESTRICTION')
            # Re-run the ORIGINAL strict server+UI validation against the actual
            # response model, never stale window.__remixContext loaderData.
            persistent=diag['stable_selection_verified']
            if diag.get('cause_classification')=='ACTUAL_FILTER_SELECTION_MISMATCH':
                observed_status='OBSERVED_MISMATCH'
            else:
                observed_status='OBSERVED_MATCH' if persistent else 'NOT_OBSERVABLE'
            proof=evidence.validated_predicates(matched['model'],observed_filter_url,
                core.BY_KEY[region]['id'],bool(stage.get('ui_selected') and persistent),
                True,ui_observation_status=observed_status,
                expected=v46.expected_for(args),require_response_filters=True)
            result['v415_rechecked_filter_proof_status']=proof['status']
            result['v415_rechecked_filter_proof_tier']=proof['evidence_tier']
            # Separate actual response metadata from absent/hidden UI controls.
            # These booleans cannot themselves prove the user's selected state.
            criteria=proof.get('criteria') or {}
            category=criteria.get('category') or {}
            maximum=criteria.get('max_price') or {}
            availability=criteria.get('available_only') or {}
            result['v415_response_filter_field_status']={
                'category_ok':bool(category.get('ok')),
                'category_from_response':category.get('source')=='response',
                'maximum_ok':bool(maximum.get('ok')),
                'maximum_from_response':maximum.get('source')=='response',
                'availability_ok':bool(availability.get('ok')),
                'availability_from_response':availability.get('source')=='response',
                'region_ok':bool(proof.get('region_ok')),
                'ui_verified':bool(proof.get('ui_verified'))}
            filter_evidence=proof
            result['filter_proof_status']=proof['status']
        result['candidate_gate']=publishable_evidence(filter_evidence,inv,
            stage.get('region_ok'),True,relation)
        if getattr(options,'detail_probe_v420',False):
            from daangn_detail_crosscheck_v4_20 import audit_sample
            # Detail verification is independent, *never* an alternative
            # route to historical candidate_gate or strict listing admission.
            result['v420_detail_audit']=await audit_sample(
                page,matched['model'],name,region,options,salt,
                result.get('ui_persistence') or {})
            if result['v420_detail_audit'].get('stop_access'):
                raise RuntimeError('ACCESS_RESTRICTION')
        if getattr(options,'filter_activation_v161',False):
            from daangn_filter_action_v4_16_1 import exercise
            persistence=result.get('ui_persistence') or {}
            result['v416_activation']=await exercise(page,args,
                result.get('baseline_dom_v16') or {},
                persistence.get('reload_dom_v16') or {},options.settle_ms)
            if result['v416_activation'].get('access_restricted'):
                raise RuntimeError('ACCESS_RESTRICTION')
        result['status']='CAPTURED_CANDIDATES_VERIFIED' if result['candidate_gate'] else 'CAPTURED_ROUTE_UNVERIFIED'
    except Exception as exc:
        reason=str(exc)
        known={'BASELINE_HTTP_INVALID','REGION_MISMATCH','ACCESS_RESTRICTION',
               'CORRELATED_ROUTE_MISSING','ROUTE_LENGTH_MISMATCH','LOCAL_EXTRACTION_TRUNCATED'}
        result['status']='STOP_'+type(exc).__name__
        result['error_type']=reason if reason in known else type(exc).__name__
    finally:
        await passive.drain()
        result['collector_errors']=passive.errors
        result['collector_overflow']=passive.overflow
        result['access_blocked']=passive.blocked or result.get('error_type')=='ACCESS_RESTRICTION'
        await context.close()
    return result


def evaluate(rows):
    complete=len(rows)==3 and all(row.get('status','').startswith('CAPTURED_') for row in rows)
    healthy=complete and all(row.get('route_correlated') and not row.get('access_blocked')
        and not row.get('collector_overflow') and row.get('collector_errors',0)==0
        and row.get('route_count')==row.get('inventory',{}).get('raw_count')
        and len(row.get('inventory',{}).get('rows',[]))==row.get('route_count') for row in rows)
    target=[r for r in rows if r.get('region')=='cheonan']
    control=[r for r in rows if r.get('region')=='asan']
    a={x['token'] for x in target[0]['inventory']['rows'] if x['token']} if len(target)==2 else set()
    b={x['token'] for x in target[1]['inventory']['rows'] if x['token']} if len(target)==2 else set()
    c={x['token'] for x in control[0]['inventory']['rows'] if x['token']} if len(control)==1 else set()
    jaccard=len(a&b)/len(a|b) if a|b else None
    distinct_control=bool(c and (c!=a and c!=b))
    cross_similarity_a=len(a&c)/len(a|c) if a|c else None
    cross_similarity_b=len(b&c)/len(b|c) if b|c else None
    cross_region_near_identical=any(x is not None and x>=old_gate.HIGH_REPEAT_JACCARD
                                   for x in (cross_similarity_a,cross_similarity_b))
    qualified=bool(healthy and len(target)==2 and len(control)==1 and
         all(row.get('candidate_gate') for row in rows) and
         jaccard is not None and jaccard>=0.80 and distinct_control
         and not cross_region_near_identical)
    if any(row.get('access_blocked') for row in rows):
        status='STOP_ACCESS_RESTRICTION'
    elif not healthy:
        status='INCONCLUSIVE_INCOMPLETE_FULL_ROUTE_CAPTURE'
    elif qualified:
        status='VERIFIED_FULL_ROUTE_CANDIDATES_CAPTURED'
    else:
        status='FULL_ROUTE_OBSERVED_BUT_CANDIDATES_NOT_APPROVED'
    all_target={x['token']:x for row in target for x in row['inventory']['rows'] if
                x['token'] and x['item_verdict']=='ITEM_CRITERIA_MATCH'} if healthy else {}
    certified=[{'token':token,'price_krw':entry['price_krw']}
               for token,entry in sorted(all_target.items())] if qualified else []
    return {'status':status,'capture_complete':healthy,
        'contexts_expected':3,'contexts_captured':sum(r.get('status','').startswith('CAPTURED_') for r in rows),
        'route_article_counts':[r.get('route_count') for r in rows],
        'route_observed_positions_total':sum(r.get('inventory',{}).get('raw_count',0) for r in rows),
        'target_independent_jaccard':round(jaccard,6) if jaccard is not None else None,
        'independent_control_distinct':distinct_control,
        'cross_region_control_jaccard':[round(x,6) if x is not None else None for x in (cross_similarity_a,cross_similarity_b)],
        'cross_region_near_identical':cross_region_near_identical,
        'per_context_candidate_gates':[r.get('candidate_gate',False) for r in rows],
        'certified_candidate_count':len(certified),
        'certified_candidates':certified,
        'strict_listing_export_approved':False,
        'strict_listing_approved_count':0,
        'whole_site_inventory_proven':False,
        'backend_fixed_cap_proven':False}


def sanitized_context(row):
    """Retain complete research rows, but never persist response models or IDs."""
    inv=row.get('inventory',{})
    return {'context':row.get('context'),'region':row.get('region'),
       'status':row.get('status'),'error_type':row.get('error_type'),
       'filter_proof_status':row.get('filter_proof_status'),
       'v415_rechecked_filter_proof_status':row.get('v415_rechecked_filter_proof_status'),
       'v415_rechecked_filter_proof_tier':row.get('v415_rechecked_filter_proof_tier'),
       'v415_response_filter_field_status':row.get('v415_response_filter_field_status'),
       'route_correlated':row.get('route_correlated'),'route_count':row.get('route_count'),
       'dom_evidence':row.get('dom_evidence'),
       'item_field_shape':row.get('item_field_shape'),
       'baseline_surface':row.get('baseline_surface'),
       'baseline_dom_v16':row.get('baseline_dom_v16'),
       'v416_activation':row.get('v416_activation'),
       'candidate_gate':row.get('candidate_gate'),
       'inventory':inv,
       'collector_errors':row.get('collector_errors'),
       'collector_overflow':row.get('collector_overflow'),
       'access_blocked':row.get('access_blocked')}


def report(doc):
    x=doc['evaluation']
    lines=['# v4.14 full Route observation vs strict candidate admission','',
       f"- Verdict: **{x['status']}**; complete: {x['capture_complete']}",
       f"- Route array counts: {x['route_article_counts']}",
       f"- Total observed Route positions (including control/repeats): {x['route_observed_positions_total']}",
       f"- Strictly verified candidate count: {x['certified_candidate_count']}",
       f"- Target repeat Jaccard: {x['target_independent_jaccard']}; distinct control: {x['independent_control_distinct']}",
       f"- Cross-region similarity: {x['cross_region_control_jaccard']}; quarantine: {x['cross_region_near_identical']}",
       '', '| Context | Route items | Valid item criteria | Exception types | Proof tier |',
       '|---|---:|---:|---|---|']
    for row in doc['contexts']:
        inv=row.get('inventory') or {}
        lines.append(f"| {row['context']} | {row.get('route_count')} | "
              f"{inv.get('item_criteria_match_count')} | "
              f"{json.dumps(inv.get('exception_counts') or {},ensure_ascii=False)} | "
              f"{row.get('filter_proof_status')} |")
    lines.extend(['','- Route positions are fully inventoried even if DOM shows only 32 anchors.',
      '- Research pseudonyms are ephemeral and scoped to this run; they are not usable as listing URLs.',
      '- Item-criteria matches are NOT promoted if server/UI proof, repeat, or control gates fail.',
      '- A Route response is not a guarantee of whole-site completeness or listing availability.',
      '- Historical strict listing-approval pipeline is unchanged; approved listing count is zero.',''])
    return '\n'.join(lines)


async def run(args):
    rows=[]
    salt=secrets.token_bytes(32)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=not args.headed)
            try:
                for name,region in (('cheonan_a','cheonan'),
                                    ('asan_control','asan'),('cheonan_b','cheonan')):
                    row=await capture(browser,name,region,args,salt)
                    rows.append(row)
                    print('v4.14',name,row['status'],row.get('route_count'),
                        'eligible',(row.get('inventory') or {}).get('item_criteria_match_count'))
                    if row['status'].startswith('STOP_') or row.get('access_blocked'):
                        break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as exc:
        rows.append({'context':'browser','region':None,'status':'STOP_'+type(exc).__name__})
    decision=evaluate(rows)
    doc={'version':'4.14','utc_time':now(),
         'design':{'keyword':'HDD','target':'cheonan','control':'asan',
                   'profile':'cap_50000','all_route_positions_included':True,
                   'hmac_salt_persisted':False,'raw_listing_urls_exported':False},
         'evaluation':decision,'contexts':[sanitized_context(row) for row in rows],
         'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'v414_full_route_results.json').write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output_dir/'v414_full_route_report.md').write_text(report(doc),encoding='utf-8')
    (args.output_dir/'v414_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    print('v4.14:',decision['status'],'complete:',decision['capture_complete'])
    return 0 if decision['capture_complete'] else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v414_output'))
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
