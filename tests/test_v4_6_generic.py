# -*- coding: utf-8 -*-
"""Offline tests for generic profile and strict region/price gate."""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
import daangn_browser_v4_6 as app
import daangn_v4_5_evidence as ev
import daangn_v4_4_gate as old

BASE='https://www.daangn.com/kr/search/buy-sell/'

def argv_args(*cli,config=None):
    """Use the actual CLI parser without executing site work."""
    with patch.object(sys,'argv',['prog',*cli]),patch.object(app,'run',new_callable=AsyncMock) as fake:
        fake.return_value=0
        app.main()
        return fake.call_args.args[0]


def model(rid='2292',price=10000,category=1,available=True,maximum=50000,minimum=None):
    filters={'regionId':rid,'categoryId':category,'onlyOnSale':available,'maxPrice':maximum}
    if minimum is not None: filters['minPrice']=minimum
    urls=[f'https://www.daangn.com/kr/buy-sell/drive-{10000+i:012d}/' for i in range(50)]
    return {'region_id':rid,'filter_region_id':rid,'filters':filters,
            'articles':[{'href':u,'price':price,'categoryId':category,'isSoldOut':False} for u in urls]}


class Args(unittest.TestCase):
    def test_presets_and_default_profile(self):
        x=argv_args()
        self.assertEqual(x.keyword,'HDD')
        self.assertEqual(x.regions['target']['id'],'2292')
        self.assertEqual(x.regions['control']['id'],'2333')
        self.assertEqual(x.category_id,1)
        self.assertEqual(x.max_price,50000)
        self.assertTrue(x.available_only)
        self.assertEqual(app.plans_for(x), (('target_a','target'),('control_a','control'),('target_b','target'),('control_b','control')))

    def test_other_preset_and_keyword(self):
        x=argv_args('--region','sadang','--control-region','cheonan','--keyword','러닝화','--max-price','85000')
        self.assertEqual(x.keyword,'러닝화')
        self.assertEqual(x.regions['target']['term'],'사당제3동')
        self.assertEqual(x.max_price,85000)

    def test_custom_region_without_global_mutation(self):
        x=argv_args('--region','임의 지역','--region-slug','임의동-98765',
                    '--control-region','다른 지역','--control-region-slug','다른동-67890')
        self.assertEqual(x.regions['target']['id'],'98765')
        self.assertEqual(x.regions['control']['term'],'다른동')

    def test_config_with_override(self):
        with TemporaryDirectory() as d:
            fn=Path(d)/'settings.json'
            fn.write_text(json.dumps({'region':'sadang','control_region':'asan',
                     'keyword':'청소기','max_price':90000,'category_id':172,
                     'available_only':False}),encoding='utf-8')
            x=argv_args('--config',str(fn),'--max-price','70000')
        self.assertEqual(x.max_price,70000)
        self.assertEqual(x.category_name,'생활가전')
        self.assertFalse(x.available_only)

    def test_include_sold_overrides_config(self):
        x=argv_args('--include-sold')
        self.assertFalse(x.available_only)

    def test_reject_invalid_settings(self):
        bad=(('--region','unknown'),('--region','asan','--control-region','asan'),
             ('--max-price','0'),('--min-price','60000'),('--max-price','500.5'),
             ('--category-id','999999'),('--keyword',''),
             ('--region','서울','--region-slug','bad-without-id'))
        for args in bad:
            with self.subTest(args=args),self.assertRaises(SystemExit) as cm:
                argv_args(*args)
            self.assertEqual(cm.exception.code,2)

    def test_reject_unsupported_config_keys(self):
        with TemporaryDirectory() as d:
            fn=Path(d)/'settings.json'
            fn.write_text('{"token":"should-not-be-used"}',encoding='utf-8')
            with self.assertRaises(SystemExit):argv_args('--config',str(fn))


