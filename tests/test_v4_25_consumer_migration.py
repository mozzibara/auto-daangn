# -*- coding: utf-8 -*-
"""v4.25 offline regression: canonical consumers never promote stock to SOLD."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import daangn_listing_state_v4_24 as state
import daangn_sale_sources_v4_21 as sources
import daangn_state_controls_v4_23 as controls
import daangn_state_consumers_v4_25 as consumer
from scripts.audit_state_conversions_v425 import audit_repository, find_direct_mappings

ROOT = Path(__file__).resolve().parents[1]


def canonical(ui='NOT_OBSERVABLE', stock='IN_STOCK', card=None,
              context='SOURCE', complete=True, same=True):
    return state.build_record(
        [ui], stock, card_state=card, identity_confirmed=True,
        render_complete=complete, same_product=same, context=context,
        ui_origin=('PRIMARY_STATUS_MARKER' if ui in ('AVAILABLE', 'SOLD', 'RESERVED')
                   else 'NONE'))


def rows421(record):
    result = []
    for name in ('cheonan_a', 'asan_control', 'cheonan_b'):
        samples = []
        for rank in (0, 32, 135):
            samples.append({
                'source_rank':rank, 'same_listing_identity':True,
                'page_status':'HTTP_200_IDENTITY_MATCH',
                'v421_sale_sources':{'status':'OBSERVED',
                    'ui':{'state':'NOT_OBSERVABLE','source':'NONE'},
                    'jsonld':{'kind':'OUT_OF_STOCK','source':'MATCHED_PRODUCT_JSONLD'}},
                'v421_sale_comparison':'CONCORDANT_SOLD',
                **({'v424_state_model':record} if record is not None else {}),
            })
        result.append({'context':name, 'route_correlated':True,
            'route_count':270, 'v420_detail_audit':{
                'status':'DETAIL_SAMPLE_AUDITED', 'page_visits':3,
                'selected_sample_count':3, 'samples':samples, 'stop_access':False}})
    return result


def rows423(with_canonical):
    result = []
    for name in ('cheonan_a','asan_control','cheonan_b'):
        ctl = []
        for sale in ('SOLD','RESERVED'):
            item = {'source_card_state':sale,'status':'AUDITED',
                    'source_rank':0,
                    'comparison':'THREE_WITNESSES_CONCORDANT'}
            if with_canonical:
                item['v424_state_model']=canonical(
                    sale, 'OUT_OF_STOCK', sale, 'CONTROL')
            ctl.append(item)
        result.append({'context':name,'route_correlated':True,
            'v420_detail_audit':{'status':'DETAIL_SAMPLE_AUDITED',
                'page_visits':3, 'stop_access':False,
                'samples':[{'v424_state_model':canonical('NOT_OBSERVABLE',
                            'IN_STOCK'),'v423_card_stats':{'eligible_by_state':
                             {'SOLD':1,'RESERVED':1}}} for _ in range(3)],
                'v423_controls':{'status':'CONTROL_DETAILS_AUDITED',
                    'selected_control_count':2,'visited_control_count':2,
                    'controls':ctl}}})
    return result


class CanonicalConsumer(unittest.TestCase):
    def test_stock_never_establishes_sold_without_primary_ui(self):
        for kind in ('IN_STOCK','OUT_OF_STOCK','SOLD_OUT',
                     'PRE_ORDER','PRE_SALE'):
            view=consumer.consume(canonical(stock=kind),'SOURCE')
            self.assertEqual(view['status'],'CANONICAL_NO_PRIMARY_UI_PROOF')
            self.assertEqual(view['primary_transaction_status'],'NOT_OBSERVABLE')
            self.assertFalse(view['primary_ui_proven'])
            self.assertFalse(view['legacy_coarse_status_used'])
            self.assertEqual(consumer.source_comparison(canonical(stock=kind)),
                             'CANONICAL_METADATA_NOT_PRIMARY_UI_PROOF')

    def test_outofstock_not_soldout_and_sold_ui_is_only_sale_proof(self):
        for kind in ('OUT_OF_STOCK','SOLD_OUT'):
            r=canonical('SOLD',kind)
            view=consumer.consume(r,'SOURCE')
            self.assertEqual(view['status'],'CANONICAL_PRIMARY_UI_SOLD')
            self.assertEqual(view['product_jsonld_exact_availability'],kind)
            self.assertTrue(view['primary_ui_proven'])
            self.assertFalse(view['strict_listing_approved'])
        self.assertEqual(consumer.source_comparison(
            canonical('SOLD','OUT_OF_STOCK')),
            'CANONICAL_UI_WITH_NONSPECIFIC_STOCK')

    def test_reserved_ui_with_outofstock_is_not_sold(self):
        view=consumer.consume(canonical('RESERVED','OUT_OF_STOCK'),'SOURCE')
        self.assertEqual(view['primary_transaction_status'],'RESERVED')
        self.assertEqual(view['product_jsonld_stock_class'],'UNAVAILABLE_GENERIC')
        self.assertEqual(view['status'],'CANONICAL_PRIMARY_UI_RESERVED')

    def test_metadata_conflict_is_quarantined(self):
        for ui,kind in [('SOLD','IN_STOCK'),('RESERVED','IN_STOCK'),
                        ('AVAILABLE','OUT_OF_STOCK')]:
            record=canonical(ui,kind)
            view=consumer.consume(record,'SOURCE')
            self.assertEqual(view['status'],'CANONICAL_QUARANTINED')
            self.assertFalse(view['primary_ui_proven'])
            self.assertIn('QUARANTINED',consumer.source_comparison(record))

    def test_card_is_hypothesis_until_primary_control_ui_observed(self):
        missing=canonical('NOT_OBSERVABLE','OUT_OF_STOCK','SOLD','CONTROL')
        agreed=canonical('RESERVED','OUT_OF_STOCK','RESERVED','CONTROL')
        self.assertFalse(consumer.consume(missing,'CONTROL')['card_ui_corroborated'])
        self.assertEqual(consumer.control_comparison(missing),
                         'CANONICAL_CONTROL_PRIMARY_UI_NOT_VERIFIED')
        view=consumer.consume(agreed,'CONTROL')
        self.assertTrue(view['card_ui_corroborated'])
        self.assertEqual(consumer.control_comparison(agreed),
                         'CANONICAL_CARD_UI_MATCH_GENERIC_STOCK')

    def test_malformed_context_and_legacy_projections_fail_closed(self):
        self.assertEqual(consumer.consume(None,'SOURCE')['status'],
                         'MISSING_CANONICAL_RECORD')
        self.assertEqual(consumer.consume(
            {'jsonld':'SOLD','sale':'SOLD'},'SOURCE')['status'],
            'INVALID_CANONICAL_RECORD')
        self.assertFalse(consumer.consume(
            canonical('SOLD','SOLD_OUT'),'CONTROL')['schema_valid'])
        bad=dict(canonical('SOLD','OUT_OF_STOCK'),
                 primary_transaction_source='NONE')
        self.assertFalse(consumer.consume(bad,'SOURCE')['schema_valid'])
        self.assertEqual(consumer.consume(canonical(),'UNKNOWN')['status'],
                         'INVALID_EXPECTED_CONTEXT')


class RealConsumers(unittest.TestCase):
    def test_v421_legacy_concordant_sold_does_not_create_transaction(self):
        evaluation=sources.aggregate(rows421(canonical(stock='OUT_OF_STOCK')))
        report=evaluation['v425_canonical_consumer']
        self.assertEqual(report['status'],'CANONICAL_COVERAGE_COMPLETE')
        self.assertEqual(report['schema_valid_records'],9)
        self.assertEqual(report['primary_ui_proven_records'],0)
        self.assertEqual(evaluation['context_results'][0]['samples'][0]
                         ['comparison'],'CANONICAL_METADATA_NOT_PRIMARY_UI_PROOF')
        self.assertEqual(evaluation['strict_listing_approved_count'],0)
        self.assertNotIn('seller',json.dumps(evaluation))

    def test_v421_missing_canonical_does_not_fall_back_to_sold(self):
        evaluation=sources.aggregate(rows421(None))
        report=evaluation['v425_canonical_consumer']
        self.assertEqual(report['status'],'INCOMPLETE_CANONICAL_COVERAGE')
        self.assertEqual(report['primary_ui_proven_records'],0)
        self.assertEqual(report['schema_valid_records'],0)

    def test_v423_legacy_three_witness_code_cannot_grant_canonical_proof(self):
        evaluation=controls.aggregate(rows423(False))
        self.assertFalse(evaluation['v425_both_control_classes_ui_proven'])
        self.assertEqual(evaluation['v425_canonical_consumer']
                         ['primary_ui_proven_records'],0)
        self.assertEqual(evaluation['strict_listing_approved_count'],0)

    def test_v423_canonical_both_classes_with_generic_stock(self):
        evaluation=controls.aggregate(rows423(True))
        self.assertTrue(evaluation['v425_both_control_classes_ui_proven'])
        self.assertEqual(evaluation['v425_canonical_consumer']
                         ['card_primary_ui_corroborated_records'],6)
        self.assertEqual(evaluation['v425_per_class_primary_ui_proven'],
                         {'SOLD':True,'RESERVED':True})
        self.assertEqual(evaluation['strict_listing_approved_count'],0)

    def test_v423_card_only_cannot_become_primary_ui(self):
        rows=rows423(True)
        for row in rows:
            for ctl in row['v420_detail_audit']['v423_controls']['controls']:
                ctl['v424_state_model']=canonical(
                    'NOT_OBSERVABLE','OUT_OF_STOCK',
                    ctl['source_card_state'],'CONTROL')
        evaluation=controls.aggregate(rows)
        self.assertFalse(evaluation['v425_both_control_classes_ui_proven'])
        self.assertEqual(evaluation['v425_canonical_consumer']
                         ['primary_ui_proven_records'],0)


class RepositoryAudit(unittest.TestCase):
    def test_every_production_python_path_scanned_zero_direct_mapping(self):
        result=audit_repository(ROOT)
        self.assertEqual(result['status'],'PASS',result['violations'])
        self.assertEqual(result['direct_stock_to_sold_sites'],{})
        self.assertEqual(result['expected_direct_conversion_sites'],0)
        self.assertGreaterEqual(result['production_python_files_scanned'],35)

    def test_new_stock_to_sold_mapping_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'new_consumer.py'
            p.write_text("if a==='OutOfStock'||a==='SoldOut': return 'SOLD'\n",
                         encoding='utf-8')
            self.assertIn('new_consumer.py',find_direct_mappings(Path(temp)))


if __name__=='__main__':
    unittest.main()
