#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4.4.1 post-gate consistency layer. No browser or network dependency.

The v4.4 decision engine is retained for historical compatibility. This layer
separates *run-level block* from *sample-level rejection* and closes dependency
holes when historical signatures invalidate an independently-matched peer.
"""
from __future__ import annotations

from collections import Counter
import daangn_v4_4_gate as old

ACCEPT = 'LIMITED_ACCEPT_REGIONAL_LISTING_SET'


def apply_consistent_gate(run: dict, *, historical_signatures=(),
                          capture_status='CAPTURED_COMPLETE', mode='live') -> dict:
    base = old.apply_gate(run)
    decisions = base['decisions']
    ids = [s.get('sample_id') for s in run.get('samples', [])]
    malformed = (len(ids) != len(set(ids)) or not all(isinstance(i,str) and i for i in ids)
                 or len(decisions) != len(ids))
    has_invalid = any(not s.get('valid',False) for s in run.get('samples', []))
    blocked = (mode != 'live' or capture_status != 'CAPTURED_COMPLETE'
               or malformed or has_invalid or not decisions)
    reasons = []
    if mode != 'live': reasons.append('NON_LIVE_MODE')
    if capture_status != 'CAPTURED_COMPLETE': reasons.append('CAPTURE_INCOMPLETE')
    if malformed: reasons.append('INVALID_SAMPLE_IDENTIFIERS')
    if has_invalid: reasons.append('INVALID_STAGE_EVIDENCE')
    if not decisions: reasons.append('NO_SAMPLES')

    historical = set(historical_signatures)
    for d in decisions:
        if d.get('set_sha256') in historical and d.get('count',0) >= 20:
            # Preserve more-specific confirmed anomaly, never turn a quarantine into acceptance.
            if not d['verdict'].startswith('QUARANTINED'):
                d['verdict'] = 'QUARANTINED_HISTORICAL_CROSS_REGION_SIGNATURE'
            d['allowed_for_price_analysis'] = False
            d['why'].append('Matched historical cross-region identical cold set signature')

    if blocked:
        for d in decisions:
            if d['verdict'] == ACCEPT:
                d['verdict'] = 'UNVERIFIED_RUN_LEVEL_BLOCKED'
                d['allowed_for_price_analysis'] = False
                d['why'].append('Whole-run integrity failed; no sample export is permitted')

    # A historical or cross-region quarantine may invalidate the purported independent
    # repeat of a different sample. Iterate to fixed point to prevent dangling approval.
    by_id = {d['sample_id']:d for d in decisions}
    changed = True
    while changed:
        changed = False
        for d in decisions:
            if d['verdict'] != ACCEPT: continue
            peer_id = (d.get('independent_repeat') or {}).get('peer_sample_id')
            peer = by_id.get(peer_id)
            if peer is None or peer['verdict'] != ACCEPT or peer['region'] != d['region'] or peer['context'] == d['context']:
                d['verdict'] = 'UNVERIFIED_APPROVAL_DEPENDENCY_INVALIDATED'
                d['allowed_for_price_analysis'] = False
                d['why'].append('Independent same-region peer is no longer approved')
                changed = True
                continue
            # Cross-region comparison must include a distinct, not-quarantined accepted set.
            peers_other = [p for p in decisions if p['verdict'] == ACCEPT and p['region'] != d['region']]
            if not peers_other:
                d['verdict'] = 'UNVERIFIED_APPROVAL_DEPENDENCY_INVALIDATED'
                d['allowed_for_price_analysis'] = False
                d['why'].append('No remaining approved distinct-region control')
                changed = True

    for d in decisions:
        d['allowed_for_price_analysis'] = bool(not blocked and d['verdict'] == ACCEPT)
        d['sample_level_allowed'] = d['allowed_for_price_analysis']
        d['sample_level_blocked'] = not d['sample_level_allowed']
    base['version'] = '4.4.1'
    base['counts'] = dict(sorted(Counter(d['verdict'] for d in decisions).items()))
    base['run_level'] = {
        'blocked': blocked,
        'reasons': reasons,
        'capture_status': capture_status,
        'mode': mode,
        'allowed_sample_count': sum(d['sample_level_allowed'] for d in decisions),
        'quarantined_sample_count': sum(d['verdict'].startswith('QUARANTINED') for d in decisions),
        'unverified_sample_count': sum(d['verdict'].startswith('UNVERIFIED') for d in decisions),
        'sample_level_policy': 'PER_SAMPLE_ALLOW_OR_BLOCK',
        'export_policy': 'NO_EXPORT' if blocked else 'LIMITED_ACCEPTED_SAMPLES_ONLY',
    }
    base['historical_signatures_checked'] = len(historical)
    assert base['run_level']['allowed_sample_count'] + base['run_level']['quarantined_sample_count'] + base['run_level']['unverified_sample_count'] == len(decisions)
    return base


def validate_exports(results: dict, quarantine: dict, accepted: dict) -> None:
    """Fail fast on contradictory output schemas before writing any files."""
    d=results['gate']['decisions']
    run=results['gate']['run_level']
    all_ids={x['sample_id'] for x in d}
    qids={x['sample_id'] for x in quarantine['quarantined']}
    uids={x['sample_id'] for x in quarantine['unverified']}
    aids={x['sample_id'] for x in accepted['samples']}
    if len(all_ids)!=len(d) or len(qids)+len(uids)+len(aids)!=len(d):
        raise ValueError('Non-unique or incomplete partition')
    if (qids & uids) or (qids & aids) or (uids & aids) or qids|uids|aids != all_ids:
        raise ValueError('Sample partitions overlap or omit samples')
    if accepted['run_level_blocked'] != run['blocked'] or quarantine['run_level_blocked'] != run['blocked']:
        raise ValueError('Run-level flags differ')
    if run['blocked'] and aids:
        raise ValueError('Blocked run has allowed samples')
    if accepted['allowed_sample_count'] != len(aids) or run['allowed_sample_count'] != len(aids):
        raise ValueError('Allowed sample counts differ')
    for x in d:
        allowed=x['sample_id'] in aids
        if allowed != x['sample_level_allowed'] or allowed != x['allowed_for_price_analysis']:
            raise ValueError('Sample permission contradicts decision')
    for item in accepted['samples']:
        if not item['sample_level_allowed'] or item['verdict']!=ACCEPT:
            raise ValueError('Accepted export has unapproved verdict')