class Evidence(unittest.TestCase):
    def test_variable_max_verified_only_with_server_field(self):
        expected={'keyword':'청소기','category':'생활가전','category_id':172,
                  'min_price_krw':0,'max_price_krw':25000,'available_only':True}
        url=BASE+'?q=%EC%B2%AD%EC%86%8C%EA%B8%B0&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292&category_id=172&only_on_sale=true&price=__25000'
        evidence=ev.validated_predicates(model(price=20000,category=172,maximum=25000),url,'2292',True,True,
                        ui_observation_status='OBSERVED_MATCH',expected=expected)
        self.assertTrue(evidence['approved'])
        self.assertEqual(evidence['criteria']['max_price']['candidate_max_krw'],25000)

    def test_url_and_items_not_enough(self):
        expected={'keyword':'청소기','category':'생활가전','category_id':172,
                  'min_price_krw':0,'max_price_krw':25000,'available_only':True}
        m=model(price=20000,category=172,maximum=25000)
        m['filters'].pop('maxPrice')
        evidence=ev.validated_predicates(m,BASE+'?q=청소기&in=불당동-2292&category_id=172&only_on_sale=true&price=__25000',
                      '2292',True,True,ui_observation_status='OBSERVED_MATCH',expected=expected)
        self.assertFalse(evidence['approved'])
        self.assertEqual(evidence['evidence_tier'],'URL_ITEM_CORROBORATION_ONLY')

    def test_hard_max_violation_quarantined(self):
        expected={'keyword':'청소기','category':'생활가전','category_id':172,
                  'min_price_krw':0,'max_price_krw':25000,'available_only':True}
        m=model(price=25001,category=172,maximum=25000)
        proof=ev.validated_predicates(m,BASE+'?q=청소기&in=불당동-2292&price=__25000',
                      '2292',True,True,ui_observation_status='NOT_OBSERVABLE',expected=expected)
        self.assertEqual(proof['status'],'QUARANTINED_ITEM_FILTER_VIOLATION')

    def test_minimum_requires_server_proof(self):
        expected={'keyword':'청소기','category':'생활가전','category_id':172,
                  'min_price_krw':10000,'max_price_krw':25000,'available_only':True}
        m=model(price=20000,category=172,maximum=25000,minimum=None)
        result=ev.validated_predicates(m,BASE+'?q=청소기&in=불당동-2292&price=10000__25000',
                      '2292',True,True,ui_observation_status='OBSERVED_MATCH',expected=expected)
        self.assertFalse(result['approved']);self.assertFalse(result['criteria']['max_price']['minimum_ok'])
        m['filters']['minPrice']=10000
        result=ev.validated_predicates(m,BASE+'?q=청소기&in=불당동-2292&price=10000__25000',
                      '2292',True,True,ui_observation_status='OBSERVED_MATCH',expected=expected)
        self.assertTrue(result['approved'])

    def test_minimum_price_violation(self):
        expected={'keyword':'청소기','category':'생활가전','category_id':172,
                  'min_price_krw':10000,'max_price_krw':25000,'available_only':True}
        proof=ev.validated_predicates(model(price=9999,category=172,maximum=25000,minimum=10000),
              BASE+'?q=청소기&in=불당동-2292','2292',True,True,
              ui_observation_status='OBSERVED_MATCH',expected=expected)
        self.assertFalse(proof['approved']);self.assertEqual(proof['min_price_violations'],50)

    def test_include_sold_does_not_claim_only_available(self):
        expected={'keyword':'HDD','category':'디지털기기','category_id':1,
                  'min_price_krw':0,'max_price_krw':50000,'available_only':False}
        m=model(available=False);m['filters']['onlyOnSale']=False
        m['articles'][0]['isSoldOut']=True
        proof=ev.validated_predicates(m,BASE+'?q=HDD&in=불당동-2292', '2292',True,True,
                     ui_observation_status='OBSERVED_MATCH',expected=expected)
        self.assertTrue(proof['approved']);self.assertEqual(proof['sold_violations'],0)

    def test_backward_compatibility(self):
        proof=ev.validated_predicates(model(), BASE+'?q=HDD&in=불당동-2292','2292',True,True)
        self.assertTrue(proof['approved'])


