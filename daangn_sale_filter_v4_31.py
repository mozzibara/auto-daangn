# -*- coding: utf-8 -*-
"""v4.31 production sale-filter policy: omit default FOR_SALE badge requirement.

An exact-item InStock offer + *observed absence of the current item's*
SOLD/RESERVED UI passes the SALE AVAILABILITY filter. This is a pragmatic
shopping candidate, not a verified marketplace transaction state.
Category/price/location/route/other listing-admission gates remain separate.

Pure code: no requests, accounts, or raw URLs/DOM/PII in outputs.
"""
from __future__ import annotations

import json
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter

from daangn_listing_state_v4_24 import clean_record
from app_v5.buy_now_policy import (
    classify_source_buy_now, assess_configured_district,
    HOLD as LOCALITY_HOLD, OUTSIDE as LOCALITY_OUTSIDE,
    UNVERIFIED as BUY_NOW_UNVERIFIED,
)

VERSION='4.31'
CONTEXTS=('cheonan_a','asan_control','cheonan_b')
PHASES=('initial','delayed','scrolled','narrow')
PASS='SALE_FILTER_PASS_IN_STOCK_NO_NEGATIVE_UI'
PASS_DIRECT='SALE_FILTER_PASS_EXPLICIT_FOR_SALE_UI'
BLOCK='SALE_FILTER_BLOCK_SOLD_OR_RESERVED'
UNKNOWN='SALE_FILTER_UNVERIFIED'
STOCK_CONTRADICTION='SALE_FILTER_BLOCK_STOCK_NOT_IN_STOCK'
BLOCK_OUTSIDE='SALE_FILTER_BLOCK_VERIFIED_OUT_OF_AREA'
HOLD_LOCALITY='SALE_FILTER_HOLD_BUY_NOW_LOCALITY'


def _out(code, canonical='NOT_VERIFIED'):
    allowed=code in (PASS,PASS_DIRECT)
    return {'sale_filter_status':code,'sale_filter_eligible':allowed,
        'sale_filter_basis':('DIRECT_FOR_SALE_PRIMARY_UI' if code==PASS_DIRECT
            else 'IN_STOCK_AND_NO_PRIMARY_SOLD_RESERVED_UI' if code==PASS
            else 'EXPLICIT_SOLD_OR_RESERVED_UI' if code==BLOCK
            else 'VERIFIED_OUTSIDE_CONFIGURED_DISTRICTS' if code==BLOCK_OUTSIDE
            else 'ITEM_DISTRICT_OR_BUY_NOW_PROOF_UNVERIFIED' if code==HOLD_LOCALITY
            else 'IN_STOCK_NOT_CONFIRMED' if code==STOCK_CONTRADICTION
            else 'INSUFFICIENT_EVIDENCE'),
        'display_status':('판매중 직접 확인' if code==PASS_DIRECT else
            '판매 가능 추정' if code==PASS else
            '판매완료·예약중 제외' if code==BLOCK else
            '지역 밖 매물 제외' if code==BLOCK_OUTSIDE else
            '매물 동·읍·면 확인 필요' if code==HOLD_LOCALITY else '판매 상태 미확인'),
        'is_inferred_available':code==PASS,
        'direct_for_sale_ui_required':False,
        'direct_for_sale_ui_observed':code==PASS_DIRECT,
        'canonical_transaction_status':canonical,
        'jsonld_promoted_to_transaction':False,
        'sold_reserved_absence_means_confirmed_for_sale':False,
        'full_recommendation_approved':False,
        'price_category_region_gate_overridden':False}


