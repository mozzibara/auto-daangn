# -*- coding: utf-8 -*-
"""v4.28 owner-approved, single-capture analysis of absent positive UI evidence.

Reuses v4.27 capture: 9 source public details and up to 6 real linked controls.
Only explicit visible semantic primary status is a possible FOR_SALE proof.
CTA and Product JSON-LD remain non-transactional witnesses.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path

import daangn_pipeline_crosscheck_v4_27 as pipeline
from daangn_listing_state_v4_24 import build_record,clean_record
from daangn_state_consumers_v4_25 import consume

CONTEXTS=pipeline.CONTEXTS
SUCCESS='DIRECT_FOR_SALE_UI_PROVEN_IN_SAMPLED_ITEMS'
NO_PROOF='DIAGNOSTIC_COMPLETE_NO_DIRECT_FOR_SALE_UI_PROOF'
MAX_SOURCES=9
MAX_CONTROLS=6
PHASES=('initial','delayed','scrolled','narrow')


def _empty(status,issues):
    return {'status':status,'diagnosis_complete':False,
        'verified_for_sale_records':0,'v427_status':'INCONCLUSIVE',
        'source_visits':0,'control_visits':0,'sampled_source_diagnostics':0,
        'sampled_control_diagnostics':0,
        'reason_counts':{},'stage_discrepancies':dict(Counter(issues)),
        'positive_ui_evidence_not_jsonld':True,
        'cta_is_not_selling_proof':True,
        'strict_listing_approved_count':0,
        'source_cases':[],'control_cases':[]}


def classify_absence(d):
    if not isinstance(d,dict):return 'INCONCLUSIVE_DIAGNOSIS_MISSING'
    probe=d.get('probe') if isinstance(d.get('probe'),dict) else {}
    if d.get('dom_capture_status')!='CAPTURED':
        return 'INCONCLUSIVE_FOUR_PHASE_DOM'
    frames=d.get('phases') if isinstance(d.get('phases'),dict) else {}
    phase_states=([frames.get(k,{}).get('ui') for k in PHASES]
                  if len(frames)==4 else [])
    observed_positive=any(x=='AVAILABLE' for x in phase_states)
    observed_negative=any(x in ('SOLD','RESERVED','AMBIGUOUS')
        for x in phase_states)
    if (observed_positive and observed_negative) or (
        observed_negative and probe.get('status')=='DIRECT_FOR_SALE_UI'):
        return 'AMBIGUOUS_PRIMARY_STATUS'
    if probe.get('status')=='DIRECT_FOR_SALE_UI':
        return 'EXPLICIT_PRIMARY_AVAILABLE_STATUS_PRESENT'
    if probe.get('status')=='AMBIGUOUS_DIRECT_UI':
        return 'AMBIGUOUS_PRIMARY_STATUS'
    if observed_positive and all(frames.get(k,{}).get('same_document_url') is True
            and frames.get(k,{}).get('scan_complete') is True
            and frames.get(k,{}).get('primary_heading_visible') is True
            for k in PHASES):
        return 'EXPLICIT_PRIMARY_AVAILABLE_STATUS_PRESENT_IN_PHASE'
    if probe.get('status') not in (
        'NO_DIRECT_FOR_SALE_UI','DIRECT_OTHER_TRANSACTION_UI'):
        return 'INCONCLUSIVE_INDEPENDENT_PROBE'
    if (probe.get('primary_hidden_positive_status') or 0)>0:
        return 'EXPLICIT_AVAILABLE_STATUS_HIDDEN'
    if (probe.get('primary_visible_unmarked_available_text') or 0)>0:
        return 'UNMARKED_AVAILABLE_TEXT_NOT_PROOF'
    if d.get('dom_outcome') in (
        'PRIMARY_VISIBLE_STATUS_OLD_SELECTOR_GAP',
        'PRIMARY_VISIBLE_STATUS_UNRESOLVED_BY_V421',
        'STATUS_EMERGED_AFTER_SETTLE',
        'STATUS_EMERGED_AFTER_SCROLL',
        'STATUS_EMERGED_NARROW_VIEWPORT'):
        return 'DOM_RENDER_OR_SELECTOR_GAP_CANDIDATE'
    frames=d.get('phases') if isinstance(d.get('phases'),dict) else {}
    if len(frames)!=4 or any(not isinstance(frames.get(k),dict) or
            frames[k].get('scan_complete') is not True or
            frames[k].get('same_document_url') is not True for k in PHASES):
        return 'INCONCLUSIVE_FOUR_PHASE_DOM'
    if all((frames[k].get('primary_exact_tokens') or 0)==0 for k in PHASES):
        related=sum(frames[k].get('linked_listing_exact_tokens') or 0
                    for k in PHASES)
        if related>0:return 'ONLY_OTHER_LISTING_STATUS_TOKENS'
        if (probe.get('primary_chat_cta') or 0)>0 or (
            probe.get('primary_purchase_cta') or 0)>0:
            return 'PRIMARY_CTA_PRESENT_WITHOUT_STATUS_PROOF'
        return 'NO_PRIMARY_EXPLICIT_STATUS_IN_FOUR_PHASES'
    return 'PRIMARY_EXPLICIT_NONAVAILABLE_OR_UNRESOLVED_TOKENS'


def analyze(v423,v427):
    if not (isinstance(v423,dict) and isinstance(v427,dict)):
        return _empty('INCONCLUSIVE_CAPTURE_MISSING',['INVALID_INPUT'])
    a=v423.get('evaluation')
    b=v427.get('evaluation')
    if not isinstance(a,dict) or not isinstance(b,dict):
        return _empty('INCONCLUSIVE_CAPTURE_MISSING',['NO_EVALUATION'])
    if v423.get('consumer_schema_version')!='4.26' or v427.get(
        'consumer_schema_version')!='4.26':
        return _empty('INCONCLUSIVE_LEGACY_SCHEMA',['NOT_V426'])
    contexts=a.get('contexts')
    if not isinstance(contexts,list) or [x.get('context') for x in contexts
            if isinstance(x,dict)]!=list(CONTEXTS):
        return _empty('INCONCLUSIVE_CONTEXT_SET',['CONTEXT_MISMATCH'])
    reasons=Counter()
    discrepancies=Counter()
    sources=[]
    controls=[]
    source_visits=0
    control_visits=0
    for row in contexts:
        ctx=row['context']
        src=row.get('v428_source_diagnostics')
        ctrl=row.get('v428_control_diagnostics')
        canonical=row.get('source_state_models')
        original_controls=row.get('controls')
        if any(not isinstance(x,list) for x in (
            src,ctrl,canonical,original_controls)):
            discrepancies['MISSING_DIAGNOSTIC_COLUMNS']+=1
            continue
        source_visits+=row.get('source_detail_count') if type(row.get(
            'source_detail_count')) is int else 0
        control_visits+=row.get('visited_control_count') if type(row.get(
            'visited_control_count')) is int else 0
        if len(src)!=3 or len(canonical)!=3 or len(ctrl)!=len(original_controls):
            discrepancies['DIAGNOSTIC_CARDINALITY_MISMATCH']+=1
        for source,record in zip(src[:3],canonical[:3]):
            if not isinstance(source,dict) or not isinstance(record,dict):
                discrepancies['INVALID_SOURCE_ROW']+=1;continue
            safe=clean_record(record.get('model'))
            view=consume(safe,'SOURCE')
            if not view['schema_valid'] or source.get('source_rank')!=record.get('source_rank'):
                discrepancies['INVALID_SOURCE_CANONICAL_ALIGNMENT']+=1
            reason=classify_absence(source)
            reasons[reason]+=1
            probe=source.get('probe') if isinstance(source.get('probe'),dict) else {}
            positive=(reason in ('EXPLICIT_PRIMARY_AVAILABLE_STATUS_PRESENT',
                'EXPLICIT_PRIMARY_AVAILABLE_STATUS_PRESENT_IN_PHASE') and
                view['schema_valid'] and view['primary_transaction_status']
                    in ('NOT_OBSERVABLE','FOR_SALE') and
                source.get('dom_capture_status')=='CAPTURED' and
                all(source.get('phases',{}).get(phase,{}).get('same_document_url') is True
                    for phase in PHASES))
            # Independent direct primary UI evidence is eligible to form a
            # research-only canonical candidate. Never changes any listing gate.
            candidate=None
            if positive:
                avail=safe['product_jsonld_exact_availability']
                candidate=clean_record(build_record(
                    ['AVAILABLE'],avail,context='SOURCE',
                    identity_confirmed=True,render_complete=True,
                    same_product=(avail!='NOT_OBSERVABLE'),
                    ui_origin='PRIMARY_STATUS_MARKER'))
                if not candidate or consume(candidate,'SOURCE')['primary_transaction_status']!='FOR_SALE':
                    discrepancies['POSITIVE_WITNESS_NORMALIZATION_FAILED']+=1
                    candidate=None
            if reason=='AMBIGUOUS_PRIMARY_STATUS':
                discrepancies['AMBIGUOUS_PRIMARY_STATE']+=1
            if any(source.get('phases',{}).get(k,{}).get('same_document_url') is False
                   for k in PHASES):
                discrepancies['SOURCE_PHASE_IDENTITY_CHANGED']+=1
            if reason.startswith('EXPLICIT_PRIMARY_AVAILABLE') and view[
                    'primary_transaction_status'] in ('SOLD','RESERVED'):
                discrepancies['SOURCE_PRIMARY_UI_STATE_CONFLICT']+=1
            if reason.startswith('INCONCLUSIVE_'):
                discrepancies['SOURCE_DIAGNOSIS_INCOMPLETE']+=1
            sources.append({'context':ctx,'source_rank':source.get('source_rank'),
                'reason':reason,'direct_primary_ui_proven':candidate is not None,
                'v426_original_transaction_status':view['primary_transaction_status'],
                'research_only_direct_ui_status':candidate['primary_transaction_status']
                    if candidate else 'NOT_VERIFIED',
                'cta_visible':any((probe.get(k) or 0)>0 for k in (
                    'primary_chat_cta','primary_purchase_cta','primary_price_offer_cta')),
                'hidden_positive_token_candidates':probe.get(
                    'primary_hidden_positive_status',0),
                'related_positive_token_candidates':probe.get(
                    'related_positive_status',0),
                'dom_outcome':source.get('dom_outcome'),
                'strict_listing_approved':False})
        for control,original in zip(ctrl[:2],original_controls[:2]):
            if not isinstance(control,dict) or not isinstance(original,dict):
                discrepancies['INVALID_CONTROL_ROW']+=1;continue
            p=control.get('probe') if isinstance(control.get('probe'),dict) else {}
            record=clean_record(original.get('v424_state_model'))
            view=consume(record,'CONTROL')
            if (not view['schema_valid'] or
                control.get('source_rank')!=original.get('source_rank') or
                original.get('status')!='AUDITED'):
                discrepancies['CONTROL_IDENTITY_OR_CANONICAL_MISMATCH']+=1
            if control.get('dom_capture_status')!='CAPTURED' or p.get(
                'status') in ('SCAN_INCOMPLETE','PRIMARY_NOT_VERIFIED'):
                discrepancies['CONTROL_DIAGNOSIS_INCOMPLETE']+=1
            control_frames=control.get('phases',{})
            phase_positive=any(isinstance(control_frames.get(k),dict) and
                control_frames[k].get('ui')=='AVAILABLE' for k in PHASES)
            if p.get('status')=='DIRECT_FOR_SALE_UI' or phase_positive:
                discrepancies['FALSE_POSITIVE_FOR_SALE_IN_SOLD_RESERVED_CONTROL']+=1
            controls.append({'context':ctx,'source_rank':control.get('source_rank'),
                'control_transaction_status':view['primary_transaction_status'],
                'explicit_positive_witness':p.get('explicit_positive_proof') is True,
                'chat_cta_present':(p.get('primary_chat_cta') or 0)>0,
                'purchase_cta_present':(p.get('primary_purchase_cta') or 0)>0,
                'price_offer_cta_present':(p.get('primary_price_offer_cta') or 0)>0,
                'strict_listing_approved':False})
    counts=Counter(x['control_transaction_status'] for x in controls)
    positive=sum(x['direct_primary_ui_proven'] for x in sources)
    complete=(source_visits==MAX_SOURCES and len(sources)==MAX_SOURCES and
        0<control_visits<=MAX_CONTROLS and len(controls)==control_visits and
        b.get('status')==pipeline.ACCEPT and a.get('bounded_capture_complete') is True)
    if discrepancies:status='QUARANTINED_OR_INCOMPLETE_DIAGNOSTICS'
    elif not complete:status='INCONCLUSIVE_LIVE_CAPTURE_INCOMPLETE'
    elif positive:status=SUCCESS
    else:status=NO_PROOF
    return {'status':status,'diagnosis_complete':complete and not discrepancies,
        'verified_for_sale_records':positive if not discrepancies else 0,
        'v427_status':b.get('status') if b.get('status')==pipeline.ACCEPT
            else 'INCONCLUSIVE',
        'source_visits':source_visits,'control_visits':control_visits,
        'sampled_source_diagnostics':len(sources),
        'sampled_control_diagnostics':len(controls),
        'source_for_sale_exact_ui_proofs':positive,
        'control_class_counts':dict(sorted(counts.items())),
        'control_cta_counts':{
            k:sum(x.get(k) is True for x in controls)
            for k in ('chat_cta_present','purchase_cta_present',
                      'price_offer_cta_present')},
        'source_cta_presence_count':sum(x['cta_visible'] for x in sources),
        'reason_counts':dict(sorted(reasons.items())),
        'stage_discrepancies':dict(sorted(discrepancies.items())),
        'positive_ui_evidence_not_jsonld':True,
        'cta_is_not_selling_proof':True,'strict_listing_approved_count':0,
        'source_cases':sources,'control_cases':controls}


def report(e):
    lines=['# v4.28 — primary FOR_SALE UI absence forensic study','',
        f"- Diagnosis verdict: **{e['status']}**",
        f"- Source public detail visits: {e['source_visits']} / 9",
        f"- SOLD/RESERVED controls: {e['control_visits']} / 6 (max)",
        f"- Complete and independently verified: {e['diagnosis_complete']}",
        f"- Direct primary UI FOR_SALE proof count: **{e['verified_for_sale_records']}**",
        f"- Absence/selector/render reason counts: {e['reason_counts']}",
        f"- Control CTA counts (NON-proof): {e.get('control_cta_counts',{})}",
        f"- Source CTA presence count (NON-proof): {e.get('source_cta_presence_count',0)}",
        f"- Fail-closed diagnostic discrepancies: {e['stage_discrepancies']}",
        '', '## Boundaries','',
        '- Four passive, same-document DOM phases: initial, delayed, scroll, narrow.',
        '- Exact visible current-item semantic status only may prove FOR_SALE.',
        '- InStock, search filtering, CTA, other-item badge, and omitted SOLD badge are NEVER FOR_SALE proof.',
        '- Missing positive UI is a bounded absence observation, not proof of a site-wide default policy.',
        '- No interaction, no contact with sellers, no login or listing approval.',
        '- All research-only positives are independently re-normalized and not admitted to the strict listing gate.','']
    return '\n'.join(lines)


async def run(options):
    options.for_sale_diagnosis_v428=True
    options.headed=getattr(options,'headed',False) is True
    old_code=await pipeline.run(options)
    try:
        a=json.loads((options.output_dir/'v423_public_controls_results.json')
                     .read_text(encoding='utf-8'))
        b=json.loads((options.output_dir/'v427_crosscheck_results.json')
                     .read_text(encoding='utf-8'))
        result=analyze(a,b)
    except (OSError,ValueError,TypeError):
        result=_empty('INCONCLUSIVE_CAPTURE_FILES_UNAVAILABLE',['MISSING_ARTIFACTS'])
    if old_code!=0 and result['status'] in (SUCCESS,NO_PROOF):
        result['status']='INCONCLUSIVE_UPSTREAM_PIPELINE_FAILED'
    artifact={'version':'4.28','consumer_schema_version':'4.26',
              'canonical_state_schema_version':'4.24',
              'utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'experiment':{'source_detail_max':9,'control_detail_max':6,
                'one_capture':True,'strict_listing_gate_changed':False},
              'evaluation':result,
              'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    options.output_dir.mkdir(parents=True,exist_ok=True)
    (options.output_dir/'v428_for_sale_results.json').write_text(
        json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (options.output_dir/'v428_for_sale_report.md').write_text(
        report(result),encoding='utf-8')
    (options.output_dir/'v428_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if old_code==0 and result['status'] in (SUCCESS,NO_PROOF) else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v428_live_output'))
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--headed',action='store_true')
    opt=p.parse_args()
    opt.output_dir=opt.output_dir.resolve()
    opt.timeout=max(15,min(45,opt.timeout))
    opt.settle_ms=max(800,min(3500,opt.settle_ms))
    return asyncio.run(run(opt))


if __name__=='__main__':
    raise SystemExit(main())