class Gate(unittest.TestCase):
    def link(self,i):return f'https://www.daangn.com/kr/buy-sell/disk-{i:012d}/'

    def test_region_explicit_expected_id_and_legacy_reject(self):
        urls=[self.link(i) for i in range(50)]
        kwargs={'version':'4.6','run':'r','context':'ctx','sequence':'ctx',
                'step':1,'region':'target','phase':'cold_first','urls':urls,'dom':urls[:32],
                'verified':True,'collector':'document'}
        self.assertIsNone(old._record(**kwargs))
        r=old._record(**kwargs,expected_region_id='98765')
        self.assertEqual(r['expected_region_id'],'98765')
        self.assertTrue(r['valid'])

    def test_custom_regions_gate_independent_repeats(self):
        snapshots=[]
        for name,reg,seed in [('target_a','target',10),('control_a','control',100),
                              ('target_b','target',10),('control_b','control',100)]:
            urls=[self.link(seed+i) for i in range(50)]
            for i in (1,2):
                snapshots.append({'context':name,'step':i,'region':reg,
                   'phase':'cold_first' if i==1 else 'same_url_repeat','_urls':urls,
                   '_dom':urls[:30],'valid':True,'time':'2026-11-08T00:00:00Z'})
        g=ev.gate_run(snapshots,'v46_base',[],'CAPTURED_COMPLETE',
                      region_ids={'target':'98765','control':'67890'},keyword='청소기')
        self.assertFalse(g['run_level']['blocked'])
        self.assertEqual(sum(x['sample_level_allowed'] for x in g['decisions']),4)


class Publishing(unittest.TestCase):
    def args(self,out):
        return SimpleNamespace(keyword='러닝화',max_price=120000,min_price=0,
                               available_only=True,category_id=1,category_name='디지털기기',
                               regions={'target':{'label':'사당','id':'334','term':'사당제3동','slug':'사당제3동-334'},
                                        'control':{'label':'천안','id':'2292','term':'불당동','slug':'불당동-2292'}},
                               output_dir=Path(out))
    def test_incomplete_never_export(self):
        with TemporaryDirectory() as d:
            out=self.args(d);self.assertEqual(app.publish(out,[],'STOP_UNVERIFIED',[]),2)
            a=json.loads((Path(d)/'daangn_browser_v4_6_limited_accept.json').read_text(encoding='utf-8'))
            self.assertEqual(a['allowed_sample_count'],0)
            r=json.loads((Path(d)/'daangn_browser_v4_6_results.json').read_text(encoding='utf-8'))
            self.assertEqual(r['configuration']['keyword'],'러닝화')
            self.assertEqual(r['configuration']['region']['id'],'334')

    def test_no_target_export_on_incomplete_rerun(self):
        with TemporaryDirectory() as d:
            out=self.args(d);app.publish(out,[],'STOP_UNVERIFIED',[])
            app.publish(out,[],'STOP_ROBOTS_UNVERIFIED_OR_DISALLOWED',[])
            a=json.loads((Path(d)/'daangn_browser_v4_6_limited_accept.json').read_text(encoding='utf-8'))
            self.assertTrue(a['run_level_blocked']);self.assertEqual(a['samples'],[])

if __name__=='__main__':unittest.main()

