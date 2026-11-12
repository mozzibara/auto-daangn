# -*- coding: utf-8 -*-
"""v4.32 per-listing sale x Route price x public detail category candidate join.

A recommendation *candidate* is not final recommendation approval.
Search price behavior and listing price are separate statements. Persist only
bounded numeric price, category provenance, context and rank, not seller info,
listing URL or article ID. Asan controls are never recommendations.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from daangn_listing_state_v4_24 import clean_record
from daangn_state_consumers_v4_25 import consume

VERSION='4.32'
PRICE_LIMIT_KRW=50000
TARGET_CONTEXTS=frozenset({'cheonan_a','cheonan_b'})
CONTEXT_ORDER=('cheonan_a','asan_control','cheonan_b')
READY='RECOMMENDATION_CANDIDATE_READY_FOR_REVIEW'
HOLD_PRICE='HOLD_ITEM_PRICE_EVIDENCE'
HOLD_CATEGORY='HOLD_DETAIL_CATEGORY_EVIDENCE'
HOLD_SALE='HOLD_SALE_AVAILABILITY'
HOLD_IDENTITY='HOLD_IDENTITY_OR_ROUTE_EVIDENCE'
BLOCK_PRICE='BLOCK_PRICE_OVER_LIMIT'
INCONCLUSIVE='INCONCLUSIVE_JOIN_EVIDENCE'
ALLOWED_CATEGORY_SOURCES=frozenset({
    'MATCHED_PRODUCT_JSONLD','PRIMARY_SEMANTIC_CATEGORY',
    'PAGE_META_CATEGORY'
})
ALLOWED_SALE_STATUSES=frozenset({
    'SALE_FILTER_PASS_IN_STOCK_NO_NEGATIVE_UI',
    'SALE_FILTER_PASS_EXPLICIT_FOR_SALE_UI'
})


def empty(status):
    return {'status':status,'join_complete':False,
        'target_source_observations':0,'sale_filter_passed':0,
        'category_matched':0,'item_price_known':0,
        'candidate_rows_ready':0,'distinct_listings_proven':False,
        'link_exported_to_public_artifact':False,
        'full_recommendations_approved':0,
        'price_filter_backend_enforcement_claimed':False,
        'prior_strict_gate_overridden':False,
        'records':[],'issues':['JOIN_INPUT_UNAVAILABLE']}


def _rank(row):
    v=row.get('source_rank') if isinstance(row,dict) else None
    return v if type(v) is int and 0<=v<=650 else None


def candidate(record,stage,availability,*,context,route_correlated):
    """Three predicates plus same-item witness; no reliance on UI FOR_SALE badge."""
    item={'context':context,'source_rank':_rank(record),
          'candidate_status':INCONCLUSIVE,
          'sale_filter_passed':False,'category_verified':False,
          'price_verified':False,'price_krw':None,
          'price_evidence':'NONE','category_evidence':'NONE',
          'display_sale_status':'상태 미확인',
          'full_recommendation_approved':False,
          'requires_external_link_review':True,
          # v4.33: run-scoped keyed HMAC, never a raw article identifier.
          'listing_run_hmac':None,
          'item_area_token':None}
    model=(record or {}).get('model') if isinstance(record,dict) else None
    clean=clean_record(model)
    canonical=consume(clean,'SOURCE')
    if clean is None or not canonical['schema_valid'] or (
        canonical['primary_transaction_status'] not in (
            'NOT_OBSERVABLE','FOR_SALE','SOLD','RESERVED')):
        item['candidate_status']=HOLD_IDENTITY
        return item
    if not isinstance(stage,dict) or not isinstance(availability,dict):
        item['candidate_status']=HOLD_IDENTITY
        return item
    if (stage.get('source_rank')!=item['source_rank'] or
        availability.get('source_rank')!=item['source_rank'] or
        availability.get('context')!=context or
        not route_correlated or
        stage.get('page_identity_confirmed') is not True or
        stage.get('detail_http_200_identity') is not True or
        stage.get('primary_heading_visible') is not True or
        stage.get('v421_probe_status')!='OBSERVED' or
        stage.get('v421_primary_valid') is not True or
        stage.get('v421_product_match_count')!=1 or
        clean['identity_confirmed'] is not True or
        clean['render_complete'] is not True):
        item['candidate_status']=HOLD_IDENTITY
        return item

    # This token comes only from the exact-identity public Route item.
    # The independent source projection must carry the same token in v4.33.
    item['listing_run_hmac']=stage.get('listing_run_hmac')
    import re
    area_token=availability.get('item_area_token')
    if type(area_token) is str and re.fullmatch(r'[a-f0-9]{20}',area_token):
        item['item_area_token']=area_token
    item['sale_filter_passed']=(availability.get('sale_filter_eligible') is True
        and availability.get('sale_filter_status') in ALLOWED_SALE_STATUSES
        and canonical['sale_filter_eligible'] is True
        and canonical['sale_filter_status']==availability['sale_filter_status']
        and item['item_area_token'] is not None
        and availability.get('canonical_transaction_status')==
            clean['primary_transaction_status'])
    item['display_sale_status']=(
        '판매 가능 추정' if item['sale_filter_passed'] and
        availability['sale_filter_status']=='SALE_FILTER_PASS_IN_STOCK_NO_NEGATIVE_UI'
        else '판매중 직접 확인' if item['sale_filter_passed']
        else '상태 미확인')

    item['category_verified']=(stage.get('category_verdict')=='MATCH' and
        stage.get('category_evidence_source') in ALLOWED_CATEGORY_SOURCES)
    if item['category_verified']:
        item['category_evidence']=stage['category_evidence_source']

    price=stage.get('route_item_price_krw')
    price_witness=(stage.get('route_item_price_identity_matched') is True and
        type(price) is int and 0<=price<=1000000000)
    if price_witness:
        item['price_krw']=price
        item['price_verified']=True
        item['price_evidence']='MATCHED_PUBLIC_ROUTE_SAME_LISTING'

    if not item['sale_filter_passed']:
        item['candidate_status']=HOLD_SALE
    elif not item['category_verified']:
        item['candidate_status']=HOLD_CATEGORY
    elif not price_witness:
        item['candidate_status']=HOLD_PRICE
    elif price>PRICE_LIMIT_KRW:
        item['candidate_status']=BLOCK_PRICE
    else:
        item['candidate_status']=READY
    return item


def evaluate(v423,v427,v429,v431):
    if not all(isinstance(x,dict) for x in (v423,v427,v429,v431)):
        return empty('INCONCLUSIVE_INVALID_DOCUMENT')
    if any(x.get('consumer_schema_version')!='4.26' for x in (
        v423,v427,v429)):
        return empty('INCONCLUSIVE_CANONICAL_SCHEMA_MISMATCH')
    a,b,c,d=(v423.get('evaluation'),v427.get('evaluation'),
             v429.get('evaluation'),v431.get('evaluation'))
    if not all(isinstance(x,dict) for x in (a,b,c,d)):
        return empty('INCONCLUSIVE_MISSING_EVALUATION')
    if (a.get('bounded_capture_complete') is not True or
        b.get('status')!='CANONICAL_PIPELINE_LIVE_CROSSCHECK_OBSERVED' or
        b.get('pipeline_discrepancy_count')!=0 or
        c.get('survey_complete') is not True or
        d.get('evaluation_complete') is not True or
        d.get('source_visits_checked')!=9):
        return empty('INCONCLUSIVE_UPSTREAM_EVIDENCE_NOT_COMPLETE')
    contexts=a.get('contexts')
    if not isinstance(contexts,list) or len(contexts)!=3 or (
        [x.get('context') for x in contexts if isinstance(x,dict)]
        !=list(CONTEXT_ORDER)):
        return empty('INCONCLUSIVE_CONTEXT_ALIGNMENT')
    expected=d.get('source_items')
    if not isinstance(expected,list) or len(expected)!=9:
        return empty('INCONCLUSIVE_SALE_FILTER_ITEMS_MISSING')
    by_key={}
    for record in expected:
        if not isinstance(record,dict):
            return empty('INCONCLUSIVE_SALE_FILTER_ITEMS_INVALID')
        key=(record.get('context'),_rank(record))
        if (key[0] not in CONTEXT_ORDER or key[1] is None
            or key in by_key):
            return empty('INCONCLUSIVE_DUPLICATE_OR_UNKNOWN_RANK')
        by_key[key]=record
    result=[]
    issues=[]
    for row in contexts:
        context=row['context']
        records=row.get('source_state_models')
        pipeline=row.get('v427_source_pipeline')
        if not all(isinstance(x,list) and len(x)==3 for x in (
            records,pipeline)):
            issues.append('SOURCE_DATASET_CARDINALITY')
            continue
        if row.get('route_correlated') is not True:
            issues.append('ROUTE_CORRELATION_MISSING')
        seen=set()
        for rec,stage in zip(records,pipeline):
            key=(context,_rank(rec))
            if (key[1] is None or key in seen or
                not isinstance(stage,dict) or
                stage.get('source_rank')!=key[1] or
                key not in by_key):
                issues.append('SOURCE_RANK_OR_FILTER_JOIN_MISMATCH')
                continue
            seen.add(key)
            if context not in TARGET_CONTEXTS:
                continue  # ASAN IS RESEARCH CONTROL, NEVER A RECOMMENDATION.
            result.append(candidate(rec,stage,by_key[key],context=context,
                route_correlated=row.get('route_correlated') is True))
    if len(result)!=6:issues.append('TARGET_SAMPLE_COUNT_NOT_SIX')
    if len(by_key)!=9:issues.append('UNCONSUMED_SALE_FILTER_ROWS')
    if issues:
        result=[{**item,'candidate_status':INCONCLUSIVE,
                 'sale_filter_passed':False,'category_verified':False,
                 'price_verified':False,'full_recommendation_approved':False}
                for item in result]
    counts=Counter(x['candidate_status'] for x in result)
    return {
        'status':('RECOMMENDATION_CANDIDATE_JOIN_COMPLETE'
                  if not issues else 'INCONCLUSIVE_RECOMMENDATION_CANDIDATE_JOIN'),
        'join_complete':not issues,
        'target_source_observations':len(result),
        'sale_filter_passed':sum(x['sale_filter_passed'] for x in result),
        'category_matched':sum(x['category_verified'] for x in result),
        'item_price_known':sum(x['price_verified'] for x in result),
        'candidate_rows_ready':counts[READY],
        'distinct_listings_proven':False,
        'link_exported_to_public_artifact':False,
        'full_recommendations_approved':0,
        'price_filter_backend_enforcement_claimed':False,
        'prior_strict_gate_overridden':False,
        'status_counts':dict(sorted(counts.items())),
        'records':result,'issues':sorted(set(issues))}


def report(e):
    return '\n'.join([
        '# v4.32 — sale, exact Route price and public category candidate join','',
        f"- Status: **{e['status']}**",
        f"- Target source observations: {e['target_source_observations']}",
        f"- Sale filter passed: {e['sale_filter_passed']}",
        f"- Detail category matched: {e['category_matched']}",
        f"- Same-item Route numeric price retained: {e['item_price_known']}",
        f"- **Recommendation candidate rows ready for review: {e['candidate_rows_ready']}**",
        f"- Counts: {e.get('status_counts',{})}",
        '- Raw listing URLs/titles/sellers are never stored in published artifacts.',
        '- Cheonan source rows only; Asan comparison is not recommended.',
        '- Observations may refer to repeated listings across contexts.',
        '- Route item price within 50,000 KRW is not proof that server search price filtering is implemented.',
        '- Manual current-link recheck is required for an actionable buyer recommendation.',
        '- Price, category and sale availability pass does not waive other independent admission checks.',
        '- Full recommendations approved: 0 until remaining checks pass.',
        f"- Diagnostics: {e['issues']}",''])


def generate(directory, outdir):
    try:
        required=('v423_public_controls_results.json',
                  'v427_crosscheck_results.json',
                  'v429_public_status_results.json')
        docs=[json.loads((directory/name).read_text(encoding='utf-8'))
              for name in required]
        policy_file=directory/'v431_sale_filter_results.json'
        if policy_file.is_file():
            verified_policy=json.loads(policy_file.read_text(encoding='utf-8'))
        else:
            # Older v4.29 archives predate v4.31; recompute solely from
            # their verified redacted public records, without site requests.
            from daangn_sale_filter_v4_31 import evaluate_capture
            verified_policy={'version':'4.31',
                'evaluation':evaluate_capture(docs[0],docs[2])}
        result=evaluate(*docs,verified_policy)
    except (OSError,ValueError,TypeError):
        result=empty('INCONCLUSIVE_REDACTED_EVIDENCE_MISSING')
    outdir.mkdir(parents=True,exist_ok=True)
    obj={'version':VERSION,
         'utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
         'evaluation':result,
         'recommendation_candidates':{'ready_for_review':result['candidate_rows_ready'],
             'full_recommendations_approved':0,'items':[
                 x for x in result['records'] if x['candidate_status']==READY]},
         'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    (outdir/'v432_recommendation_candidates.json').write_text(
        json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (outdir/'v432_recommendation_report.md').write_text(
        report(result),encoding='utf-8')
    (outdir/'v432_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if result['join_complete'] else 2


def export_local_links(result,sink,target,public_dir):
    """Explicit local opt-in; NEVER called in GitHub Actions public workflow.

    Join actual current-page URL only to exact same context/rank/price
    approved as a candidate. Never persist in any GitHub Actions archive.
    """
    if os.environ.get('GITHUB_ACTIONS') or os.environ.get('CI'):
        raise ValueError('PRIVATE_URL_EXPORT_NOT_AVAILABLE_ON_CI')
    target=Path(target).resolve()
    public_dir=Path(public_dir).resolve()
    if target==public_dir or public_dir in target.parents:
        raise ValueError('PRIVATE_URL_EXPORT_MUST_BE_OUTSIDE_PUBLIC_ARTIFACTS')
    if target.exists():
        raise FileExistsError('PRIVATE_URL_EXPORT_ALREADY_EXISTS')
    if not result.get('join_complete') or not isinstance(sink,list):
        raise ValueError('INCOMPLETE_PUBLIC_CANDIDATE_GATE')
    from daangn_v4_1_core import normalized_listing
    from daangn_v4_4_gate import stable_article_id
    lookup={}
    for x in sink:
        if not isinstance(x,dict):raise ValueError('INVALID_PRIVATE_INPUT')
        key=(x.get('context'),x.get('source_rank'))
        url=x.get('url')
        if (key in lookup or key[0] not in TARGET_CONTEXTS or
            type(key[1]) is not int or not isinstance(url,str)
            or normalized_listing(url)!=url or not stable_article_id(url)
            or type(x.get('price_krw')) is not int):
            raise ValueError('PRIVATE_INPUT_IDENTITY_MISMATCH')
        lookup[key]=x
    selected=[]
    for record in result['records']:
        if record['candidate_status']!=READY:continue
        key=(record['context'],record['source_rank'])
        source=lookup.get(key)
        if source is None or source['price_krw']!=record['price_krw']:
            raise ValueError('PRIVATE_CANDIDATE_PRICE_OR_IDENTITY_MISMATCH')
        selected.append({
            'context':key[0],'source_rank':key[1],
            'price_krw':record['price_krw'],
            'public_listing_url':source['url'],
            'availability':'판매 가능 추정',
            'category':'디지털기기',
            'full_recommendation_approved':False})
    # Never create a misleading actionable export with missing price/links.
    if len(selected)!=result['candidate_rows_ready']:
        raise ValueError('PRIVATE_LINK_COUNT_MISMATCH')
    target.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:
        json.dump({'version':VERSION,'private_local_only':True,
                   'links_current_at_observation_only':True,
                   'recommendations_need_manual_confirmation':True,
                   'items':selected},stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    return len(selected)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--evidence-dir',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    opts=p.parse_args()
    return generate(opts.evidence_dir.resolve(),opts.output_dir.resolve())


if __name__=='__main__':
    raise SystemExit(main())
