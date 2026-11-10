# -*- coding: utf-8 -*-
"""v4.25 authoritative, offline consumers of the v4.24 orthogonal state model.

Historical v4.20/v4.21/v4.23 coarse outputs are archival and MUST NOT be
reinterpreted as marketplace transaction facts. Fail closed if a canonical
record is absent, malformed, has the wrong context or lacks primary UI proof.
"""
from __future__ import annotations

from collections import Counter

from daangn_listing_state_v4_24 import clean_record
from daangn_sale_filter_v4_31 import assess_source


def consume(record, expected_context):
    """Project only validated finite enums. Never accept a legacy SOLD value."""
    empty = {
        'status': 'MISSING_CANONICAL_RECORD' if record is None else 'INVALID_CANONICAL_RECORD',
        'schema_valid': False,
        'primary_transaction_status': 'NOT_VERIFIED',
        'product_jsonld_exact_availability': 'NOT_OBSERVABLE',
        'product_jsonld_stock_class': 'UNKNOWN',
        'independent_evidence_tier': 'INCONCLUSIVE',
        'card_primary_comparison': 'NOT_APPLICABLE',
        'primary_ui_proven': False,
        'sale_filter_eligible': False,
        'sale_filter_inferred': False,
        'sale_filter_status': 'SALE_FILTER_UNVERIFIED',
        'direct_for_sale_badge_required': False,
        'card_ui_corroborated': False,
        'strict_listing_approved': False,
        'legacy_coarse_status_used': False,
    }
    if expected_context not in ('SOURCE', 'CONTROL'):
        return dict(empty, status='INVALID_EXPECTED_CONTEXT')
    safe = clean_record(record)
    if safe is None or safe['context_kind'] != expected_context:
        return empty
    txn = safe['primary_transaction_status']
    tier = safe['independent_evidence_tier']
    card = safe['card_primary_comparison']
    ui_proven = txn in ('FOR_SALE', 'RESERVED', 'SOLD') and tier != 'QUARANTINED'
    # v4.31: primary FOR_SALE badge is optional for a pragmatic shopping
    # candidate, but the canonical transaction status is NOT rewritten.
    policy = assess_source(safe) if expected_context=='SOURCE' else None
    if tier == 'QUARANTINED':
        status = 'CANONICAL_QUARANTINED'
    elif txn in ('NOT_VERIFIED', 'AMBIGUOUS'):
        status = 'CANONICAL_INCONCLUSIVE'
    elif txn == 'NOT_OBSERVABLE':
        status = 'CANONICAL_NO_PRIMARY_UI_PROOF'
    else:
        status = 'CANONICAL_PRIMARY_UI_' + txn
    return {
        'status': status,
        'schema_valid': True,
        'primary_transaction_status': txn,
        'product_jsonld_exact_availability': safe['product_jsonld_exact_availability'],
        'product_jsonld_stock_class': safe['product_jsonld_stock_class'],
        'independent_evidence_tier': tier,
        'card_primary_comparison': card,
        'primary_ui_proven': ui_proven,
        'sale_filter_eligible': policy['sale_filter_eligible'] if policy else False,
        'sale_filter_inferred': policy['is_inferred_available'] if policy else False,
        'sale_filter_status': policy['sale_filter_status'] if policy
                            else 'SALE_FILTER_UNVERIFIED',
        'direct_for_sale_badge_required': False,
        'card_ui_corroborated': ui_proven and expected_context == 'CONTROL'
                                and card == 'CARD_AND_PRIMARY_UI_MATCH',
        'strict_listing_approved': False,
        'legacy_coarse_status_used': False,
    }


def source_comparison(record):
    """A descriptive canonical comparison, not a transaction conversion."""
    view = consume(record, 'SOURCE')
    if not view['schema_valid']:
        return view['status']
    if view['status'] == 'CANONICAL_QUARANTINED':
        return 'CANONICAL_SEMANTIC_CONFLICT_QUARANTINED'
    if view['status'] == 'CANONICAL_NO_PRIMARY_UI_PROOF':
        return 'CANONICAL_METADATA_NOT_PRIMARY_UI_PROOF'
    if not view['primary_ui_proven']:
        return 'CANONICAL_UI_NOT_VERIFIED'
    tier = view['independent_evidence_tier']
    return {
        'UI_AND_METADATA_COMPATIBLE': 'CANONICAL_UI_AND_STOCK_COMPATIBLE',
        'UI_OBSERVED_STOCK_UNSPECIFIC': 'CANONICAL_UI_WITH_NONSPECIFIC_STOCK',
        'UI_ONLY_NO_STOCK_PROOF': 'CANONICAL_PRIMARY_UI_ONLY',
    }.get(tier, 'CANONICAL_UI_STOCK_INCONCLUSIVE')


def control_comparison(record):
    """Only the target's own visible primary UI can corroborate its card."""
    view = consume(record, 'CONTROL')
    if not view['schema_valid']:
        return view['status']
    if view['status'] == 'CANONICAL_QUARANTINED':
        return 'CANONICAL_CONTROL_QUARANTINED'
    if not view['primary_ui_proven']:
        return 'CANONICAL_CONTROL_PRIMARY_UI_NOT_VERIFIED'
    if not view['card_ui_corroborated']:
        return 'CANONICAL_CARD_PRIMARY_UI_NOT_CORROBORATED'
    if (view['primary_transaction_status']=='RESERVED'
        and view['product_jsonld_stock_class']=='SOLD_OUT'):
        return 'CANONICAL_CARD_UI_MATCH_SOLDOUT_SEMANTIC_GAP'
    return {
        'UNAVAILABLE_GENERIC': 'CANONICAL_CARD_UI_MATCH_GENERIC_STOCK',
        'SOLD_OUT': 'CANONICAL_CARD_UI_MATCH_SOLD_OUT_STOCK',
        'AVAILABLE': 'CANONICAL_CARD_UI_MATCH_AVAILABLE_STOCK',
    }.get(view['product_jsonld_stock_class'],
          'CANONICAL_CARD_UI_MATCH_STOCK_UNSPECIFIC')


def summarize(views, expected_count=None):
    """Never use historical comparison labels to grant a canonical witness."""
    cleaned = [v for v in views if isinstance(v, dict)]
    statuses = Counter(v.get('status', 'INVALID_CONSUMER') for v in cleaned)
    valid = sum(v.get('schema_valid') is True for v in cleaned)
    ui = sum(v.get('primary_ui_proven') is True for v in cleaned)
    sale_filter = sum(v.get('sale_filter_eligible') is True for v in cleaned)
    inferred = sum(v.get('sale_filter_inferred') is True for v in cleaned)
    card = sum(v.get('card_ui_corroborated') is True for v in cleaned)
    expected = expected_count if type(expected_count) is int and expected_count >= 0 else len(cleaned)
    complete = len(cleaned) == expected and valid == expected
    return {
        'status': 'CANONICAL_COVERAGE_COMPLETE' if complete
                  else 'INCOMPLETE_CANONICAL_COVERAGE',
        'expected_records': expected,
        'observed_records': len(cleaned),
        'schema_valid_records': valid,
        'primary_ui_proven_records': ui,
        'source_sale_filter_eligible_records': sale_filter,
        'source_sale_filter_inferred_records': inferred,
        'direct_for_sale_badge_required': False,
        'card_primary_ui_corroborated_records': card,
        'consumer_status_counts': dict(sorted(statuses.items())),
        'legacy_coarse_status_used': False,
        'stock_metadata_promoted_to_transaction': False,
        'strict_listing_approved_count': 0,
    }
