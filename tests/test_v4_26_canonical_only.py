# -*- coding: utf-8 -*-
"""v4.26 negative controls for total canonical-only consumer cutover."""
from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,Mock

import daangn_detail_crosscheck_v4_20 as detail
import daangn_sale_sources_v4_21 as sources
import daangn_state_controls_v4_23 as controls
import daangn_listing_state_v4_24 as canonical
from scripts.audit_state_conversions_v425 import audit_repository

ROOT=Path(__file__).resolve().parents[1]


def rec(ui='NOT_OBSERVABLE', stock='OUT_OF_STOCK',card=None,context='SOURCE'):
    return canonical.build_record([ui],stock,card_state=card,context=context,
         identity_confirmed=True,render_complete=True,same_product=True,
         ui_origin='PRIMARY_STATUS_MARKER'
         if ui in ('AVAILABLE','RESERVED','SOLD') else 'NONE')


class FullCutover(unittest.TestCase):
    def test_zero_direct_conversions_after_release(self):
        audit=audit_repository(ROOT)
        self.assertEqual(audit['status'],'PASS',audit['violations'])
        self.assertEqual(audit['direct_stock_to_sold_sites'],{})
        self.assertEqual(audit['expected_direct_conversion_sites'],0)

    def test_detail_cannot_take_legacy_sold_claim_without_canonical(self):
        probe={'status':'OBSERVED','primary_item_present':True,
               'primary_heading_visible':True,'category':{'verdict':'MATCH'},
               'sale':{'verdict':'SOLD','source':'MATCHED_PRODUCT_JSONLD'}}
        self.assertEqual(detail.classify_detail(probe,True),
                         'DETAIL_CANONICAL_NOT_VERIFIED')
        self.assertEqual(detail.classify_detail(probe,True,rec()),
                         'CATEGORY_ONLY')
        self.assertEqual(detail.classify_detail(probe,True,rec('SOLD')),
                         'NOT_AVAILABLE')

    def test_no_kind_can_raise_unobserved_ui_to_marketplace_sold(self):
        for kind in canonical.AVAILABILITY_KINDS:
            model=rec('NOT_OBSERVABLE',kind)
            self.assertEqual(model['primary_transaction_status'],'NOT_OBSERVABLE')
            self.assertNotEqual(sources.compare_sources(
                {'status':'OBSERVED','valid_primary':True},
                canonical_record=model),'CANONICAL_UI_AND_STOCK_COMPATIBLE')

    def test_control_ignores_old_jsonld_state_arguments(self):
        with self.assertRaises(TypeError):
            controls.control_verdict('SOLD',['SOLD'],'SOLD','CAPTURED',
                                     availability_kind='OUT_OF_STOCK')

    def test_sold_and_reserved_same_generic_availability(self):
        sold=controls.control_verdict(rec('SOLD','OUT_OF_STOCK','SOLD','CONTROL'))
        reserved=controls.control_verdict(rec('RESERVED','OUT_OF_STOCK','RESERVED','CONTROL'))
        self.assertEqual(sold,'CANONICAL_CARD_UI_MATCH_GENERIC_STOCK')
        self.assertEqual(reserved,'CANONICAL_CARD_UI_MATCH_GENERIC_STOCK')

    def test_reserved_vs_exact_soldout_remains_gap(self):
        verdict=controls.control_verdict(rec('RESERVED','SOLD_OUT','RESERVED','CONTROL'))
        self.assertEqual(verdict,'CANONICAL_CARD_UI_MATCH_SOLDOUT_SEMANTIC_GAP')

    def test_mutated_stock_class_cannot_be_promoted(self):
        model=rec('RESERVED','OUT_OF_STOCK','RESERVED','CONTROL')
        model['product_jsonld_stock_class']='SOLD_OUT'
        self.assertEqual(controls.control_verdict(model),'INVALID_CANONICAL_RECORD')

    def test_untrusted_nested_status_values_do_not_crash_probes(self):
        raw={'valid_primary':True,'ui':{'state':{'private':'x'},
            'source':['not-a-source'],'candidates':0},
             'jsonld':{'kind':['OUT_OF_STOCK'],
            'source':'MATCHED_PRODUCT_JSONLD','matching_product_count':1}}
        safe=sources.sanitize(raw)
        self.assertEqual(safe['ui']['state'],'NOT_OBSERVABLE')
        self.assertEqual(safe['ui']['source'],'NONE')
        self.assertEqual(safe['jsonld']['kind'],'NOT_OBSERVABLE')
        phases=controls.phase_projection({
            'phases':{'initial':{'v421_ui_state':{'private':'x'}}}})
        self.assertEqual(phases['initial']['ui'],'NOT_OBSERVABLE')

    def test_invalid_exact_availability_type_is_not_transaction(self):
        page=Mock(evaluate=AsyncMock(return_value={
            'kind':['SOLD_OUT'],'matched_product_count':1}))
        result=asyncio.run(controls.probe_exact_availability(page))
        self.assertEqual(result['kind'],'OTHER')
        self.assertNotIn('SOLD',result.values())

    def test_no_prior_comparison_can_overwrite_current_canonical(self):
        clean=rec('NOT_OBSERVABLE','OUT_OF_STOCK')
        payload={'status':'OBSERVED','valid_primary':True,
                 'ui':{'state':'SOLD'},'jsonld':{'state':'SOLD'}}
        decision=sources.compare_sources(payload,True,clean)
        self.assertEqual(decision,'CANONICAL_METADATA_NOT_PRIMARY_UI_PROOF')
        self.assertFalse(clean['strict_listing_approved'])


if __name__=='__main__':
    unittest.main()