def _valid_diag(d,*,allow_explicit_for_sale=False):
    if not isinstance(d,dict) or d.get('role')!='SOURCE' or (
        d.get('dom_capture_status')!='CAPTURED'):
        return False
    p=d.get('probe')
    frames=d.get('phases')
    if not isinstance(p,dict) or not isinstance(frames,dict):
        return False
    # A current-item Buy Now marker is not negative sale evidence. A local
    # listing can have delivery enabled and still be reviewed for meetup.
    if classify_source_buy_now(d)['status'] == BUY_NOW_UNVERIFIED:
        return False
    if p.get('status') not in (
        ('NO_DIRECT_FOR_SALE_UI','DIRECT_FOR_SALE_UI')
            if allow_explicit_for_sale else ('NO_DIRECT_FOR_SALE_UI',)
        ) or p.get('scan_complete') is not True or (
        p.get('primary_valid') is not True):
        return False
    if p.get('primary_visible_sold_status')!=0 or (
        p.get('primary_visible_reserved_status')!=0):
        return False
    if set(frames)!=set(PHASES):
        return False
    for phase in PHASES:
        frame=frames[phase]
        if not isinstance(frame,dict) or any(
            frame.get(k) is not True for k in
            ('same_document_url','scan_complete','primary_heading_visible')):
            return False
        if frame.get('ui') in ('SOLD','RESERVED','AMBIGUOUS','NOT_VERIFIED'):
            return False
        if frame.get('ui') not in ('AVAILABLE','NOT_OBSERVABLE'):
            return False
        if not allow_explicit_for_sale and any(frame.get(key)!=0 for key in (
            'primary_exact_tokens','primary_visible_exact_tokens',
            'primary_nonvisible_exact_tokens')):
            # Any unresolved primary status token may hide SOLD/RESERVED.
            return False
    return True


def _valid_survey(s):
    if not isinstance(s,dict) or s.get('role')!='SOURCE':
        return False
    p=s.get('survey')
    if not isinstance(p,dict) or p.get('status')!='SURVEY_COMPLETE':
        return False
    if not (p.get('scan_complete') is True
            and p.get('primary_valid') is True
            and p.get('product_exact_url_match_count')==1
            and p.get('offer_availability')=='IN_STOCK'):
        return False
    if p.get('primary_visible_sold_text')!=0 or p.get(
        'primary_visible_reserved_text')!=0 or (
        p.get('primary_hidden_transaction_text') not in (0,None)):
        return False
    # Unknown per-product trade-state metadata is not an authoritative
    # sale witness; contradictory or uncalibrated values require review.
    if any(p.get(k) not in ('NOT_OBSERVABLE',None)
           for k in ('trade_attribute_status','exact_product_trade_status',
                     'page_meta_trade_status')):
        return False
    return True


def assess_source(record, *, diagnostic=None, survey=None):
    """Default practical policy for an already-validated exact source item.

    Canonical v4.24 NOT_OBSERVABLE is a successful completed check that no
    recognized explicit primary status UI appeared. If supplementary v4.28/
    v4.29 evidence is supplied, it must also be complete and noncontradictory.
    Neither optional probe nor six shared controls are mandatory per listing.
    """
    valid=clean_record(record)
    if valid is None or valid['context_kind']!='SOURCE':
        return _out(UNKNOWN)
    txn=valid['primary_transaction_status']
    if txn in ('SOLD','RESERVED'):
        return _out(BLOCK,txn)
    if txn in ('NOT_VERIFIED','AMBIGUOUS') or not (
        valid['identity_confirmed'] and valid['render_complete']):
        return _out(UNKNOWN,txn)
    if valid['independent_evidence_tier']=='QUARANTINED':
        return _out(UNKNOWN,txn)
    # Include same-item JSON-LD exact availability; InStock only conveys
    # availability, and never changes txn from NOT_OBSERVABLE to FOR_SALE.
    if valid['product_jsonld_exact_availability']!='IN_STOCK' or (
        valid['product_jsonld_stock_class']!='AVAILABLE'):
        return _out(STOCK_CONTRADICTION,txn)
    if txn not in ('NOT_OBSERVABLE','FOR_SALE'):
        return _out(UNKNOWN,txn)
    # No blanket city acceptance and no blanket Buy Now exclusion. A
    # deliberately configured dong/eup/myeon in the exact source Route item
    # must be verified before an item is a local meetup candidate.
    # Unknowns stay held; searchRegion can never substitute for this proof.
    diag = diagnostic if type(diagnostic) is dict else {}
    buy_now = classify_source_buy_now(diag)['status']
    local = assess_configured_district(
        buy_now, diag.get('item_area_status'), diag.get('item_area_key'))
    if local['decision'] == LOCALITY_OUTSIDE:
        return _out(BLOCK_OUTSIDE, txn)
    if local['decision'] == LOCALITY_HOLD:
        return _out(HOLD_LOCALITY, txn)
    if diagnostic is not None and not _valid_diag(
            diagnostic,allow_explicit_for_sale=(txn=='FOR_SALE')):
        return _out(UNKNOWN,txn)
    if survey is not None and not _valid_survey(survey):
        return _out(UNKNOWN,txn)
    # Even when a direct FOR_SALE marker is present, a complete current
    # item check + InStock is sufficient, but a marker is never required.
    return _out(PASS_DIRECT if txn=='FOR_SALE' else PASS,txn)


