# -*- coding: utf-8 -*-
"""v4.27 bounded, privacy-redacted real-path consumer crosscheck.

The study executes ONE v4.24/v4.26-compatible live capture (9 source
details; at most 6 distinct linked controls), then independently re-evaluates
the *same in-memory capture's* v4.20/v4.21/v4.23/v4.24 witnesses offline.
It does not widen the crawl, infer SOLD from stock, or approve listings.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import re
from pathlib import Path

import daangn_detail_crosscheck_v4_20 as detail
import daangn_sale_sources_v4_21 as sale
import daangn_state_controls_v4_23 as controls
import daangn_state_model_study_v4_24 as study
import daangn_listing_state_v4_24 as model
from daangn_state_consumers_v4_25 import consume, source_comparison, control_comparison

CONTEXTS=('cheonan_a','asan_control','cheonan_b')
MAX_SOURCES=9
MAX_CONTROLS=6
ACCEPT='CANONICAL_PIPELINE_LIVE_CROSSCHECK_OBSERVED'


def _valid_document(doc):
    return (isinstance(doc,dict) and doc.get('consumer_schema_version')=='4.26'
            and doc.get('strict_listing_acceptance',{}).get('blocked') is True
            and doc.get('strict_listing_acceptance',{}).get('approved_listings') == [])


def _safe_comparison_status(text):
    return text if isinstance(text,str) and text.startswith('CANONICAL_') else 'INCONCLUSIVE'


def crosscheck(raw_v423,raw_v424):
    """Examine validated projections and independent consumer outputs only.

    No URL, item identifier, title, seller name or raw browser data appears in
    the returned evidence, including when supplied input is malformed.
    """
    discrepancies=[]
    source_items=[]
    control_items=[]
    diagnostics=[]
    if not (_valid_document(raw_v423) and _valid_document(raw_v424)):
        return _empty('INCONCLUSIVE_INVALID_OR_LEGACY_INPUT', ['INVALID_SOURCE_SCHEMA'])
    e=raw_v423.get('evaluation')
    e2=raw_v424.get('evaluation')
    if not isinstance(e,dict) or not isinstance(e2,dict):
        return _empty('INCONCLUSIVE_MISSING_CAPTURE', ['MISSING_EVALUATION'])
    originals=e.get('contexts')
    canonical_contexts=e2.get('context_models')
    if not isinstance(originals,list) or not isinstance(canonical_contexts,list):
        return _empty('INCONCLUSIVE_INVALID_CONTEXTS', ['CONTEXT_SCHEMA_INVALID'])
    if ([x.get('context') if isinstance(x,dict) else None for x in originals] != list(CONTEXTS)
        or [x.get('context') if isinstance(x,dict) else None for x in canonical_contexts] != list(CONTEXTS)):
        result=_empty('INCONCLUSIVE_CONTEXT_ALIGNMENT', ['CONTEXT_SET_OR_ORDER_MISMATCH'])
        errors=e.get('browser_capture_exception_types')
        if isinstance(errors,dict):
            result['browser_capture_exception_types']={
                k:v for k,v in errors.items() if isinstance(k,str)
                and re.fullmatch(r'STOP_[A-Za-z]{1,48}',k)
                and type(v) is int and 0<v<=3}
        return result

    source_visits=0
    control_visits=0
    stock_semantic=Counter()
    txn_counts=Counter()
    availability_counts=Counter()
    controls_by_state=Counter()
    ui_corrob=Counter()
    any_quarantined=False
    for context,src_ctx,projected in zip(CONTEXTS,originals,canonical_contexts):
        nsource=src_ctx.get('source_detail_count')
        ncontrol=src_ctx.get('visited_control_count')
        if type(nsource) is not int or not 0<=nsource<=3:
            discrepancies.append('SOURCE_VISIT_COUNT_INVALID')
            nsource=0
        if type(ncontrol) is not int or not 0<=ncontrol<=2:
            discrepancies.append('CONTROL_VISIT_COUNT_INVALID')
            ncontrol=0
        source_visits+=nsource
        control_visits+=ncontrol
        original_sources=src_ctx.get('source_state_models')
        raw_pipeline=src_ctx.get('v427_source_pipeline')
        original_controls=src_ctx.get('controls')
        projected_items=projected.get('items') if isinstance(projected,dict) else None
        if not all(isinstance(x,list) for x in (
            original_sources,raw_pipeline,original_controls,projected_items)):
            discrepancies.append('MISSING_PER_CONTEXT_EVIDENCE')
            diagnostics.append({'context':context,'status':'MISSING_CONTEXT_EVIDENCE'})
            continue
        ps=[x for x in projected_items if isinstance(x,dict) and x.get('role')=='SOURCE']
        pc=[x for x in projected_items if isinstance(x,dict) and x.get('role')=='CONTROL']
        if (len(original_sources)!=nsource or len(raw_pipeline)!=nsource
            or len(ps)!=nsource or len(pc)!=len(original_controls)
            or len(original_controls)>2 or ncontrol!=len(original_controls)):
            discrepancies.append('ROLE_CARDINALITY_MISMATCH')
        for i,(original,wire,projection) in enumerate(zip(
            original_sources[:3],raw_pipeline[:3],ps[:3])):
            if not isinstance(original,dict) or not isinstance(wire,dict):
                discrepancies.append('SOURCE_RECORD_INVALID')
                continue
            rank=original.get('source_rank')
            record=model.clean_record(original.get('model'))
            project_record=model.clean_record(projection.get('fields'))
            consumer=consume(record,'SOURCE')
            if (record is None or project_record!=record
                or rank!=projection.get('source_rank')
                or rank!=wire.get('source_rank')):
                discrepancies.append('SOURCE_PROJECTION_MISMATCH')
            if not consumer['schema_valid']:
                discrepancies.append('SOURCE_CANONICAL_INVALID')
                continue
            # Recompute stage decisions with a validated canonical record.
            v420=detail.classify_detail({
                'status':'OBSERVED' if wire.get('detail_http_200_identity') else 'NOT_OBSERVABLE',
                'primary_item_present':wire.get('detail_http_200_identity') is True,
                'primary_heading_visible':wire.get('primary_heading_visible') is True,
                'category':{'verdict':wire.get('category_verdict')}},
                wire.get('page_identity_confirmed') is True,record)
            v421=sale.compare_sources({
                'status':wire.get('v421_probe_status'),
                'valid_primary':wire.get('v421_primary_valid') is True},
                wire.get('page_identity_confirmed') is True,record)
            if v420!=wire.get('v420_verdict'):
                discrepancies.append('V420_DECISION_DIVERGENCE')
            if v421!=wire.get('v421_verdict') or v421!=source_comparison(record):
                discrepancies.append('V421_DECISION_DIVERGENCE')
            if not (wire.get('detail_http_200_identity') is True and
                    wire.get('page_identity_confirmed') is True):
                discrepancies.append('SOURCE_HTTP_OR_IDENTITY_NOT_VERIFIED')
            observed_ui=wire.get('v421_ui_status')
            txn={'AVAILABLE':'FOR_SALE','SOLD':'SOLD',
                 'RESERVED':'RESERVED'}.get(observed_ui)
            if txn and consumer['primary_transaction_status'] != txn:
                discrepancies.append('SOURCE_PRIMARY_UI_STATE_DIVERGENCE')
            if not txn and observed_ui=='NOT_OBSERVABLE' and consumer[
                    'primary_transaction_status'] in ('FOR_SALE','RESERVED','SOLD'):
                discrepancies.append('METADATA_TO_TRANSACTION_PROMOTION')
            other_ui=wire.get('v420_ui_status')
            if (other_ui in ('AVAILABLE','RESERVED','SOLD') and
                observed_ui in ('AVAILABLE','RESERVED','SOLD') and
                other_ui != observed_ui):
                discrepancies.append('INDEPENDENT_UI_PROBES_DISAGREE')
            v421_exact=wire.get('v421_exact_availability')
            if (wire.get('v421_product_match_count')==1 and
                v421_exact not in ('NOT_OBSERVABLE','AMBIGUOUS','OTHER') and
                consumer['product_jsonld_exact_availability']!=v421_exact):
                discrepancies.append('INDEPENDENT_JSONLD_PROBES_DISAGREE')
            if not record['availability_to_transaction_conversion_performed'] is False:
                discrepancies.append('FORBIDDEN_STOCK_TO_TRANSACTION_CONVERSION')
            if consumer['independent_evidence_tier']=='QUARANTINED':
                any_quarantined=True
            stock_semantic[record['transaction_stock_semantic_comparison']]+=1
            txn_counts[consumer['primary_transaction_status']]+=1
            availability_counts[consumer['product_jsonld_exact_availability']]+=1
            source_items.append({
                'context':context,'source_rank':rank,
                'transaction_status':consumer['primary_transaction_status'],
                'jsonld_exact_availability':consumer['product_jsonld_exact_availability'],
                'evidence_tier':consumer['independent_evidence_tier'],
                'v420_recomputed':v420,'v421_recomputed':_safe_comparison_status(v421),
                'stock_is_transaction_proof':False,'strict_listing_approved':False})
        for i,(control,projection) in enumerate(zip(original_controls[:2],pc[:2])):
            if not isinstance(control,dict):
                discrepancies.append('CONTROL_RECORD_INVALID')
                continue
            record=model.clean_record(control.get('v424_state_model'))
            projected_record=model.clean_record(projection.get('fields'))
            consumer=consume(record,'CONTROL')
            if (record is None or projected_record!=record or
                control.get('source_rank')!=projection.get('source_rank')):
                discrepancies.append('CONTROL_PROJECTION_MISMATCH')
            if not consumer['schema_valid']:
                discrepancies.append('CONTROL_CANONICAL_INVALID')
                continue
            code=control_comparison(record)
            if (control.get('comparison')!=code or
                control.get('v425_control_comparison')!=code):
                discrepancies.append('V423_DECISION_DIVERGENCE')
            if (control.get('status')!='AUDITED'
                or control.get('identity_matched') is not True):
                discrepancies.append('CONTROL_PRIMARY_DETAIL_NOT_VERIFIED')
            if record['linked_card_status']!=control.get('source_card_state'):
                discrepancies.append('LINKED_CARD_PROVENANCE_DIVERGENCE')
            if record['product_jsonld_exact_availability'] != control.get(
                    'target_jsonld_exact_kind'):
                discrepancies.append('CONTROL_JSONLD_PROBE_DIVERGENCE')
            if record['availability_to_transaction_conversion_performed'] is not False:
                discrepancies.append('FORBIDDEN_STOCK_TO_TRANSACTION_CONVERSION')
            if consumer['independent_evidence_tier']=='QUARANTINED':
                any_quarantined=True
            card=record['linked_card_status']
            controls_by_state[card]+=1
            if (consumer['card_ui_corroborated'] and
                consumer['primary_transaction_status']==card):
                ui_corrob[card]+=1
            stock_semantic[record['transaction_stock_semantic_comparison']]+=1
            txn_counts[consumer['primary_transaction_status']]+=1
            availability_counts[consumer['product_jsonld_exact_availability']]+=1
            control_items.append({
                'context':context,'source_rank':control.get('source_rank'),
                'linked_card_status':card,
                'target_transaction_status':consumer['primary_transaction_status'],
                'jsonld_exact_availability':consumer['product_jsonld_exact_availability'],
                'evidence_tier':consumer['independent_evidence_tier'],
                'v423_recomputed':code,'card_primary_ui_corroborated':consumer['card_ui_corroborated'],
                'strict_listing_approved':False})
        diagnostics.append({'context':context,
            'source_visit_count':nsource,'control_visit_count':ncontrol,
            'validated_source_records':len([x for x in source_items if x['context']==context]),
            'validated_control_records':len([x for x in control_items if x['context']==context])})

    base_complete=(source_visits==MAX_SOURCES and len(source_items)==MAX_SOURCES
                   and 0<=control_visits<=MAX_CONTROLS
                   and control_visits==len(control_items)
                   and e.get('bounded_capture_complete') is True
                   and e2.get('capture_complete') is True
                   and e2.get('status')=='ORTHOGONAL_STATE_MODEL_OBSERVED'
                   and e2.get('source_record_count')==MAX_SOURCES
                   and e2.get('control_record_count')==control_visits)
    original_verdict=e.get('status') if isinstance(e.get('status'),str) and e['status'] in (
        'BOTH_SOLD_AND_RESERVED_CONTROL_UI_CORROBORATED',
        'PARTIAL_CONTROL_CLASSES_AVAILABLE',
        'PARTIAL_CONTROL_UI_CORROBORATED','CONTROL_UI_NOT_OBSERVABLE',
        'PUBLIC_CONTROL_WITNESSES_CONFLICT',
        'INCONCLUSIVE_CONTROL_STUDY_INCOMPLETE','STOP_ACCESS_RESTRICTION') else 'INCONCLUSIVE'
    if discrepancies:
        status='QUARANTINED_PIPELINE_DIVERGENCE'
    elif not base_complete:
        status='INCONCLUSIVE_BOUNDED_CAPTURE_INCOMPLETE'
    elif any_quarantined:
        status='QUARANTINED_SEMANTIC_CONFLICT'
    elif not (ui_corrob['SOLD']>=1 and ui_corrob['RESERVED']>=1):
        status='INCONCLUSIVE_CONTROL_CLASSES_NOT_CORROBORATED'
    else:
        status=ACCEPT
    return {
        'status':status,'capture_complete':base_complete and not discrepancies,
        'source_detail_visits':source_visits,'control_detail_visits':control_visits,
        'validated_source_records':len(source_items),
        'validated_control_records':len(control_items),
        'pipeline_discrepancy_count':len(discrepancies),
        'pipeline_discrepancy_codes':dict(sorted(Counter(discrepancies).items())),
        'semantic_quarantine_observed':any_quarantined,
        'control_classes_observed':dict(sorted(controls_by_state.items())),
        'control_ui_corroboration_count':dict(sorted(ui_corrob.items())),
        'transaction_status_counts':dict(sorted(txn_counts.items())),
        'exact_stock_availability_counts':dict(sorted(availability_counts.items())),
        'stock_semantic_comparison_counts':dict(sorted(stock_semantic.items())),
        'v423_independent_verdict':original_verdict,
        'v424_canonical_verdict':e2.get('status') if e2.get('status') in (
            'ORTHOGONAL_STATE_MODEL_OBSERVED','QUARANTINED_SEMANTIC_CONFLICT') else 'INCONCLUSIVE',
        'strict_listing_gate_changed':False,
        'strict_listing_approved_count':0,
        'stock_metadata_promoted_to_transaction':False,
        'card_status_promoted_to_primary_ui':False,
        'all_route_listings_verified':False,
        'contexts':diagnostics,
        'source_witnesses':source_items,'control_witnesses':control_items}


def _empty(status,issues):
    return {'status':status,'capture_complete':False,
        'source_detail_visits':0,'control_detail_visits':0,
        'validated_source_records':0,'validated_control_records':0,
        'pipeline_discrepancy_count':len(issues),
        'pipeline_discrepancy_codes':dict(sorted(Counter(issues).items())),
        'browser_capture_exception_types':{},
        'strict_listing_approved_count':0,
        'stock_metadata_promoted_to_transaction':False,
        'card_status_promoted_to_primary_ui':False,
        'all_route_listings_verified':False,
        'contexts':[],'source_witnesses':[],'control_witnesses':[]}


def render_report(result):
    lines=['# v4.27 — independent real-path canonical consumer crosscheck','',
        f"- Verdict: **{result['status']}**",
        f"- Original source detail visits: {result['source_detail_visits']} / {MAX_SOURCES}",
        f"- Linked control detail visits: {result['control_detail_visits']} / {MAX_CONTROLS} (maximum)",
        f"- Validated source canonical records: {result['validated_source_records']}",
        f"- Validated control canonical records: {result['validated_control_records']}",
        f"- Cross-stage divergences: {result['pipeline_discrepancy_count']}",
        f"- Divergence codes: {result['pipeline_discrepancy_codes']}",
        f"- Browser startup exception types: {result.get('browser_capture_exception_types',{})}",
        f"- Primary control UI corroborations: {result.get('control_ui_corroboration_count',{})}",
        f"- Exact JSON-LD availability counts: {result.get('exact_stock_availability_counts',{})}",
        f"- Independent transaction counts: {result.get('transaction_status_counts',{})}",
        '', '## Interpretation','',
        '- Source and control counts are page visits, not guaranteed unique market listings.',
        '- Observations are bounded to public exact-identity pages, verified before visits against robots.txt.',
        '- v4.20 UI, v4.21 independent source, v4.23 control and v4.24 canonical projection are recomputed from one bounded capture.',
        '- OutOfStock is not SOLD and SoldOut is a different exact stock value; neither proves a completed sale.',
        '- Missing controls or conflicting independent witnesses are explicitly inconclusive/quarantined.',
        '- Strict price/category/server-filter listing admission is unchanged; approved listings: 0.','']
    return '\n'.join(lines)


async def run(opts):
    # v4.23 browser launch expects .headed even for headless unattended use.
    opts.headed=getattr(opts,'headed',False) is True
    # Reuse the existing three-context public, robots-gated 9+6 capture only once.
    legacy_exit=await study.run(opts)
    d=opts.output_dir
    try:
        old=json.loads((d/'v423_public_controls_results.json').read_text(encoding='utf-8'))
        current=json.loads((d/'v424_state_model_results.json').read_text(encoding='utf-8'))
        verdict=crosscheck(old,current)
    except (OSError,ValueError,TypeError):
        verdict=_empty('INCONCLUSIVE_CAPTURE_FILES_UNAVAILABLE',
                       ['CAPTURE_FILE_UNAVAILABLE_OR_INVALID'])
    # The previous capture's exit status is an independent prerequisite.
    if legacy_exit!=0 and verdict['status']==ACCEPT:
        verdict['status']='INCONCLUSIVE_PREVIOUS_STAGE_FAILED'
    artifact={
        'version':'4.27','consumer_schema_version':'4.26',
        'canonical_state_schema_version':'4.24',
        'collected_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'design':{'contexts':list(CONTEXTS),'source_detail_max':MAX_SOURCES,
                  'control_detail_max':MAX_CONTROLS,
                  'single_live_capture':True,
                  'strict_listing_gate_changed':False},
        'evaluation':verdict,
        'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    d.mkdir(parents=True,exist_ok=True)
    (d/'v427_crosscheck_results.json').write_text(
        json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (d/'v427_crosscheck_report.md').write_text(
        render_report(verdict),encoding='utf-8')
    (d/'v427_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if legacy_exit==0 and verdict['status']==ACCEPT else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v427_live_output'))
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--headed',action='store_true')
    opts=p.parse_args()
    opts.output_dir=opts.output_dir.resolve()
    opts.timeout=max(15,min(45,opts.timeout))
    opts.settle_ms=max(800,min(3500,opts.settle_ms))
    return asyncio.run(run(opts))


if __name__=='__main__':
    raise SystemExit(main())
