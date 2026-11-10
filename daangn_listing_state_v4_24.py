# -*- coding: utf-8 -*-
"""v4.24 common evidence model: transaction UI != stock availability.

Pure, offline, JSON-safe domain layer. A Product JSON-LD availability field
cannot supply or overwrite an item's UI transaction state. A linked-card badge
is a separate hypothesis, not primary item proof. Every returned value is an
allowlisted finite enum or bounded integer; no raw seller/listing data.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

VERSION='4.24'
UI_STATES=frozenset({'AVAILABLE','RESERVED','SOLD','AMBIGUOUS','NOT_OBSERVABLE'})
TRANSACTION_STATES=frozenset({'FOR_SALE','RESERVED','SOLD','NOT_OBSERVABLE',
                              'AMBIGUOUS','NOT_VERIFIED'})
AVAILABILITY_KINDS=frozenset({
    'IN_STOCK','OUT_OF_STOCK','SOLD_OUT','PRE_ORDER','PRE_SALE',
    'OTHER','NOT_OBSERVABLE','AMBIGUOUS'})
STOCK_CLASSES=frozenset({
    'AVAILABLE','UNAVAILABLE_GENERIC','SOLD_OUT','PRE_ORDER',
    'PRE_SALE','UNKNOWN','AMBIGUOUS'})
UI_MAP={'AVAILABLE':'FOR_SALE','RESERVED':'RESERVED','SOLD':'SOLD'}
STOCK_MAP={'IN_STOCK':'AVAILABLE','OUT_OF_STOCK':'UNAVAILABLE_GENERIC',
           'SOLD_OUT':'SOLD_OUT','PRE_ORDER':'PRE_ORDER','PRE_SALE':'PRE_SALE',
           'AMBIGUOUS':'AMBIGUOUS','NOT_OBSERVABLE':'UNKNOWN','OTHER':'UNKNOWN'}
CARD_MAP={'AVAILABLE':'FOR_SALE','RESERVED':'RESERVED','SOLD':'SOLD'}
CARD_COMPARISONS=frozenset({'NOT_APPLICABLE','CARD_AND_PRIMARY_UI_MATCH',
              'CARD_AND_PRIMARY_UI_CONFLICT','CARD_ONLY_PRIMARY_UNOBSERVABLE'})
SEMANTIC_COMPARISONS=frozenset({
    'AVAILABILITY_ONLY_PRIMARY_UI_NOT_OBSERVABLE',
    'BOTH_SOURCES_NOT_OBSERVABLE',
    'SOURCE_INVALID_OR_INCOMPLETE',
    'POTENTIAL_AVAILABLE_VS_UNAVAILABLE_CONFLICT',
    'POTENTIAL_UNAVAILABLE_VS_IN_STOCK_CONFLICT',
    'GENERIC_UNAVAILABILITY_NOT_TRANSACTION_PROOF',
    'SOLD_OUT_COMPATIBLE_NOT_TRANSACTION_PROOF',
    'SOLD_OUT_VS_RESERVED_SEMANTIC_GAP',
    'PREORDER_STATUS_NOT_RESERVATION_PROOF',
    'AVAILABLE_AND_IN_STOCK_COMPATIBLE',
    'PRIMARY_UI_ONLY_STOCK_UNOBSERVABLE',
    'AMBIGUOUS_SOURCES'})
EVIDENCE_TIERS=frozenset({
    'QUARANTINED','INCONCLUSIVE','UI_AND_METADATA_COMPATIBLE',
    'UI_OBSERVED_STOCK_UNSPECIFIC','METADATA_ONLY_NO_TRANSACTION_PROOF',
    'UI_ONLY_NO_STOCK_PROOF'})
CONTEXTS=frozenset({'SOURCE','CONTROL'})
UI_ORIGIN=frozenset({'PRIMARY_STATUS_MARKER','PRIMARY_EXACT_VISIBLE_LEAF',
                    'PRIMARY_PHASE_OBSERVATION','NONE','OTHER'})


def _source_tag(value):
    return value if isinstance(value,str) and value in UI_ORIGIN else 'OTHER'


def normalize_ui_states(states: Any, *,identity_confirmed:bool,
                        render_complete:bool) -> str:
    """Only direct primary visible UI statuses can establish transaction state.

    A phase that has an AMBIGUOUS status invalidates any positive observation;
    conflicting states across phases also remain ambiguous. Incomplete render
    or changed identity prevents a positive claim.
    """
    if not identity_confirmed or not render_complete:
        return 'NOT_VERIFIED'
    if not isinstance(states,(list,tuple)) or not states or len(states)>4:
        return 'NOT_VERIFIED'
    if any(not isinstance(v,str) or v not in UI_STATES for v in states):
        return 'NOT_VERIFIED'
    if 'AMBIGUOUS' in states:
        return 'AMBIGUOUS'
    found={UI_MAP[v] for v in states if v in UI_MAP}
    if len(found)>1:
        return 'AMBIGUOUS'
    return next(iter(found)) if found else 'NOT_OBSERVABLE'


def normalize_availability(kind: Any, *,same_product:bool) -> tuple[str,str]:
    """Retain exact schema.org enum; NEVER return transaction SOLD/RESERVED."""
    if not same_product or not isinstance(kind,str) or kind not in AVAILABILITY_KINDS:
        return ('NOT_OBSERVABLE','UNKNOWN')
    return kind,STOCK_MAP[kind]


def compare_card_to_primary(card_state,txn):
    if card_state is None:return 'NOT_APPLICABLE'
    if not isinstance(card_state,str) or card_state not in CARD_MAP or txn not in TRANSACTION_STATES:
        return 'CARD_ONLY_PRIMARY_UNOBSERVABLE'
    if txn in ('NOT_OBSERVABLE','AMBIGUOUS','NOT_VERIFIED'):
        return 'CARD_ONLY_PRIMARY_UNOBSERVABLE'
    return ('CARD_AND_PRIMARY_UI_MATCH' if CARD_MAP[card_state]==txn
            else 'CARD_AND_PRIMARY_UI_CONFLICT')


def compare_semantics(txn,stock):
    """Compatibility is not a transaction-status verification by JSON-LD."""
    if (not isinstance(txn,str) or txn not in TRANSACTION_STATES or
        not isinstance(stock,str) or stock not in STOCK_CLASSES):
        return 'SOURCE_INVALID_OR_INCOMPLETE'
    if txn in ('AMBIGUOUS','NOT_VERIFIED') or stock=='AMBIGUOUS':
        return 'AMBIGUOUS_SOURCES'
    if txn=='NOT_OBSERVABLE':
        return ('BOTH_SOURCES_NOT_OBSERVABLE' if stock=='UNKNOWN'
                else 'AVAILABILITY_ONLY_PRIMARY_UI_NOT_OBSERVABLE')
    if stock=='UNKNOWN':
        return 'PRIMARY_UI_ONLY_STOCK_UNOBSERVABLE'
    if txn=='FOR_SALE':
        return ('AVAILABLE_AND_IN_STOCK_COMPATIBLE' if stock=='AVAILABLE'
                else 'POTENTIAL_AVAILABLE_VS_UNAVAILABLE_CONFLICT')
    if txn in ('RESERVED','SOLD') and stock=='AVAILABLE':
        return 'POTENTIAL_UNAVAILABLE_VS_IN_STOCK_CONFLICT'
    if stock=='UNAVAILABLE_GENERIC':
        return 'GENERIC_UNAVAILABILITY_NOT_TRANSACTION_PROOF'
    if stock=='SOLD_OUT':
        return ('SOLD_OUT_COMPATIBLE_NOT_TRANSACTION_PROOF' if txn=='SOLD'
                else 'SOLD_OUT_VS_RESERVED_SEMANTIC_GAP')
    return 'PREORDER_STATUS_NOT_RESERVATION_PROOF'


def evidence_tier(txn,comparison,card_comparison):
    if (txn in ('AMBIGUOUS','NOT_VERIFIED') or
        card_comparison=='CARD_AND_PRIMARY_UI_CONFLICT' or
        comparison in ('POTENTIAL_AVAILABLE_VS_UNAVAILABLE_CONFLICT',
            'POTENTIAL_UNAVAILABLE_VS_IN_STOCK_CONFLICT',
            'SOURCE_INVALID_OR_INCOMPLETE','AMBIGUOUS_SOURCES')):
        return 'QUARANTINED'
    if txn=='NOT_OBSERVABLE':
        return ('METADATA_ONLY_NO_TRANSACTION_PROOF'
                if comparison=='AVAILABILITY_ONLY_PRIMARY_UI_NOT_OBSERVABLE'
                else 'INCONCLUSIVE')
    if comparison=='PRIMARY_UI_ONLY_STOCK_UNOBSERVABLE':
        return 'UI_ONLY_NO_STOCK_PROOF'
    if comparison in ('GENERIC_UNAVAILABILITY_NOT_TRANSACTION_PROOF',
                      'PREORDER_STATUS_NOT_RESERVATION_PROOF',
                      'SOLD_OUT_VS_RESERVED_SEMANTIC_GAP'):
        return 'UI_OBSERVED_STOCK_UNSPECIFIC'
    if comparison in ('AVAILABLE_AND_IN_STOCK_COMPATIBLE',
                      'SOLD_OUT_COMPATIBLE_NOT_TRANSACTION_PROOF'):
        return 'UI_AND_METADATA_COMPATIBLE'
    return 'INCONCLUSIVE'


def build_record(ui_states,exact_availability,*,card_state=None,
                 identity_confirmed=False,render_complete=False,
                 same_product=False,context='SOURCE',ui_origin='NONE'):
    """Canonical item evidence fields. All inputs are untrusted observations.

    status UI provenance is separate from Product JSON-LD exact availability.
    A source-card signal remains separate even if it agrees with target UI.
    """
    context=context if isinstance(context,str) and context in CONTEXTS else 'SOURCE'
    txn=normalize_ui_states(ui_states,identity_confirmed=identity_confirmed,
                            render_complete=render_complete)
    exact,stock=normalize_availability(exact_availability,
                 same_product=bool(identity_confirmed and same_product))
    card=(card_state if isinstance(card_state,str) and card_state in CARD_MAP else None)
    compare_card=compare_card_to_primary(card,txn)
    compare_stock=compare_semantics(txn,stock)
    tier=evidence_tier(txn,compare_stock,compare_card)
    return {
        'schema_version':VERSION,
        'context_kind':context,
        'identity_confirmed':identity_confirmed is True,
        'render_complete':render_complete is True,
        'primary_transaction_status':txn,
        'primary_transaction_source':(_source_tag(ui_origin)
            if txn in ('FOR_SALE','RESERVED','SOLD') else 'NONE'),
        'linked_card_status':card if card is not None else 'NOT_APPLICABLE',
        'linked_card_is_primary_proof':False,
        'product_jsonld_exact_availability':exact,
        'product_jsonld_stock_class':stock,
        'jsonld_is_primary_transaction_proof':False,
        'availability_to_transaction_conversion_performed':False,
        'card_primary_comparison':compare_card,
        'transaction_stock_semantic_comparison':compare_stock,
        'independent_evidence_tier':tier,
        'strict_listing_approved':False
    }


def clean_record(record):
    """Return a safe copy only if the canonical fields are self-consistent.

    This also prevents incidental untrusted properties from later source
    records being carried into the public v4.24 evidence artifact.
    """
    if not isinstance(record,dict) or record.get('schema_version')!=VERSION:
        return None
    strings={
        'context_kind':CONTEXTS,
        'primary_transaction_status':TRANSACTION_STATES,
        'primary_transaction_source':UI_ORIGIN,
        'linked_card_status':set(CARD_MAP)|{'NOT_APPLICABLE'},
        'product_jsonld_exact_availability':AVAILABILITY_KINDS,
        'product_jsonld_stock_class':STOCK_CLASSES,
        'card_primary_comparison':CARD_COMPARISONS,
        'transaction_stock_semantic_comparison':SEMANTIC_COMPARISONS,
        'independent_evidence_tier':EVIDENCE_TIERS}
    clean={'schema_version':VERSION}
    for name,enum in strings.items():
        val=record.get(name)
        if not isinstance(val,str) or val not in enum:
            return None
        clean[name]=val
    bools=('identity_confirmed','render_complete','linked_card_is_primary_proof',
           'jsonld_is_primary_transaction_proof',
           'availability_to_transaction_conversion_performed',
           'strict_listing_approved')
    for name in bools:
        val=record.get(name)
        if type(val) is not bool:return None
        clean[name]=val
    if any(clean[k] for k in (
        'linked_card_is_primary_proof','jsonld_is_primary_transaction_proof',
        'availability_to_transaction_conversion_performed','strict_listing_approved')):
        return None
    txn=clean['primary_transaction_status']
    if txn in ('FOR_SALE','RESERVED','SOLD') and not (
        clean['identity_confirmed'] and clean['render_complete'] and
        clean['primary_transaction_source'] in
            ('PRIMARY_STATUS_MARKER','PRIMARY_EXACT_VISIBLE_LEAF',
             'PRIMARY_PHASE_OBSERVATION')):
        return None
    if clean['product_jsonld_stock_class']!=STOCK_MAP[
            clean['product_jsonld_exact_availability']]:
        return None
    if clean['transaction_stock_semantic_comparison']!=compare_semantics(
            txn,clean['product_jsonld_stock_class']):
        return None
    card=None if clean['linked_card_status']=='NOT_APPLICABLE' else clean['linked_card_status']
    if clean['card_primary_comparison']!=compare_card_to_primary(card,txn):
        return None
    if clean['independent_evidence_tier']!=evidence_tier(
        txn,clean['transaction_stock_semantic_comparison'],
        clean['card_primary_comparison']):
        return None
    if clean['context_kind']=='SOURCE' and card is not None:
        return None
    if not clean['identity_confirmed'] and clean[
            'product_jsonld_exact_availability']!='NOT_OBSERVABLE':
        return None
    return clean


def summarize_records(records):
    """Sanitize + aggregate only schema records, never raw source rows."""
    accepted=[]
    for item in records:
        safe=clean_record(item)
        if safe is not None:
            accepted.append(safe)
    by_txn=Counter(x['primary_transaction_status'] for x in accepted)
    by_exact=Counter(x['product_jsonld_exact_availability'] for x in accepted)
    by_tier=Counter(x['independent_evidence_tier'] for x in accepted)
    by_semantic=Counter(x['transaction_stock_semantic_comparison'] for x in accepted)
    by_context=Counter(x['context_kind'] for x in accepted if isinstance(x.get('context_kind'),str) and x['context_kind'] in CONTEXTS)
    return {
        'record_count':len(accepted),
        'transaction_status_counts':dict(sorted(by_txn.items())),
        'exact_availability_counts':dict(sorted(by_exact.items())),
        'semantic_comparison_counts':dict(sorted(by_semantic.items())),
        'independent_evidence_tier_counts':dict(sorted(by_tier.items())),
        'context_record_counts':dict(sorted(by_context.items())),
        'out_of_stock_is_not_sold_out':True,
        'out_of_stock_does_not_prove_reserved_or_sold':True,
        'product_jsonld_used_as_transaction_proof':False,
        'linked_card_used_as_primary_ui_proof':False,
        'historical_strict_gate_overridden':False,
        'strict_listing_approved_count':0
    }