class FullExport(unittest.TestCase):
    def run_data(self,args,server_proof=True):
        import daangn_v4_4_gate as gate
        contexts=[]
        for name,region in app.plans_for(args):
            rid=args.regions[region]['id']
            offset=100 if region=='target' else 700
            urls=[f'https://www.daangn.com/kr/buy-sell/drive-{offset+i:012d}/' for i in range(70)]
            m=model(rid=rid,price=args.max_price//2,category=args.category_id,maximum=args.max_price)
            m['articles']=[{'href':u,'price':args.max_price//2,'categoryId':args.category_id,'isSoldOut':False} for u in urls]
            if not server_proof:m['filters'].pop('maxPrice')
            url=(BASE+'?q='+args.keyword+'&in='+args.regions[region]['slug']+
                 '&category_id='+str(args.category_id)+'&only_on_sale=true&price=__'+str(args.max_price))
            proof=ev.validated_predicates(m,url,rid,True,True,ui_observation_status='OBSERVED_MATCH',
                    expected=app.expected_for(args),require_response_filters=True)
            stages=[]
            for ix in (1,2,3,4):
                stages.append({'id':f'v46_{"base" if ix<=2 else "filtered"}:{name}:{1 if ix%2 else 2}:{region}',
                 'context':name,'region':region,'step':1 if ix%2 else 2,
                 'phase':'cold_first' if ix%2 else 'same_url_repeat',
                 'time':'2026-11-08T00:00:00Z','valid':True,'count':70,
                 'set_sha256':gate.set_hash(gate.hashed_listing_ids(urls)),
                 'filter_evidence':proof if ix>2 else None,
                 '_urls':urls,'_dom':urls[:32]})
            contexts.append({'context':name,'region':region,
                'status':'CAPTURED_FOUR_STAGES' if server_proof else 'UNVERIFIED_FILTER_PROOF',
                'stages':stages,'ui':{'after':{'observation_status':'OBSERVED_MATCH'}},
                'error':None})
        return contexts

    def test_custom_profile_strict_export_target_only(self):
        with TemporaryDirectory() as d:
            args=Publishing().args(d)
            self.assertEqual(app.publish(args,self.run_data(args),'CAPTURED_COMPLETE',[]),0)
            accept=json.loads((Path(d)/'daangn_browser_v4_6_limited_accept.json').read_text(encoding='utf-8'))
            self.assertFalse(accept['run_level_blocked'])
            self.assertEqual(accept['allowed_sample_count'],2)
            self.assertTrue(all(x['region']=='사당' for x in accept['samples']))
            result=json.loads((Path(d)/'daangn_browser_v4_6_results.json').read_text(encoding='utf-8'))
            self.assertEqual(result['configuration']['keyword'],'러닝화')
            self.assertEqual(result['filtered_gate']['run'],'v46_filtered')
            self.assertEqual(result['filtered_gate']['input_version'],'4.6')

    def test_only_candidate_never_exports(self):
        with TemporaryDirectory() as d:
            args=Publishing().args(d)
            self.assertEqual(app.publish(args,self.run_data(args,False),'UNVERIFIED_FILTER_PROOF',[]),2)
            accept=json.loads((Path(d)/'daangn_browser_v4_6_limited_accept.json').read_text(encoding='utf-8'))
            self.assertTrue(accept['run_level_blocked'])
            self.assertEqual(accept['samples'],[])

    def test_response_price_field_but_category_only_url_unverified(self):
        x=Publishing().args('.')
        m=model('334',price=40000,category=1,maximum=120000)
        m['filters'].pop('categoryId')
        out=ev.validated_predicates(m,BASE+'?q=러닝화&in=사당제3동-334&category_id=1',
            '334',True,True,ui_observation_status='OBSERVED_MATCH',
            expected=app.expected_for(x),require_response_filters=True)
        self.assertFalse(out['approved']);self.assertEqual(out['status'],'UNVERIFIED_SERVER_FILTER_FIELDS')

class KeywordSanitization(unittest.TestCase):
    def test_search_terms_with_dot_and_plus_round_trip(self):
        from urllib.parse import urlencode
        for term in ('M.2 SSD','RTX 4060','USB-C + PD','3.5인치 HDD'):
            url=BASE+'?'+urlencode({'q':term,'in':'불당동-2292'})
            safe=ev.public_url(url)
            self.assertTrue(safe['valid'])
            self.assertEqual(safe['public_params']['q'],term)

    def test_secret_query_values_not_repeated(self):
        x=ev.public_url(BASE+'?q=HDD&cookie=CONFIDENTIAL&token=MORESECRET')
        self.assertNotIn('CONFIDENTIAL',json.dumps(x))
        self.assertNotIn('MORESECRET',json.dumps(x))

class ConfigurationTypes(unittest.TestCase):
    def test_reject_ambiguous_boolean_and_numeric_types(self):
        for cfg in ({'available_only':'false'},{'max_price':True},
                    {'min_price':'20000'},{'region':1234}):
            with TemporaryDirectory() as d:
                f=Path(d)/'bad.json';f.write_text(json.dumps(cfg),encoding='utf-8')
                with patch('sys.stderr'),self.assertRaises(SystemExit):
                    argv_args('--config',str(f))

    def test_reject_region_label_with_newline(self):
        with patch('sys.stderr'),self.assertRaises(SystemExit):
            argv_args('--region','sample\nleak','--region-slug','실제동-9999')