def evaluate_capture(v423, v429):
    """Project full 9-source v4.29 capture; no extra marketplace navigation."""
    if not all(isinstance(x,dict) for x in (v423,v429)):
        return _empty('INCONCLUSIVE_MISSING_INPUT')
    if v423.get('consumer_schema_version')!='4.26' or v429.get(
        'consumer_schema_version')!='4.26':
        return _empty('INCONCLUSIVE_WRONG_SOURCE_SCHEMA')
    e=v423.get('evaluation')
    previous=v429.get('evaluation')
    if not isinstance(e,dict) or not isinstance(previous,dict):
        return _empty('INCONCLUSIVE_EVALUATION_ABSENT')
    cs=e.get('contexts')
    if not isinstance(cs,list) or [c.get('context') for c in cs
        if isinstance(c,dict)]!=list(CONTEXTS):
        return _empty('INCONCLUSIVE_CONTEXT_ALIGNMENT')
    if e.get('bounded_capture_complete') is not True or (
        previous.get('survey_complete') is not True):
        return _empty('INCONCLUSIVE_INCOMPLETE_PREVIOUS_CAPTURE')
    rows=[]
    problems=[]
    for context in cs:
        main=context.get('source_state_models')
        diagnostic=context.get('v428_source_diagnostics')
        survey=context.get('v429_source_signal_surveys')
        if not all(isinstance(v,list) and len(v)==3
                   for v in (main,diagnostic,survey)):
            problems.append('SOURCE_TRIAD_MISSING')
            continue
        for a,b,c in zip(main,diagnostic,survey):
            if not all(isinstance(x,dict) for x in (a,b,c)):
                problems.append('SOURCE_RECORD_INVALID')
                continue
            rank=a.get('source_rank')
            if type(rank) is not int or rank<0 or rank>650 or (
                b.get('source_rank')!=rank or c.get('source_rank')!=rank):
                problems.append('RANK_OR_IDENTITY_ALIGNMENT_MISMATCH')
                continue
            result=assess_source(a.get('model'),diagnostic=b,survey=c)
            rows.append({'context':context['context'],'source_rank':rank,
                         **result})
    if len(rows)!=9:problems.append('WRONG_SOURCE_COUNT')
    if problems:
        rows=[{'context':x['context'],'source_rank':x['source_rank'],
               **_out(UNKNOWN,x['canonical_transaction_status'])}
              for x in rows]
    counts=Counter(x['sale_filter_status'] for x in rows)
    return {'status':('SALE_AVAILABILITY_POLICY_APPLIED'
                      if not problems else 'INCONCLUSIVE_SAMPLE_ALIGNMENT'),
        'policy_version':VERSION,'evaluation_complete':not problems,
        'source_visits_checked':len(rows),
        'sale_filter_passed':sum(x['sale_filter_eligible'] for x in rows),
        'inferred_possible_for_sale':counts[PASS],
        'direct_for_sale':counts[PASS_DIRECT],
        'blocked_sold_or_reserved':counts[BLOCK],
        'blocked_verified_out_of_area':counts[BLOCK_OUTSIDE],
        'held_buy_now_for_locality':counts[HOLD_LOCALITY],
        'unverified':counts[UNKNOWN]+counts[STOCK_CONTRADICTION]+counts[HOLD_LOCALITY],
        'reason_counts':dict(sorted(counts.items())),
        'direct_for_sale_required':False,
        'source_transaction_status_modified':False,
        'price_category_region_verification_claimed':False,
        'fully_approved_recommendations':0,
        'problems':sorted(set(problems)),'source_items':rows}


