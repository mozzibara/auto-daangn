# -*- coding: utf-8 -*-
import json,hashlib,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import daangn_v4_5_evidence as e
import daangn_browser_v4_5 as app

def link(i):return 'https://www.daangn.com/kr/buy-sell/drive-%012d/'%i

def model(reg='2292',filter_on=True):
    filters={'regionId':reg}
    if filter_on:filters.update({'categoryId':1,'maxPrice':50000,'onlyAvailable':True})
    return {'region_id':reg,'filter_region_id':reg,'filters':filters,
            'articles':[{'href':link(i),'price':40000,'categoryId':1,'isSoldOut':False} for i in range(70)]}

def proof(m=None,ui=True,response=True):
    m=m or model()
    return e.validated_predicates(m,'https://www.daangn.com/kr/search/buy-sell/?q=HDD&in=불당동-2292',
                                  '2292',ui,response)

class FilterEvidence(unittest.TestCase):
    def test_full_pass(self):self.assertTrue(proof()['approved'])
    def test_region_bad(self):
        m=model();m['region_id']='2333';self.assertEqual(proof(m)['status'],'QUARANTINED_REGION_MISMATCH')
    def test_only_url_missing_metadata(self):
        m=model(filter_on=False);self.assertEqual(proof(m)['status'],'UNVERIFIED_SERVER_FILTER_FIELDS')
    def test_bad_price(self):
        m=model();m['articles'][1]['price']=50001
        self.assertEqual(proof(m)['status'],'QUARANTINED_ITEM_FILTER_VIOLATION')
    def test_missing_price(self):
        m=model();m['articles'][1]['price']=None
        self.assertEqual(proof(m)['status'],'UNVERIFIED_ITEM_PRICE_MISSING')
    def test_sold(self):
        m=model();m['articles'][0]['isSoldOut']=True
        self.assertEqual(proof(m)['status'],'QUARANTINED_ITEM_FILTER_VIOLATION')
    def test_wrong_category(self):
        m=model();m['articles'][2]['categoryId']=172
        self.assertEqual(proof(m)['status'],'QUARANTINED_ITEM_FILTER_VIOLATION')
    def test_ui_mismatch(self):self.assertEqual(proof(ui=False)['status'],'UNVERIFIED_UI_NOT_PERSISTED')
    def test_route_missing(self):self.assertEqual(proof(response=False)['status'],'UNVERIFIED_RESPONSE_MISSING')
    def test_category_missing(self):
        m=model();m['filters'].pop('categoryId');self.assertEqual(proof(m)['status'],'UNVERIFIED_SERVER_FILTER_FIELDS')
    def test_availability_false(self):
        m=model();m['filters']['onlyAvailable']=False;self.assertEqual(proof(m)['status'],'UNVERIFIED_SERVER_FILTER_FIELDS')
    def test_price_parser(self):
        self.assertEqual(e.int_price('50,000원'),50000);self.assertEqual(e.int_price('나눔'),0)
        self.assertIsNone(e.int_price('제안'))
    def test_secret_query_discarded(self):
        d=e.public_url('https://www.daangn.com/kr/search/buy-sell/?q=HDD&in=불당동-2292&maxPrice=50000&auth_token=SECRET')
        self.assertTrue(d['valid']);self.assertNotIn('SECRET',json.dumps(d));self.assertEqual(d['public_params']['maxPrice'],'50000')
    def test_non_public_url_not_exported(self):
        self.assertFalse(e.public_url('https://other.com/search?q=HDD')['valid'])
    def test_private_filter_fields_discarded(self):
        self.assertNotIn('SECRET',json.dumps(e.public_filters({'categoryId':1,'authToken':'SECRET'})))
    def test_parse_route(self):
        n=model();raw=json.dumps({'data':{'search':{'buySellArticles':n['articles'],
              'searchRegion':{'id':2292},'currentFilters':n['filters']}}}).encode()
        p=e.extract_model(raw)
        self.assertEqual(p['region_id'],'2292');self.assertEqual(len(e.model_urls(p)),70)
    def test_bad_route(self):self.assertIsNone(e.extract_model(b'<html>'))
    def test_set_difference(self):
        x=e.compare([link(1),link(2)],[link(2),link(3)])
        self.assertEqual(x['common'],1);self.assertAlmostEqual(x['jaccard'],1/3,places=5)

