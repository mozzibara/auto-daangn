# -*- coding: utf-8 -*-
"""v4.29 offline protocol for ethically owner-observed public listing transitions.

This script NEVER creates listings, changes trade states, logs in, interacts
with sellers, or fetches sites. Owner actions are truthful and manual.
Snapshots are privacy-bounded, owner attested, and matched by ephemeral
experiment-only HMAC, never by title, seller identity, or source rank.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

SCHEMA='4.29'
PHASES=('BEFORE','AFTER')
TRADE_STATES=('FOR_SALE','RESERVED','SOLD')
VISIBLE_STATES=('FOR_SALE','RESERVED','SOLD','NOT_OBSERVABLE','AMBIGUOUS')
STOCK_STATES=('IN_STOCK','OUT_OF_STOCK','SOLD_OUT','RESERVED','PRE_ORDER',
              'PRE_SALE','OTHER','NOT_OBSERVABLE','AMBIGUOUS')
PERMISSIONS=('NOT_VERIFIED','OWNER_ATTESTED_POLICY_REVIEW',
             'WRITTEN_PLATFORM_AUTHORIZATION')
# No claim that a human's self-report constitutes official site permission.
HASH_RE=re.compile(r'^[a-f0-9]{64}$')


def _date(raw):
    if not isinstance(raw,str) or len(raw)>40:return None
    try:
        x=datetime.fromisoformat(raw.replace('Z','+00:00'))
        return x.astimezone(timezone.utc) if x.tzinfo else None
    except (ValueError,OverflowError):
        return None


def _invalid(code):
    return {'status':code,'comparison_valid':False,'official_permission_verified':False,
        'direct_for_sale_proven':False,'default_omission_proven':False,
        'owner_observation_concordance':False,
        'strict_listing_approved_count':0}


def validate(entry,phase):
    if not isinstance(entry,dict) or entry.get('protocol_version')!=SCHEMA:
        return None
    if entry.get('phase')!=phase or entry.get('owner_consented') is not True or (
        entry.get('public_identity_confirmed') is not True or
        entry.get('robots_policy_allowed_for_capture') is not True):
        return None
    if entry.get('owner_manual_action_only') is not True or (
        entry.get('no_deceptive_state_change') is not True):
        return None
    key=entry.get('same_item_hmac_sha256')
    if not isinstance(key,str) or not HASH_RE.fullmatch(key):
        return None
    owner_state=entry.get('owner_declared_state')
    primary=entry.get('primary_visible_trade_status')
    availability=entry.get('exact_product_offer_availability')
    attr=entry.get('uncalibrated_primary_attribute_status')
    if owner_state not in TRADE_STATES or primary not in VISIBLE_STATES or (
        availability not in STOCK_STATES) or attr not in VISIBLE_STATES:
        return None
    timestamp=_date(entry.get('observed_at_utc'))
    if not timestamp:return None
    permission=entry.get('platform_permission_basis')
    if permission not in PERMISSIONS:return None
    if entry.get('strict_listing_approved') is not False:return None
    return {'key':key,'time':timestamp,'owner_state':owner_state,
        'primary_ui':primary,'stock':availability,'attribute':attr,
        'permission':permission}


def compare(before,after):
    """A one-item before/after is association evidence, never a causal proof.

    Even owner-verified FOR_SALE + InStock + no badge cannot become direct
    marketplace FOR_SALE proof. Official permission must be independently
    checked outside this self-reported artifact.
    """
    a=validate(before,'BEFORE')
    b=validate(after,'AFTER')
    if a is None or b is None:return _invalid('INCONCLUSIVE_INVALID_SNAPSHOT')
    if a['key']!=b['key']:return _invalid('INCONCLUSIVE_DIFFERENT_LISTING')
    if b['time']<=a['time']:return _invalid('INCONCLUSIVE_NONMONOTONIC_TIME')
    if a['owner_state']!='FOR_SALE' or b['owner_state'] not in ('RESERVED','SOLD'):
        return _invalid('INCONCLUSIVE_NO_RELEVANT_NATURAL_TRANSITION')
    if a['primary_ui'] in ('RESERVED','SOLD','AMBIGUOUS') or (
        b['primary_ui']=='AMBIGUOUS'):
        return _invalid('QUARANTINED_CONTRADICTORY_PUBLIC_STATUS')
    witnessed_after=b['primary_ui']==b['owner_state']
    explicit_before=a['primary_ui']=='FOR_SALE'
    stock_pattern=(a['stock']=='IN_STOCK' and b['stock'] in (
        'OUT_OF_STOCK','SOLD_OUT','RESERVED'))
    # An owner-reported platform permission is not a verified grant.
    permission_claim=(a['permission']=='WRITTEN_PLATFORM_AUTHORIZATION' and
                      b['permission']=='WRITTEN_PLATFORM_AUTHORIZATION')
    if not witnessed_after:
        status='INCONCLUSIVE_AFTER_TRANSITION_NOT_PUBLICLY_OBSERVED'
    elif explicit_before:
        status='DIRECT_PRIMARY_FOR_SALE_UI_IN_OWNER_PAIR'
    elif a['primary_ui']=='NOT_OBSERVABLE' and stock_pattern:
        status='OWNER_PAIR_COMPATIBLE_WITH_DEFAULT_BADGE_OMISSION'
    else:
        status='OWNER_PAIR_NONDECISIVE'
    # Even a compatible pair does not prove site's design intent or
    # validate undisclosed terms; only a scoped observation is reported.
    return {'status':status,'comparison_valid':True,
        'official_permission_verified':False,
        'written_permission_claimed_by_owner':permission_claim,
        'direct_for_sale_proven':False,
        'owner_reported_direct_primary_ui':explicit_before,
        'default_omission_proven':False,
        'default_omission_compatible':status==(
            'OWNER_PAIR_COMPATIBLE_WITH_DEFAULT_BADGE_OMISSION'),
        'owner_observation_concordance':witnessed_after,
        'before_primary_ui':a['primary_ui'],'after_primary_ui':b['primary_ui'],
        'before_owner_declared_state':a['owner_state'],
        'after_owner_declared_state':b['owner_state'],
        'before_stock_class':a['stock'],'after_stock_class':b['stock'],
        'candidate_attribute_changed':a['attribute']!=b['attribute'],
        'candidate_attribute_before':a['attribute'],
        'candidate_attribute_after':b['attribute'],
        'time_monotonic':True,'same_listing_hmac_matched':True,
        'marketplace_default_policy_proven':False,
        'strict_listing_approved_count':0}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--before',type=Path,required=True)
    p.add_argument('--after',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    opts=p.parse_args()
    try:
        before=json.loads(opts.before.read_text(encoding='utf-8'))
        after=json.loads(opts.after.read_text(encoding='utf-8'))
        result=compare(before,after)
    except (OSError,ValueError,TypeError):
        result=_invalid('INCONCLUSIVE_UNREADABLE_SNAPSHOT')
    # Store only redacted enums and test outcomes; no owner URL/digest.
    opts.output.parent.mkdir(parents=True,exist_ok=True)
    opts.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',
                           encoding='utf-8')
    print('v4.29 owner-pair comparison:',result['status'])
    return 0 if result['comparison_valid'] else 2


if __name__=='__main__':
    raise SystemExit(main())