def _empty(code):
    return {'status':code,'policy_version':VERSION,'evaluation_complete':False,
        'source_visits_checked':0,'sale_filter_passed':0,
        'inferred_possible_for_sale':0,'direct_for_sale':0,
        'blocked_sold_or_reserved':0,'blocked_verified_out_of_area':0,
        'held_buy_now_for_locality':0,'unverified':0,'reason_counts':{},
        'direct_for_sale_required':False,'source_transaction_status_modified':False,
        'price_category_region_verification_claimed':False,
        'fully_approved_recommendations':0,
        'problems':['INPUT_INCOMPLETE'],'source_items':[]}


def report(e):
    return '\n'.join([
        '# v4.31 — pragmatic sale availability filtering','',
        f"- Result: **{e['status']}**",
        f"- Source detail visits: {e['source_visits_checked']}",
        f"- Pass sale availability filter: **{e['sale_filter_passed']}**",
        f"- Estimated possibly for sale: **{e['inferred_possible_for_sale']}**",
        f"- Direct FOR_SALE observed: {e['direct_for_sale']}",
        f"- Explicit SOLD/RESERVED blocked: {e['blocked_sold_or_reserved']}",
        f"- Verified out-of-area items blocked: {e['blocked_verified_out_of_area']}",
        f"- Buy Now locality verification pending: {e['held_buy_now_for_locality']}",
        f"- Unverified/conflicted: {e['unverified']}",
        f"- Per-status counts: {e['reason_counts']}",
        f"- Direct FOR_SALE badge required: {e['direct_for_sale_required']}",
        '- InStock + no same-item SOLD/RESERVED UI is a practical CANDIDATE policy, not direct transaction verification.',
        '- Primary canonical transaction status remains independent and unchanged.',
        '- Buy Now is a shipping option, NOT proof of remote location or inability to meet in person.',
        '- Local Buy Now is retained only with its own configured dong/eup/myeon proof; unknown locality is held, not deleted.',
        '- A generic purchase CTA alone is not a verified Buy Now flag.',
        '- No Buy Now classification repairs a mismatched search Route locality.',
        '- Existing server-price, category, regional scope and route proof gates are NOT bypassed.',
        '- Passing the sale filter alone NEVER approves a full recommendation.',
        f"- Fully approved recommendations: {e['fully_approved_recommendations']}",
        f"- Incomplete evidence: {e['problems']}",''])


def generate(evidence_dir,output_dir):
    """Use only existing redacted v4.29 local evidence files."""
    try:
        a=json.loads((evidence_dir/'v423_public_controls_results.json')
                     .read_text(encoding='utf-8'))
        b=json.loads((evidence_dir/'v429_public_status_results.json')
                     .read_text(encoding='utf-8'))
        result=evaluate_capture(a,b)
    except (OSError,ValueError,TypeError):
        result=_empty('INCONCLUSIVE_UNREADABLE_CAPTURE')
    output_dir.mkdir(parents=True,exist_ok=True)
    output={'version':VERSION,'utc':datetime.now(timezone.utc)
            .isoformat(timespec='seconds'),
            'availability_policy_only':True,'evaluation':result,
            'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    (output_dir/'v431_sale_filter_results.json').write_text(
        json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output_dir/'v431_sale_filter_report.md').write_text(
        report(result),encoding='utf-8')
    return 0 if result['evaluation_complete'] else 2


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Offline v4.31 sale filter policy')
    parser.add_argument('--evidence-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    opts=parser.parse_args()
    return generate(opts.evidence_dir.resolve(),opts.output_dir.resolve())


if __name__=='__main__':
    raise SystemExit(main())
