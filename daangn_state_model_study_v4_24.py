# -*- coding: utf-8 -*-
"""v4.24 bounded study of two orthogonal fields on actual public item details.

Reuse the v4.23.1 real UI → Route → exact robots-gated source/control details,
and project its in-memory per-item v4.24 canonical evidence without altering
the historical source, strict filter, or listing approval semantics.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path

import daangn_listing_state_v4_24 as state
import daangn_state_controls_v4_23 as previous

VALID_CONTEXTS=('cheonan_a','asan_control','cheonan_b')
MAX_SOURCE_ITEMS=9
MAX_CONTROL_ITEMS=6


def project(legacy):
    """Never accept arbitrary raw fields: keep only canonical model columns."""
    if not isinstance(legacy,dict):return {'status':'INVALID_LEGACY_EVIDENCE'}
    evaluation=legacy.get('evaluation') if isinstance(legacy.get('evaluation'),dict) else {}
    contexts=evaluation.get('contexts') if isinstance(evaluation.get('contexts'),list) else []
    results=[]
    records=[]
    observed_source=0
    observed_control=0
    for item in contexts[:3]:
        if not isinstance(item,dict) or item.get('context') not in VALID_CONTEXTS:continue
        label=item['context']
        projected={'context':label,'original_source_visits':item.get('source_detail_count'),
                   'original_control_visits':item.get('visited_control_count'),
                   'items':[]}
        for v in (item.get('source_state_models') or [])[:3]:
            if not isinstance(v,dict):continue
            record=v.get('model')
            if not isinstance(record,dict) or record.get('context_kind')!='SOURCE':continue
            if not isinstance(v.get('source_rank'),int) or v['source_rank']<0 or v['source_rank']>650:continue
            safe=state.clean_record(record)
            if safe is None:continue
            projected['items'].append({'role':'SOURCE','source_rank':v['source_rank'],
                                        'fields':safe})
            records.append(safe)
            observed_source+=1
        for v in (item.get('controls') or [])[:2]:
            if not isinstance(v,dict) or v.get('status')!='AUDITED':continue
            record=v.get('v424_state_model')
            if not isinstance(record,dict) or record.get('context_kind')!='CONTROL':continue
            if not isinstance(v.get('source_rank'),int) or v['source_rank']<0 or v['source_rank']>650:continue
            safe=state.clean_record(record)
            if safe is None:continue
            projected['items'].append({'role':'CONTROL','source_rank':v['source_rank'],
                                        'fields':safe})
            records.append(safe)
            observed_control+=1
        results.append(projected)
    summary=state.summarize_records(records)
    exact_contradictions=summary['independent_evidence_tier_counts'].get('QUARANTINED',0)
    sources_complete=(len(results)==3 and
        all(len([r for r in c['items'] if r['role']=='SOURCE'])==3 for c in results))
    controls_expected=evaluation.get('actual_control_page_visits')
    controls_complete=(type(controls_expected) is int and
                       controls_expected==observed_control)
    source_ui=summary['transaction_status_counts'].get('NOT_OBSERVABLE',0)
    if not evaluation.get('bounded_capture_complete'):
        status='INCONCLUSIVE_LEGACY_CAPTURE_INCOMPLETE'
    elif not sources_complete or not controls_complete:
        status='INCONCLUSIVE_STATE_MODEL_RECORDS_INCOMPLETE'
    elif exact_contradictions:
        status='QUARANTINED_SEMANTIC_CONFLICT'
    elif observed_control==0:
        status='INCONCLUSIVE_NO_CONTROL_DETAILS'
    else:
        status='ORTHOGONAL_STATE_MODEL_OBSERVED'
    return {
        'status':status,
        'capture_complete':status in (
            'ORTHOGONAL_STATE_MODEL_OBSERVED','QUARANTINED_SEMANTIC_CONFLICT'),
        'source_record_count':observed_source,
        'control_record_count':observed_control,
        'source_ui_unobserved_anywhere_count':source_ui,
        'canonical_model_summary':summary,
        'original_v423_status':evaluation.get('status','INCONCLUSIVE'),
        'all_route_listings_verified':False,
        'transaction_state_inferred_from_jsonld':False,
        'availability_inferred_from_transaction_ui':False,
        'source_card_inferred_as_primary_status':False,
        'historical_strict_listing_approved_count':0,
        'context_models':results
    }


def report(e):
    lines=['# v4.24 common transaction/availability evidence model','',
         f"- Independent model verdict: **{e['status']}**",
         f"- Complete bounded sample: {e['capture_complete']}",
         f"- Original source detail records: {e['source_record_count']}",
         f"- Target control detail records: {e['control_record_count']}",
         '- No individual listing approval, and no whole-Route extrapolation.',
         '', '## Strictly separate normalized fields','',
         '| Field | Definition |',
         '|---|---|',
         '| primary_transaction_status | Current listing primary UI only: FOR_SALE, RESERVED, SOLD, NOT_OBSERVABLE |',
         '| product_jsonld_exact_availability | Exact URL-matched Product offers availability: IN_STOCK, OUT_OF_STOCK, SOLD_OUT, PRE_ORDER, PRE_SALE |',
         '| product_jsonld_stock_class | Stock-oriented compatibility only; never a transaction-status classifier |',
         '| linked_card_status | Other listing card evidence, not primary UI proof |',
         '| independent_evidence_tier | Compatibility, semantic gap, quarantine or incompleteness |',
         '', '## Observed bounded distributions','',
         f"- Primary UI transaction statuses: {e['canonical_model_summary']['transaction_status_counts']}",
         f"- Exact JSON-LD availability types: {e['canonical_model_summary']['exact_availability_counts']}",
         f"- Stock vs transaction semantic relationships: {e['canonical_model_summary']['semantic_comparison_counts']}",
         f"- Independent evidence tiers: {e['canonical_model_summary']['independent_evidence_tier_counts']}",
         '', '## Limitations','',
         '- OutOfStock and SoldOut are distinct exact schema.org values. Neither directly establishes a completed marketplace transaction.',
         '- A visible RESERVED item plus OutOfStock is generic unavailability; its reservation state comes from primary UI, not Product JSON-LD.',
         '- v4.26 removed the former v4.20/v4.21 coarse JSON-LD-to-marketplace-state converters entirely. The normalized decision uses only the independent canonical record.',
         '- Item links, IDs, seller names, JSON-LD payloads, and raw HTML are not saved; the model stores only allowlisted enums and source ranks.',
         '- All strict price/category/availability listing gates remain unchanged and approved listings remain zero.','']
    return '\n'.join(lines)


async def run(opts):
    opts.state_model_v424=True
    code=await previous.run(opts)
    old=opts.output_dir/'v423_public_controls_results.json'
    if not old.exists():
        result={'status':'STOP_MISSING_V423_RESULTS','capture_complete':False,
                'source_record_count':0,'control_record_count':0,
                'historical_strict_listing_approved_count':0}
    else:
        try:result=project(json.loads(old.read_text(encoding='utf-8')))
        except (OSError,ValueError,TypeError,KeyError):
            result={'status':'STOP_UNPARSEABLE_LEGACY_RESULTS','capture_complete':False,
                    'source_record_count':0,'control_record_count':0,
                    'historical_strict_listing_approved_count':0}
    obj={'version':'4.24','consumer_schema_version':'4.26',
         'utc_timestamp':datetime.now(timezone.utc).isoformat(timespec='seconds'),
         'design':{'source_public_detail_max':MAX_SOURCE_ITEMS,
                   'control_public_detail_max':MAX_CONTROL_ITEMS,
                   'exact_detail_robots_required':True,
                   'isolated_transaction_and_availability_fields':True,
                   'strict_listing_gate_changed':False},
         'evaluation':result,
         'strict_listing_acceptance':{'blocked':True,'approved_listings':[]}}
    opts.output_dir.mkdir(parents=True,exist_ok=True)
    (opts.output_dir/'v424_state_model_results.json').write_text(
        json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (opts.output_dir/'v424_state_model_report.md').write_text(
        report(result) if 'canonical_model_summary' in result else
        '# v4.24 evidence incomplete\n\n'+str(result['status'])+'\n',encoding='utf-8')
    (opts.output_dir/'v424_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if code==0 and result['status']=='ORTHOGONAL_STATE_MODEL_OBSERVED' else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v424_output'))
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
