# -*- coding: utf-8 -*-
"""v4.33: privacy-bounded, exact-listing deduplication of v4.32 candidates.

Only one capture-scoped, keyed HMAC over a canonical listing ID can establish
same-item identity across context replays. Rank, title, price, category and
timestamp are NEVER deduplication keys. A key cannot be reused across runs.

No browsing, raw URL, listing ID, title, seller data or HMAC secret in reports.
One conflicting observation quarantines the entire corresponding item.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

import daangn_recommendation_candidates_v4_32 as prior

VERSION='4.33'
RUN_HMAC=re.compile(r'^[0-9a-f]{20}$')
CONTEXT_ORDER=('cheonan_a','asan_control','cheonan_b')
TARGET=frozenset({'cheonan_a','cheonan_b'})
UNIQUE='UNIQUE_RECOMMENDATION_CANDIDATE_READY_FOR_REVIEW'
QUARANTINE='QUARANTINED_REPEATED_LISTING_CONFLICT'


def _empty(code,*,observed=0,unkeyed=0):
    return {'status':code,'dedup_complete':False,
        'observation_candidate_count':observed,
        'unique_candidate_count':0,'duplicate_observations_removed':0,
        'repeat_verified_unique_count':0,'quarantined_unique_groups':0,
        'quarantined_observation_count':0,
        'missing_run_identity_count':unkeyed,
        'unique_candidates':[],'quarantined_candidates':[],
        'raw_listing_url_exported':False,
        'single_capture_scope_only':True,'across_runs_identity_verified':False,
        'price_conflicts_ignored':False,
        'full_recommendations_approved':0,
        'prior_strict_gate_overridden':False}


def _key(c,r):
    return (c,r) if c in TARGET and type(r) is int and 0<=r<=650 else None


def deduplicate(v423,v432):
    """Join exact v4.32 target observations to HMAC witnesses in v4.23.

    A missing pseudonym anywhere in the target observation set makes the
    entire deduplication inconclusive, not just the missing row: the unknown
    row could refer to an already 'unique' candidate.
    """
    if not isinstance(v423,dict) or not isinstance(v432,dict):
        return _empty('INCONCLUSIVE_MISSING_DOCUMENTS')
    if v423.get('consumer_schema_version')!='4.26' or (
        v432.get('version')!='4.32'):
        return _empty('INCONCLUSIVE_VERSION_MISMATCH')
    root=v423.get('evaluation')
    evaluated=v432.get('evaluation')
    if not isinstance(root,dict) or not isinstance(evaluated,dict):
        return _empty('INCONCLUSIVE_MISSING_EVALUATION')
    if (root.get('bounded_capture_complete') is not True
        or evaluated.get('join_complete') is not True
        or evaluated.get('target_source_observations')!=6
        or evaluated.get('full_recommendations_approved')!=0
        or evaluated.get('prior_strict_gate_overridden') is not False):
        return _empty('INCONCLUSIVE_UPSTREAM_JOIN_NOT_VALIDATED')
    rows=root.get('contexts')
    observations=evaluated.get('records')
    if (not isinstance(rows,list) or len(rows)!=3 or
        not isinstance(observations,list) or len(observations)!=6 or
        [r.get('context') for r in rows if isinstance(r,dict)]
        !=list(CONTEXT_ORDER)):
        return _empty('INCONCLUSIVE_CONTEXT_SET')
    candidates={}
    for record in observations:
        if not isinstance(record,dict):
            return _empty('INCONCLUSIVE_INVALID_CANDIDATE_RECORD')
        key=_key(record.get('context'),record.get('source_rank'))
        if key is None or key in candidates:
            return _empty('INCONCLUSIVE_DUPLICATE_CONTEXT_RANK')
        candidates[key]=record
    if len(candidates)!=6:
        return _empty('INCONCLUSIVE_INCOMPLETE_TARGET_CANDIDATES')

    by_key={}
    for context in rows:
        name=context['context']
        records=context.get('source_state_models')
        projected=context.get('v427_source_pipeline')
        if not (isinstance(records,list) and isinstance(projected,list)
                and len(records)==len(projected)==3):
            return _empty('INCONCLUSIVE_EVIDENCE_CARDINALITY')
        if context.get('route_correlated') is not True:
            return _empty('INCONCLUSIVE_ROUTE_NOT_CORRELATED')
        seen=set()
        for original,stage in zip(records,projected):
            if not isinstance(original,dict) or not isinstance(stage,dict):
                return _empty('INCONCLUSIVE_WRONG_ORIGIN')
            rank=original.get('source_rank')
            if (type(rank) is not int or not 0<=rank<=650
                or rank in seen or stage.get('source_rank')!=rank):
                return _empty('INCONCLUSIVE_RANK_BINDING')
            seen.add(rank)
            if name not in TARGET:
                continue  # Asan is a control; never a recommendation.
            key=(name,rank)
            if key not in candidates or key in by_key:
                return _empty('INCONCLUSIVE_CANDIDATE_MISSING_IN_SOURCE')
            by_key[key]=stage
    if len(by_key)!=6 or set(by_key)!=set(candidates):
        return _empty('INCONCLUSIVE_SOURCE_CANDIDATE_ALIGNMENT')

    groups=defaultdict(list)
    missing=0
    for key in sorted(candidates):
        record=candidates[key]
        stage=by_key[key]
        hmac=stage.get('listing_run_hmac')
        if (not isinstance(hmac,str) or RUN_HMAC.fullmatch(hmac) is None
            or not isinstance(record.get('listing_run_hmac'),str)
            or RUN_HMAC.fullmatch(record['listing_run_hmac']) is None
            or stage.get('page_identity_confirmed') is not True
            or stage.get('detail_http_200_identity') is not True
            or stage.get('route_item_price_identity_matched') is not True):
            missing+=1
            continue
        # Both archived independently derived records must refer to
        # the SAME run-scoped keyed listing ID. Never silently combine
        # different capture runs with unrelated HMAC salts.
        if record['listing_run_hmac']!=hmac:
            return _empty('INCONCLUSIVE_MIXED_RUN_OR_LISTING_IDENTITY',
                          observed=evaluated.get('candidate_rows_ready',0))
        # Strong relation: each retained price is the exact same Route
        # item as the HMAC tag, not an arbitrary rank matched by price.
        if (stage.get('route_item_price_krw')!=record.get('price_krw')
            or (record.get('price_verified') is True and
                type(record.get('price_krw')) is not int)):
            return _empty('INCONCLUSIVE_PRICE_WITNESS_ALIGNMENT',
                          observed=evaluated.get('candidate_rows_ready',0))
        groups[hmac].append(record)
    if missing:
        return _empty('INCONCLUSIVE_MISSING_RUN_SCOPED_LISTING_IDENTITIES',
                      observed=evaluated.get('candidate_rows_ready',0),
                      unkeyed=missing)
    ready=[]
    quarantined=[]
    for token,observed in groups.items():
        grouped=sorted(observed,key=lambda x:(x['context'],x['source_rank']))
        reasons=[]
        if any(x.get('candidate_status')!=prior.READY for x in grouped):
            reasons.append('NONREADY_OR_CONTRADICTORY_OBSERVATION')
        prices={x.get('price_krw') for x in grouped}
        if len(prices)!=1 or any(type(x.get('price_krw')) is not int for x in grouped):
            reasons.append('CONFLICTING_OR_INVALID_PRICE')
        if any(x.get('category_verified') is not True for x in grouped):
            reasons.append('CATEGORY_NOT_VERIFIED_IN_ALL_OBSERVATIONS')
        if any(x.get('sale_filter_passed') is not True for x in grouped):
            reasons.append('SALE_NOT_VERIFIED_IN_ALL_OBSERVATIONS')
        if any(x.get('price_verified') is not True for x in grouped):
            reasons.append('PRICE_NOT_VERIFIED_IN_ALL_OBSERVATIONS')
        if len({x.get('display_sale_status') for x in grouped})!=1:
            reasons.append('CONFLICTING_DISPLAYED_SALE_STATE')
        # No joining an item observed under contradictory subdistricts.
        area_tokens={x.get('item_area_token') for x in grouped}
        if len(area_tokens)!=1:
            reasons.append('CONFLICTING_ITEM_AREA')
        area_token=next(iter(area_tokens)) if len(area_tokens)==1 else None
        if area_token is not None:
            import re
            if type(area_token) is not str or (
                    re.fullmatch(r'[a-f0-9]{20}',area_token) is None):
                reasons.append('INVALID_ITEM_AREA_TOKEN')
        if len(prices)==1 and all(type(p) is int for p in prices):
            price=next(iter(prices))
            if price<0 or price>prior.PRICE_LIMIT_KRW:
                reasons.append('ITEM_PRICE_OUT_OF_RANGE')
        common={'listing_run_hmac':token,'observation_count':len(grouped),
            'observations':[{'context':x['context'],
                             'source_rank':x['source_rank']} for x in grouped],
            'price_krw':next(iter(prices)) if len(prices)==1 and
                       all(type(p) is int for p in prices) else None,
            'category':'디지털기기',
            'display_sale_status':grouped[0].get('display_sale_status'),
            'item_area_token':area_token,
            'full_recommendation_approved':False,
            'requires_current_listing_link_recheck':True}
        if reasons:
            quarantined.append({**common,'status':QUARANTINE,
                                'reason_codes':sorted(set(reasons))})
        else:
            ready.append({**common,'status':UNIQUE,
                          'independently_repeated':len(grouped)>=2,
                          'reason_codes':[]})
    ready.sort(key=lambda x:(x['price_krw'],x['listing_run_hmac']))
    quarantined.sort(key=lambda x:x['listing_run_hmac'])
    count=evaluated.get('candidate_rows_ready',0)
    if type(count) is not int or not 0<=count<=6:
        return _empty('INCONCLUSIVE_UNTRUSTED_READY_COUNT')
    # Every v4.32 ready observation is either in one unique candidate or
    # deliberately quarantined. No duplicate is silently dropped.
    assigned=sum(x['observation_count'] for x in ready)+sum(
        x['observation_count'] for x in quarantined)
    if assigned!=6:
        return _empty('INCONCLUSIVE_LOST_OBSERVATION')
    verified_ready=sum(x['observation_count'] for x in ready)
    if verified_ready>count:
        return _empty('INCONCLUSIVE_READY_COUNT_OVERFLOW')
    return {'status':'UNIQUE_CANDIDATES_DEDUPLICATED',
        'dedup_complete':True,'observation_candidate_count':count,
        'unique_candidate_count':len(ready),
        'duplicate_observations_removed':verified_ready-len(ready),
        'repeat_verified_unique_count':sum(x['independently_repeated'] for x in ready),
        'quarantined_unique_groups':len(quarantined),
        'quarantined_observation_count':sum(x['observation_count'] for x in quarantined),
        'missing_run_identity_count':0,'unique_candidates':ready,
        'quarantined_candidates':quarantined,
        'raw_listing_url_exported':False,'single_capture_scope_only':True,
        'across_runs_identity_verified':False,
        'price_conflicts_ignored':False,
        'full_recommendations_approved':0,
        'prior_strict_gate_overridden':False}


def report(e):
    return '\n'.join([
        '# v4.33 — capture-scoped HMAC unique recommendation candidates','',
        f"- Verdict: **{e['status']}**",
        f"- v4.32 candidate observations: **{e['observation_candidate_count']}**",
        f"- Unique ready candidates: **{e['unique_candidate_count']}**",
        f"- Repeated observations collapsed: {e['duplicate_observations_removed']}",
        f"- Unique candidates with repeated independent observations: {e['repeat_verified_unique_count']}",
        f"- Quarantined unique groups: {e['quarantined_unique_groups']}",
        f"- Quarantined observations: {e['quarantined_observation_count']}",
        f"- Missing capture-scoped identity tags: {e['missing_run_identity_count']}",'',
        '| Rank | Price (KRW) | Observations | Source contexts/ranks |',
        '|---:|---:|---:|---|',
        *['| '+ ' | '.join([str(i),
            str(x['price_krw']),str(x['observation_count']),
            ', '.join(f"{o['context']}:{o['source_rank']}"
                      for o in x['observations'])])+' |'
          for i,x in enumerate(e['unique_candidates'],1)],
        '', '## Interpretation','',
        '- Only the same run-scoped keyed HMAC of an exact listing ID can deduplicate observations.',
        '- Same price or rank without a matching keyed HMAC NEVER establishes identity.',
        '- No HMAC secret, raw listing URL, seller, title, or unkeyed original ID is archived.',
        '- Keys CANNOT be compared between executions because the salt is freshly generated each run.',
        '- Missing keys fail closed: historical v4.32 results cannot be retroactively deduplicated.',
        '- Any discrepancy in observed price, item category, sale status, or readiness quarantines the whole item.',
        '- Candidate rows remain reviewable, not automatically approved marketplace recommendations.',
        '- Current listing link and live price require a separate manual/local confirmation.',
        f"- Full recommendations approved: {e['full_recommendations_approved']}",''])


def generate(directory,outdir):
    try:
        source=json.loads((directory/'v423_public_controls_results.json')
                          .read_text(encoding='utf-8'))
        candidate=json.loads((directory/'v432_recommendation_candidates.json')
                             .read_text(encoding='utf-8'))
        result=deduplicate(source,candidate)
    except (OSError,ValueError,TypeError):
        result=_empty('INCONCLUSIVE_INPUT_UNREADABLE')
    outdir.mkdir(parents=True,exist_ok=True)
    doc={'version':VERSION,'analyzed_utc':datetime.now(timezone.utc)
         .isoformat(timespec='seconds'),'evaluation':result,
         'unique_recommendation_candidates':{
            'ready_for_review':result['unique_candidate_count'],
            'full_recommendations_approved':0,
            'items':result['unique_candidates']},
         'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    (outdir/'v433_unique_candidates.json').write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (outdir/'v433_unique_candidates_report.md').write_text(
        report(result),encoding='utf-8')
    return 0 if result['dedup_complete'] else 2


def export_local_unique_links(result,links,target,public_dir):
    """Opt-in same-run private link file; never written by GitHub Actions."""
    if os.environ.get('GITHUB_ACTIONS') or os.environ.get('CI'):
        raise ValueError('PRIVATE_LINK_EXPORT_DISALLOWED_IN_CI')
    target=Path(target).resolve()
    public_dir=Path(public_dir).resolve()
    if target==public_dir or public_dir in target.parents:
        raise ValueError('PRIVATE_FILE_INSIDE_SHARED_ARTIFACT_DIR')
    if target.exists():
        raise FileExistsError('PRIVATE_LINK_FILE_ALREADY_EXISTS')
    if not isinstance(result,dict) or result.get('dedup_complete') is not True:
        raise ValueError('NO_CONFIRMED_UNIQUE_CANDIDATES')
    if not isinstance(links,list):
        raise ValueError('NO_PRIVATE_SAME_RUN_SOURCES')
    from daangn_v4_1_core import normalized_listing
    from daangn_v4_4_gate import stable_article_id
    sources={}
    for x in links:
        if not isinstance(x,dict):
            raise ValueError('INVALID_LINK_INPUT')
        key=_key(x.get('context'),x.get('source_rank'))
        raw=x.get('url')
        if (key is None or key in sources or type(x.get('price_krw')) is not int
            or not isinstance(raw,str) or normalized_listing(raw)!=raw
            or stable_article_id(raw) is None):
            raise ValueError('INVALID_OR_DUPLICATE_LOCAL_SOURCE')
        sources[key]=x
    output=[]
    for item in result['unique_candidates']:
        ids=set()
        source_urls=[]
        for observation in item['observations']:
            key=_key(observation['context'],observation['source_rank'])
            found=sources.get(key)
            if (found is None or found.get('price_krw')!=item['price_krw']
                or found.get('listing_run_hmac')!=item['listing_run_hmac']):
                raise ValueError('PRIVATE_LINK_MISSING_OR_IDENTITY_PRICE_CONFLICT')
            stable=stable_article_id(found['url'])
            ids.add(stable)
            source_urls.append(found['url'])
        if len(ids)!=1 or len(source_urls)!=item['observation_count']:
            raise ValueError('PRIVATE_LINKS_NOT_SAME_ACTUAL_LISTING')
        output.append({'listing_url':source_urls[0],
            'price_krw':item['price_krw'],
            'observation_count':item['observation_count'],
            'display_sale_status':item['display_sale_status'],
            'category':'디지털기기',
            'full_recommendation_approved':False})
    if len(output)!=result['unique_candidate_count']:
        raise ValueError('PRIVATE_UNIQUE_COUNT_MISMATCH')
    target.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:
        json.dump({'version':VERSION,'private_local_only':True,
            'current_sale_and_price_not_guaranteed':True,'items':output},
            stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    return len(output)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    return generate(args.evidence_dir.resolve(),args.output_dir.resolve())


if __name__=='__main__':
    raise SystemExit(main())
