# -*- coding: utf-8 -*-
"""v4.29: owner-approved public status signal study, no unauthorized transition.

One bounded v4.28-backed capture of 9 source + <=6 controls. The owner
before/after experiment is a separate *offline protocol* and never triggers
a marketplace state mutation or automated revisit.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import daangn_for_sale_study_v4_28 as previous

ACCEPT_NO_PROOF='PUBLIC_STATUS_SIGNAL_SURVEY_COMPLETE_NO_DIRECT_FOR_SALE_PROOF'
ACCEPT_DIRECT='PUBLIC_DIRECT_FOR_SALE_UI_CONFIRMED'
COUNTS=('explicit_trade_attribute_nodes',
        'exact_product_additional_trade_properties','page_meta_trade_properties',
        'primary_visible_for_sale_text','primary_visible_sold_text',
        'primary_visible_reserved_text','primary_transaction_semantic_nodes',
        'current_primary_button_status_text_nodes','microdata_stock_nodes')


def _missing(code):
    return {'status':code,'survey_complete':False,'source_visits':0,
        'control_visits':0,'source_surveys':0,'control_surveys':0,
        'explicit_direct_for_sale_evidence':0,'independent_trade_field_candidates':0,
        'candidate_for_sale_authoritative':False,
        'default_badge_omission_proven':False,'real_owner_transition_performed':False,
        'no_stock_to_trade_conversion':True,'strict_listing_approved_count':0,
        'source_cases':[],'control_cases':[],'issues':{'INCOMPLETE_INPUT':1}}


def analyze(raw_v423,raw_v427,raw_v428):
    if not all(isinstance(x,dict) for x in (raw_v423,raw_v427,raw_v428)):
        return _missing('INCONCLUSIVE_MISSING_PIPELINE_EVIDENCE')
    e=raw_v423.get('evaluation')
    cross=raw_v427.get('evaluation')
    prior=raw_v428.get('evaluation')
    if any(not isinstance(x,dict) for x in (e,cross,prior)) or any(
        x.get('consumer_schema_version')!='4.26'
        for x in (raw_v423,raw_v427,raw_v428)):
        return _missing('INCONCLUSIVE_LEGACY_OR_INVALID_EVIDENCE')
    contexts=e.get('contexts')
    if not isinstance(contexts,list) or len(contexts)!=3 or (
        [x.get('context') for x in contexts if isinstance(x,dict)]
        !=['cheonan_a','asan_control','cheonan_b']):
        return _missing('INCONCLUSIVE_CONTEXT_IDENTITY')
    issues=Counter()
    rows_source=[]
    rows_control=[]
    count_fields=Counter()
    types=Counter()
    exact=Counter()
    for row in contexts:
        ctx=row['context']
        sources=row.get('v429_source_signal_surveys')
        controls=row.get('v429_control_signal_surveys')
        canonical=row.get('source_state_models')
        original_ctrl=row.get('controls')
        if not all(isinstance(x,list) for x in
                   (sources,controls,canonical,original_ctrl)):
            issues['MISSING_CONTEXT_SIGNAL_SURVEYS']+=1
            continue
        if (len(sources)!=len(canonical) or len(sources)!=3
            or len(controls)!=len(original_ctrl) or len(controls)>2):
            issues['SCOPE_COUNT_MISMATCH']+=1
        for role,signals,originals,out in (
            ('SOURCE',sources,canonical,rows_source),
            ('CONTROL',controls,original_ctrl,rows_control)):
            for entry,orig in zip(signals,originals):
                if not isinstance(entry,dict) or not isinstance(orig,dict):
                    issues['INVALID_SOURCE_OR_CONTROL_ITEM']+=1
                    continue
                safe=entry.get('survey')
                if not isinstance(safe,dict) or entry.get('role')!=role or (
                    entry.get('source_rank')!=orig.get('source_rank')):
                    issues['SURVEY_ROLE_OR_RANK_MISMATCH']+=1
                    continue
                status=safe.get('status')
                if status!='SURVEY_COMPLETE':
                    issues['PUBLIC_PRIMARY_SURVEY_INCOMPLETE']+=1
                if safe.get('direct_for_sale_proven') is not False or (
                    safe.get('machine_trade_field_calibrated') is not False or
                    safe.get('stock_metadata_is_transaction_proof') is not False):
                    issues['PROHIBITED_METADATA_PROOF_PROMOTION']+=1
                candidate=any(safe.get(k) in ('FOR_SALE','SOLD','RESERVED')
                    for k in ('exact_product_trade_status','trade_attribute_status',
                              'page_meta_trade_status'))
                exact[safe.get('offer_availability') if safe.get(
                    'offer_availability') in (
                    'IN_STOCK','OUT_OF_STOCK','SOLD_OUT','RESERVED','PRE_ORDER',
                    'PRE_SALE','OTHER','NOT_OBSERVABLE','AMBIGUOUS')
                    else 'INVALID']+=1
                for field in COUNTS:
                    v=safe.get(field)
                    if type(v) is not int or not 0<=v<=3500:
                        issues['INVALID_FINITE_FIELD_COUNT']+=1
                    else:
                        count_fields[role+'_'+field]+=v
                for name in ('trade_attribute_status','exact_product_trade_status',
                             'page_meta_trade_status'):
                    val=safe.get(name)
                    if not isinstance(val,str) or val not in (
                        'FOR_SALE','SOLD','RESERVED','NOT_OBSERVABLE','AMBIGUOUS'):
                        issues['INVALID_STATUS_ENUM']+=1
                    else:
                        types[role+'_'+name+'_'+val]+=1
                out.append({'context':ctx,'role':role,
                    'source_rank':entry.get('source_rank'),
                    'survey_status':status,
                    'product_exact_match_count':safe.get('product_exact_url_match_count'),
                    'offer_availability':safe.get('offer_availability'),
                    'primary_visible_for_sale_token_count':safe.get(
                        'primary_visible_for_sale_text'),
                    'uncalibrated_trade_attribute':safe.get('trade_attribute_status'),
                    'uncalibrated_exact_product_property':safe.get(
                        'exact_product_trade_status'),
                    'uncalibrated_page_metadata':safe.get('page_meta_trade_status'),
                    'independent_candidate_detected':candidate,
                    'marketplace_transaction_proven_by_this_survey':False,
                    'strict_listing_approved':False})
    source_count=e.get('source_detail_visits')
    control_count=e.get('actual_control_page_visits')
    complete=(len(rows_source)==9 and len(rows_control)==control_count
        and type(source_count) is int and source_count==9
        and type(control_count) is int and 0<=control_count<=6
        and cross.get('status')=='CANONICAL_PIPELINE_LIVE_CROSSCHECK_OBSERVED'
        and prior.get('status') in (
            previous.SUCCESS, previous.NO_PROOF)
        and prior.get('diagnosis_complete') is True
        and prior.get('source_visits')==9
        and prior.get('control_visits')==control_count)
    direct=prior.get('verified_for_sale_records')
    if type(direct) is not int or not 0<=direct<=9:
        issues['INVALID_PRIOR_DIRECT_PROOF_COUNT']+=1
        direct=0
    candidate_count=sum(x['independent_candidate_detected']
                        for x in rows_source+rows_control)
    if issues:
        status='QUARANTINED_OR_INCOMPLETE_PUBLIC_SIGNAL_SURVEY'
    elif not complete:
        status='INCONCLUSIVE_INCOMPLETE_BOUNDED_CAPTURE'
    elif direct:
        status=ACCEPT_DIRECT
    else:
        status=ACCEPT_NO_PROOF
    return {'status':status,'survey_complete':complete and not issues,
        'source_visits':source_count if type(source_count) is int else 0,
        'control_visits':control_count if type(control_count) is int else 0,
        'source_surveys':len(rows_source),'control_surveys':len(rows_control),
        'explicit_direct_for_sale_evidence':direct if not issues else 0,
        'independent_trade_field_candidates':candidate_count,
        'candidate_for_sale_authoritative':False,
        'custom_field_value_counts':dict(sorted(types.items())),
        'field_presence_counts':dict(sorted(count_fields.items())),
        'exact_offer_availability_distribution':dict(sorted(exact.items())),
        'default_badge_omission_proven':False,
        'real_owner_transition_performed':False,
        'no_stock_to_trade_conversion':True,
        'strict_listing_approved_count':0,
        'issues':dict(sorted(issues.items())),
        'source_cases':rows_source,'control_cases':rows_control}


def report(e):
    lines=['# v4.29 — public item-scoped status and structured-data evidence','',
        f"- Public status survey: **{e['status']}**",
        f"- Bounded source/control detail visits: {e['source_visits']} / {e['control_visits']}",
        f"- Completed source/control surveys: {e['source_surveys']} / {e['control_surveys']}",
        f"- Direct FOR_SALE UI evidence (v4.28 confirmed): {e['explicit_direct_for_sale_evidence']}",
        f"- Uncalibrated transaction-like machine-field candidates: {e['independent_trade_field_candidates']}",
        f"- Exact Product Offer availability: {e.get('exact_offer_availability_distribution',{})}",
        f"- Primary status field and token presence: {e.get('field_presence_counts',{})}",
        f"- Calibrated trade status field: **NO**",
        f"- Survey completion: {e['survey_complete']}",
        f"- Failed-close issues: {e['issues']}",
        '', '## Evidence tiers','',
        '- An exact public Product offers availability property is official schema.org structured DATA, but it is about inventory, not independently verified marketplace trade status.',
        '- A primary item data-* field or custom Product.additionalProperty can be a candidate, but it is not an official, calibrated trade-state interface without platform documentation and same-item transition validation.',
        '- InStock + absence of sold/reserved badge is compatible with default omission, but does not prove the default hypothesis or transaction availability.',
        '- This run does not perform a before/after owner-controlled transition.',
        '- No live state mutations, logins, seller contacts, API bypass, or listing approvals.','']
    return '\n'.join(lines)


async def run(options):
    options.status_signals_v429=True
    options.for_sale_diagnosis_v428=True
    # Public GitHub Actions must never write live listing URLs into artifacts.
    private_path=getattr(options,'private_links_output',None)
    sealed_key=getattr(options,'sealed_public_key',None)
    if private_path is not None and sealed_key is not None:
        raise ValueError('MUTUALLY_EXCLUSIVE_PLAINTEXT_AND_ENCRYPTED_OUTPUT')
    if sealed_key is not None:
        # Validate recipient BEFORE any marketplace access. Only the
        # asymmetric PUBLIC key enters the GitHub runner.
        from daangn_secure_links_v4_34 import validate_public_key
        validate_public_key(sealed_key)
        options.v432_local_link_sink=[]
    if private_path is not None:
        import os
        if os.environ.get('GITHUB_ACTIONS') or os.environ.get('CI'):
            raise ValueError('PRIVATE_LISTING_LINKS_FORBIDDEN_IN_CI')
        private_path=Path(private_path).resolve()
        if options.output_dir==private_path or options.output_dir in private_path.parents:
            raise ValueError('PRIVATE_LINKS_MUST_BE_OUTSIDE_PUBLIC_OUTPUT')
        options.v432_local_link_sink=[]
    code=await previous.run(options)
    d=options.output_dir
    try:
        a=json.loads((d/'v423_public_controls_results.json').read_text(encoding='utf-8'))
        b=json.loads((d/'v427_crosscheck_results.json').read_text(encoding='utf-8'))
        c=json.loads((d/'v428_for_sale_results.json').read_text(encoding='utf-8'))
        result=analyze(a,b,c)
    except (OSError,ValueError,TypeError):
        result=_missing('INCONCLUSIVE_CAPTURE_ARTIFACTS_UNAVAILABLE')
    if code!=0 and result['status'] in (ACCEPT_DIRECT,ACCEPT_NO_PROOF):
        result['status']='INCONCLUSIVE_UPSTREAM_CAPTURE_FAILURE'
    doc={'version':'4.29','consumer_schema_version':'4.26',
        'canonical_model_version':'4.24',
        'utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'design':{'one_live_capture':True,'source_detail_max':9,
            'control_detail_max':6,
            'official_status_change_not_attempted':True,
            'strict_listing_gate_changed':False},
        'evaluation':result,
        'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    d.mkdir(parents=True,exist_ok=True)
    (d/'v429_public_status_results.json').write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (d/'v429_public_status_report.md').write_text(
        report(result),encoding='utf-8')
    (d/'v429_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    # v4.30 is a presentation-only consumer of the SAME archived capture.
    # It never changes v4.24 primary_transaction_status or accepts listings.
    from daangn_availability_estimate_v4_30 import generate as estimate
    estimate_rc=estimate(d,d)
    # Presentation-only estimation is explicitly non-authoritative.
    # Missing/incomplete negative controls must invalidate the overlay,
    # but must NOT turn a scientifically valid v4.29 survey into failure.
    if estimate_rc!=0:
        print('v4.30 availability projection INCONCLUSIVE (no status promotion)')
    # v4.31: practical sale-filter predicate reuses the same saved v4.29
    # data. Its output is distinct from full price/category admission.
    from daangn_sale_filter_v4_31 import generate as sale_filter
    filter_rc=sale_filter(d,d)
    if filter_rc!=0:
        print('v4.31 sale filter INCONCLUSIVE (no listing admission)')
    # v4.32: join source-specific sale + matched Route price + detail
    # category into a redacted RECOMMENDATION CANDIDATE queue.
    from daangn_recommendation_candidates_v4_32 import generate as candidate_generate
    candidate_rc=candidate_generate(d,d)
    if candidate_rc!=0:
        print('v4.32 candidate join INCONCLUSIVE (no recommendation approval)')
    # v4.33: one same-run keyed listing ID per observed article; no
    # extra browsing. Historical archives lacking identity are NOT unique.
    from daangn_unique_candidates_v4_33 import generate as unique_generate
    unique_rc=unique_generate(d,d)
    if unique_rc!=0:
        print('v4.33 deduplication INCONCLUSIVE (no unique candidate claims)')
    if private_path is not None and candidate_rc==0 and code==0:
        if unique_rc!=0:
            raise ValueError('PRIVATE_LINK_EXPORT_BLOCKED_UNVERIFIED_DEDUP')
        doc=json.loads((d/'v433_unique_candidates.json')
                       .read_text(encoding='utf-8'))
        from daangn_secure_links_v4_34 import write_local_clickable
        exported=write_local_clickable(doc['evaluation'],
            options.v432_local_link_sink,private_path,d)
        print('v4.34 local-only deduplicated titles and links:',exported)
    if sealed_key is not None:
        if unique_rc!=0 or candidate_rc!=0 or code!=0:
            raise ValueError('V434_SEALED_LINKS_REQUIRE_VERIFIED_CAPTURE')
        from daangn_secure_links_v4_34 import write_sealed
        unique=json.loads((d/'v433_unique_candidates.json')
                          .read_text(encoding='utf-8'))
        summary=write_sealed(unique['evaluation'],
            options.v432_local_link_sink,sealed_key,d)
        # No plaintext listing URL/title may reach runner logs.
        print('v4.34 AES-GCM sealed unique titles and links:',
              summary['linked_unique_candidates'],
              'unlinked_title_groups:',summary['quarantined_title_groups'])
    return 0 if (code==0 and
        result['status'] in (ACCEPT_DIRECT,ACCEPT_NO_PROOF)) else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v429_live_output'))
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--headed',action='store_true')
    p.add_argument('--private-links-output',type=Path,default=None,
                   help='LOCAL ONLY: explicit private listing links outside public artifacts')
    p.add_argument('--sealed-public-key',default=None,
                   help='One-time recipient X25519 PUBLIC key, base64; all titles/URLs encrypted')
    opts=p.parse_args()
    opts.output_dir=opts.output_dir.resolve()
    opts.timeout=max(15,min(45,opts.timeout))
    opts.settle_ms=max(800,min(3500,opts.settle_ms))
    return asyncio.run(run(opts))


if __name__=='__main__':
    raise SystemExit(main())
