# -*- coding: utf-8 -*-
"""v4.30 conservative display-only listing availability hypothesis.

The marketplace may omit a FOR_SALE badge as the default. This is a
bounded, falsifiable presentation hypothesis, NOT a new transaction state.
Never edit v4.24 canonical records or approve listings via an inference.

No network requests; accepts previously captured redacted v4.29 9+6 evidence.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime,timezone
import argparse
import json
from pathlib import Path

from daangn_listing_state_v4_24 import clean_record
from daangn_state_consumers_v4_25 import consume

VERSION='4.30'
PHASES=('initial','delayed','scrolled','narrow')
CONTEXTS=('cheonan_a','asan_control','cheonan_b')
ESTIMATES=frozenset({
    'FOR_SALE_DIRECTLY_VERIFIED','POSSIBLY_FOR_SALE_BADGE_OMITTED',
    'SOLD_DIRECTLY_VERIFIED','RESERVED_DIRECTLY_VERIFIED',
    'UNKNOWN_OR_CONFLICT'})
LABELS={
    'FOR_SALE_DIRECTLY_VERIFIED':'판매중 직접 확인',
    'POSSIBLY_FOR_SALE_BADGE_OMITTED':'판매 가능 추정',
    'SOLD_DIRECTLY_VERIFIED':'판매완료 확인',
    'RESERVED_DIRECTLY_VERIFIED':'예약중 확인',
    'UNKNOWN_OR_CONFLICT':'상태 미확인'}
BASIS={
    'FOR_SALE_DIRECTLY_VERIFIED':'EXPLICIT_PRIMARY_UI',
    'POSSIBLY_FOR_SALE_BADGE_OMITTED':'BADGE_OMISSION_HYPOTHESIS',
    'SOLD_DIRECTLY_VERIFIED':'EXPLICIT_PRIMARY_UI',
    'RESERVED_DIRECTLY_VERIFIED':'EXPLICIT_PRIMARY_UI',
    'UNKNOWN_OR_CONFLICT':'INSUFFICIENT_OR_CONTRADICTORY'}
STOCK_FIELDS=('exact_product_trade_status','trade_attribute_status',
              'page_meta_trade_status')
SIGNAL_COUNTERS=(
    'primary_visible_transaction_text','primary_visible_for_sale_text',
    'primary_visible_sold_text','primary_visible_reserved_text',
    'primary_hidden_transaction_text',
    'explicit_trade_attribute_nodes',
    'exact_product_additional_trade_properties',
    'page_meta_trade_properties')
PROBE_COUNTERS=('primary_visible_positive_status','primary_visible_sold_status',
                'primary_visible_reserved_status',
                'primary_hidden_positive_status',
                'primary_visible_unmarked_available_text')


def _result(label='UNKNOWN_OR_CONFLICT',reason='INCOMPLETE_OR_CONFLICTING_EVIDENCE',
            *,canonical='NOT_VERIFIED'):
    """Presentation-only evidence; keep transaction model immutable."""
    return {
        'presentation_estimate':label,
        'display_label':LABELS[label],
        'estimate_basis':BASIS[label],
        'reason_code':reason,
        'canonical_transaction_status':canonical,
        'primary_ui_for_sale_verified':label=='FOR_SALE_DIRECTLY_VERIFIED',
        'is_inference':label=='POSSIBLY_FOR_SALE_BADGE_OMITTED',
        'badge_omission_policy_proven':False,
        'not_verified_for_sale_when_inferred':True,
        'strict_listing_approved':False,
        'used_for_strict_filter_gate':False}


def _count_zero(obj,keys):
    return isinstance(obj,dict) and all(
        type(obj.get(k)) is int and obj[k]==0 for k in keys)


def classify_source(record,forensics,survey,*,control_calibrated=False):
    """Explicit UI can confirm; exact InStock + no badge can only estimate.

    A negative status is never inferred from stock and unrelated listing cards
    never establish current item state. All sources must agree at item rank.
    """
    safe=clean_record(record)
    view=consume(safe,'SOURCE')
    if not view['schema_valid'] or view['status']=='CANONICAL_QUARANTINED':
        return _result(reason='CANONICAL_INVALID_OR_QUARANTINED')
    txn=view['primary_transaction_status']
    if txn in ('FOR_SALE','SOLD','RESERVED') and view['primary_ui_proven']:
        return _result({
            'FOR_SALE':'FOR_SALE_DIRECTLY_VERIFIED',
            'SOLD':'SOLD_DIRECTLY_VERIFIED',
            'RESERVED':'RESERVED_DIRECTLY_VERIFIED'}[txn],
            reason='EXPLICIT_MATCHED_PRIMARY_UI',
            canonical=txn)
    if txn!='NOT_OBSERVABLE':
        return _result(reason='NO_RELIABLE_PRIMARY_STATE',canonical=txn)
    if not control_calibrated:
        return _result(reason='MISSING_SOLD_AND_RESERVED_NEGATIVE_CONTROLS',
                       canonical=txn)
    if (safe['product_jsonld_exact_availability']!='IN_STOCK'
        or safe['product_jsonld_stock_class']!='AVAILABLE'):
        return _result(reason='EXACT_ITEM_STOCK_NOT_IN_STOCK',canonical=txn)
    if not (safe['identity_confirmed'] and safe['render_complete']):
        return _result(reason='CURRENT_ITEM_IDENTITY_OR_RENDER_NOT_CONFIRMED',
                       canonical=txn)
    if not isinstance(forensics,dict) or not isinstance(survey,dict):
        return _result(reason='INCOMPLETE_DIAGNOSTIC',canonical=txn)
    p=forensics.get('probe')
    q=survey.get('survey')
    phases=forensics.get('phases')
    if (forensics.get('role')!='SOURCE' or
        survey.get('role')!='SOURCE' or
        forensics.get('source_rank')!=survey.get('source_rank') or
        forensics.get('dom_capture_status')!='CAPTURED' or
        not isinstance(p,dict) or not isinstance(q,dict) or
        not isinstance(phases,dict)):
        return _result(reason='SCOPE_OR_DIAGNOSTIC_MISMATCH',canonical=txn)
    if (p.get('status')!='NO_DIRECT_FOR_SALE_UI' or
        p.get('scan_complete') is not True or p.get('primary_valid') is not True
        or p.get('explicit_positive_proof') is not False or
        q.get('status')!='SURVEY_COMPLETE' or
        q.get('scan_complete') is not True or
        q.get('primary_valid') is not True or
        q.get('product_exact_url_match_count')!=1 or
        q.get('offer_availability')!='IN_STOCK' or
        q.get('direct_for_sale_proven') is not False or
        q.get('machine_trade_field_calibrated') is not False or
        q.get('stock_metadata_is_transaction_proof') is not False):
        return _result(reason='EXPLICIT_PROOF_OR_SURVEY_INCONSISTENT',canonical=txn)
    if not _count_zero(p,PROBE_COUNTERS) or not _count_zero(q,SIGNAL_COUNTERS):
        return _result(reason='CURRENT_ITEM_STATUS_CANDIDATE_OR_CONFLICT',
                       canonical=txn)
    if any(q.get(k)!='NOT_OBSERVABLE' for k in STOCK_FIELDS):
        return _result(reason='UNRESOLVED_MACHINE_STATE_CANDIDATE',
                       canonical=txn)
    if set(phases)!=set(PHASES) or any(
        not isinstance(phases[k],dict) or
        phases[k].get('same_document_url') is not True or
        phases[k].get('scan_complete') is not True or
        phases[k].get('primary_heading_visible') is not True or
        phases[k].get('ui')!='NOT_OBSERVABLE' or
        phases[k].get('primary_exact_tokens')!=0 or
        phases[k].get('primary_visible_exact_tokens')!=0 or
        phases[k].get('primary_nonvisible_exact_tokens')!=0
        for k in PHASES):
        return _result(reason='FOUR_PHASE_PRIMARY_UI_ABSENCE_NOT_ESTABLISHED',
                       canonical=txn)
    # Another item's status tokens may exist; they cannot prove this item.
    return _result('POSSIBLY_FOR_SALE_BADGE_OMITTED',
                   reason='IN_STOCK_PLUS_FOUR_PHASE_NO_BADGE_WITH_NEGATIVE_CONTROLS',
                   canonical=txn)


def _controls_valid(e):
    if e.get('both_control_classes_verified') is not True:
        return False
    if e.get('sold_control_detail_audits')!=3 or e.get(
        'reserved_control_detail_audits')!=3:
        return False
    if e.get('control_ui_card_concordances')!=6:
        return False
    for row in e.get('contexts',[]):
        controls=row.get('controls')
        surveys=row.get('v429_control_signal_surveys')
        if not isinstance(controls,list) or not isinstance(surveys,list) or (
            len(controls)!=2 or len(surveys)!=2):
            return False
        if {x.get('source_card_state') for x in controls}!={'SOLD','RESERVED'}:
            return False
        for control,survey in zip(controls,surveys):
            if control.get('status')!='AUDITED' or control.get(
                'identity_matched') is not True or control.get(
                'page_status')!='HTTP_200_EXACT_IDENTITY':
                return False
            view=consume(control.get('v424_state_model'),'CONTROL')
            state=control.get('source_card_state')
            if not (view['schema_valid'] and view['primary_ui_proven'] and
                view['card_ui_corroborated'] and
                view['primary_transaction_status']==state):
                return False
            if survey.get('role')!='CONTROL' or survey.get(
                'source_rank')!=control.get('source_rank'):
                return False
            s=survey.get('survey')
            if not isinstance(s,dict) or s.get('status')!='SURVEY_COMPLETE' or (
                s.get('product_exact_url_match_count')!=1 or
                s.get('offer_availability')!='OUT_OF_STOCK' or
                s.get('primary_visible_for_sale_text')!=0 or
                s.get('primary_visible_sold_text')!=int(state=='SOLD') or
                s.get('primary_visible_reserved_text')!=int(state=='RESERVED')):
                return False
    return True


def _empty(code):
    return {
        'status':code,'projection_complete':False,
        'source_detail_visits':0,'control_detail_visits':0,
        'presentation_estimate_counts':{},
        'verified_for_sale_count':0,'inferred_possible_for_sale_count':0,
        'control_negative_classes_calibrated':False,
        'badge_omission_policy_proven':False,
        'stock_used_as_direct_transaction_proof':False,
        'canonical_transaction_status_changed':False,
        'strict_listing_approved_count':0,
        'source_items':[],'issues':['MISSING_OR_INCOMPLETE_PRIOR_EVIDENCE']}


def analyze(v423,v427,v428,v429):
    """Deterministically reinterpret prior redacted public capture; no site IO."""
    if not all(isinstance(x,dict) for x in (v423,v427,v428,v429)):
        return _empty('INCONCLUSIVE_MISSING_DOCUMENT')
    for doc in (v423,v427,v428,v429):
        if doc.get('consumer_schema_version')!='4.26':
            return _empty('INCONCLUSIVE_WRONG_CANONICAL_SCHEMA')
    e=v423.get('evaluation')
    b=v427.get('evaluation')
    c=v428.get('evaluation')
    d=v429.get('evaluation')
    if not all(isinstance(x,dict) for x in (e,b,c,d)):
        return _empty('INCONCLUSIVE_EVALUATION_MISSING')
    contexts=e.get('contexts')
    if not isinstance(contexts,list) or len(contexts)!=3 or (
        [x.get('context') for x in contexts if isinstance(x,dict)]
        !=list(CONTEXTS)):
        return _empty('INCONCLUSIVE_CONTEXT_SET')
    issues=[]
    if (e.get('bounded_capture_complete') is not True or
        b.get('status')!='CANONICAL_PIPELINE_LIVE_CROSSCHECK_OBSERVED' or
        b.get('pipeline_discrepancy_count')!=0 or
        c.get('diagnosis_complete') is not True or
        d.get('survey_complete') is not True or
        e.get('source_detail_visits')!=9 or
        e.get('actual_control_page_visits')!=6):
        issues.append('UPSTREAM_CAPTURE_OR_CROSSCHECK_NOT_COMPLETE')
    controls_ok=_controls_valid(e)
    if not controls_ok:
        issues.append('NEGATIVE_CONTROL_CALIBRATION_NOT_VERIFIED')
    projected=[]
    for row in contexts:
        original=row.get('source_state_models')
        diagnostics=row.get('v428_source_diagnostics')
        surveys=row.get('v429_source_signal_surveys')
        if not all(isinstance(v,list) and len(v)==3
                   for v in (original,diagnostics,surveys)):
            issues.append('SOURCE_TRIAD_CARDINALITY_MISMATCH')
            continue
        for record,diag,signal in zip(original,diagnostics,surveys):
            rank=record.get('source_rank') if isinstance(record,dict) else None
            if (type(rank) is not int or
                not isinstance(diag,dict) or not isinstance(signal,dict) or
                diag.get('source_rank')!=rank or
                signal.get('source_rank')!=rank):
                issues.append('SOURCE_RANK_OR_SCOPE_MISMATCH')
                continue
            model=record.get('model')
            view=consume(model,'SOURCE')
            result=classify_source(model,diag,signal,
                                   control_calibrated=controls_ok)
            if not view['schema_valid'] or result['canonical_transaction_status']!=(
                view['primary_transaction_status']):
                issues.append('INVALID_CANONICAL_OR_CHANGED_TRANSACTION')
            projected.append({
                'context':row['context'],
                'source_rank':rank,
                **result})
    if len(projected)!=9:
        issues.append('SOURCE_SAMPLE_COUNT_NOT_NINE')
    if any(x.get('primary_ui_for_sale_verified') for x in projected) and (
        c.get('verified_for_sale_records',0)==0):
        issues.append('UNEXPECTED_DIRECT_UI_VERIFICATION_NOT_CROSSCHECKED')
    if issues:
        status='INCONCLUSIVE_INFERENCE_GATE_FAILED'
    else:
        status='BADGE_OMISSION_HYPOTHESIS_APPLIED_WITHOUT_SALE_PROOF'
    if issues:
        # Fail closed; no heuristic labels from an incomplete study.
        projected=[{**x,**_result(reason='BATCH_INFERENCE_GATE_FAILED',
                                  canonical=x['canonical_transaction_status'])}
                   for x in projected]
    counts=Counter(x['presentation_estimate'] for x in projected)
    return {
        'status':status,'projection_complete':not issues,
        'source_detail_visits':e.get('source_detail_visits'),
        'control_detail_visits':e.get('actual_control_page_visits'),
        'presentation_estimate_counts':dict(sorted(counts.items())),
        'verified_for_sale_count':counts['FOR_SALE_DIRECTLY_VERIFIED'],
        'inferred_possible_for_sale_count':counts['POSSIBLY_FOR_SALE_BADGE_OMITTED'],
        'control_negative_classes_calibrated':controls_ok,
        'badge_omission_policy_proven':False,
        'stock_used_as_direct_transaction_proof':False,
        'canonical_transaction_status_changed':False,
        'strict_listing_approved_count':0,
        'source_items':projected,
        'issues':sorted(set(issues))}


def report(e):
    lines=['# v4.30 — omission-aware availability presentation overlay','',
        f"- Outcome: **{e['status']}**",
        f"- Verified FOR_SALE directly: {e['verified_for_sale_count']}",
        f"- Presentation-only 판매 가능 추정: {e['inferred_possible_for_sale_count']}",
        f"- Distribution: {e['presentation_estimate_counts']}",
        f"- SOLD and RESERVED negative controls calibrated: {e['control_negative_classes_calibrated']}",
        f"- Original transaction state changed: {e['canonical_transaction_status_changed']}",
        '- The marketplace default badge-omission policy is NOT proven.',
        '- InStock plus no status badge is a candidate signal, not a proof of availability.',
        '- A listing might be stale, pending, hidden, or subject to unobserved restrictions.',
        '- No user-facing purchase recommendation is automatically admitted.',
        f"- Strict listing approvals: {e['strict_listing_approved_count']}",
        f"- Analysis problems: {e['issues']}",'',
        '## Data contract','',
        '- primary_transaction_status is the existing canonical, direct UI status, never overwritten.',
        '- presentation_estimate is a separate, provisional UI/search label.',
        '- FOR_SALE_DIRECTLY_VERIFIED means direct, exact-item primary UI evidence; not a third-party stock/CTA/card surrogate.',
        '- POSSIBLY_FOR_SALE_BADGE_OMITTED means the omission hypothesis fits a bounded four-phase sample with independently SOLD and RESERVED controls.',
        '- Neither status bypasses price, category, seller or marketplace strict admission checks.','']
    return '\n'.join(lines)


def generate(evidence_dir,output_dir):
    """Consume existing redacted artifacts; never issue marketplace requests."""
    files=['v423_public_controls_results.json','v427_crosscheck_results.json',
           'v428_for_sale_results.json','v429_public_status_results.json']
    try:
        docs=[json.loads((evidence_dir/name).read_text(encoding='utf-8'))
              for name in files]
        result=analyze(*docs)
    except (OSError,ValueError,TypeError):
        result=_empty('INCONCLUSIVE_INPUT_FILES_UNAVAILABLE')
    output_dir.mkdir(parents=True,exist_ok=True)
    obj={'version':VERSION,
         'analyzed_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
         'source_version':'4.29',
         'presentation_only':True,
         'evaluation':result,
         'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    (output_dir/'v430_availability_estimates.json').write_text(
        json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output_dir/'v430_availability_report.md').write_text(
        report(result),encoding='utf-8')
    (output_dir/'v430_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if result['projection_complete'] else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--evidence-dir',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    opts=p.parse_args()
    return generate(opts.evidence_dir.resolve(),opts.output_dir.resolve())


if __name__=='__main__':
    raise SystemExit(main())