class GateOutput(unittest.TestCase):
    def fixture(self):
        result=[]
        for n,r in app.PLANS:
            region_id='2292' if r=='cheonan' else '2333';seed=100 if r=='cheonan' else 600
            data=model(region_id)
            data['articles']=[{'href':link(seed+i),'price':20000,'categoryId':1,'isSoldOut':False} for i in range(70)]
            stages=[]
            for step in (1,2,3,4):
                urls=e.model_urls(data)
                phase='cold_first' if step%2 else 'same_url_repeat'
                sid=f'v45_{"base" if step<=2 else "filtered"}:{n}:{1 if step%2 else 2}:{r}'
                stages.append({'id':sid,'context':n,'region':r,'step':1 if step%2 else 2,
                   'phase':phase,'time':'2026-11-08Z','valid':True,'count':len(urls),
                   'set_sha256':hashlib.sha256(str(urls).encode()).hexdigest(),
                   'filter_evidence':e.validated_predicates(data,'https://www.daangn.com/kr/search/buy-sell/?q=HDD&in=xxx-'+region_id,
                                                 region_id,True,True) if step>2 else None,
                   '_urls':urls,'_dom':urls[:32]})
            result.append({'context':n,'region':r,'status':'CAPTURED_FOUR_STAGES','stages':stages,'ui':{},'error':None})
        return result
    def test_synthetic_approval_and_metadata(self):
        with TemporaryDirectory() as td:
            args=SimpleNamespace(keyword='HDD',output_dir=Path(td))
            self.assertEqual(app.publish(args,self.fixture(),'CAPTURED_COMPLETE',[]),0)
            a=json.loads((Path(td)/'daangn_browser_v4_5_limited_accept.json').read_text(encoding='utf-8'))
            r=json.loads((Path(td)/'daangn_browser_v4_5_results.json').read_text(encoding='utf-8'))
            self.assertFalse(r['run_level']['blocked'])
            self.assertEqual(len(a['samples']),2)
            self.assertTrue(all(s['region']=='cheonan' for s in a['samples']))
            self.assertEqual(len(a['samples'][0]['public_listing_urls']),70)
            self.assertNotIn('https://www.daangn.com/kr/buy-sell/',json.dumps(r))
    def test_failed_run_never_exports_urls(self):
        with TemporaryDirectory() as td:
            args=SimpleNamespace(keyword='HDD',output_dir=Path(td))
            self.assertEqual(app.publish(args,self.fixture(),'STOP_ACCESS_RESTRICTED',[]),2)
            a=json.loads((Path(td)/'daangn_browser_v4_5_limited_accept.json').read_text(encoding='utf-8'))
            self.assertTrue(a['run_level_blocked']);self.assertEqual(a['samples'],[])
    def test_missing_stages_blocks(self):
        with TemporaryDirectory() as td:
            args=SimpleNamespace(keyword='HDD',output_dir=Path(td))
            self.assertEqual(app.publish(args,[], 'STOP_INCOMPLETE', []),2)
            self.assertTrue(json.loads((Path(td)/'daangn_browser_v4_5_results.json').read_text(encoding='utf-8'))['run_level']['blocked'])

if __name__=='__main__':unittest.main()

class ExtraObservedFilterVariants(unittest.TestCase):
    def test_nested_filter_variants(self):
        x=model();x['filters']={'regionId':'2292','category':{'id':1},
           'priceRange':{'min':0,'max':50000},'onlyAvailable':True}
        self.assertEqual(proof(x)['status'],'FILTER_APPLIED_VERIFIED')
    def test_category_ids(self):
        x=model();x['filters']['categoryIds']=[1];x['filters'].pop('categoryId')
        self.assertEqual(proof(x)['status'],'FILTER_APPLIED_VERIFIED')
    def test_numeric_sold_flag(self):
        x=model();x['articles'][0]['isSoldOut']=1
        self.assertEqual(proof(x)['status'],'QUARANTINED_ITEM_FILTER_VIOLATION')
