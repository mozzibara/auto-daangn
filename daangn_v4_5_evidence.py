# -*- coding: utf-8 -*-
"""Bounded first-party search filter evidence. No network calls or credential storage."""
import re, json, hashlib
from collections import Counter
from urllib.parse import urlsplit,parse_qsl,urlunsplit,urlencode
import daangn_v4_1_core as core
import daangn_v4_4_gate as gate
import daangn_v4_4_1_gate as gate41

EXPECTED={'keyword':'HDD','category':'디지털기기','category_id':1,'max_price_krw':50000,'available_only':True}
CAT=('categoryId','category_id','category','categoryIds')
MAX=('maxPrice','max_price','priceMax','price_to','priceTo')
ON=('onlyAvailable','only_available','availableOnly','onlyOnSale','only_on_sale','onSaleOnly','isSelling','onlySelling')
SAFE_QUERY={'q','in','price',*CAT,*MAX,*ON,'minPrice','min_price','sort','order','sort_by','sortBy','order_by','ordering','status'}
SECRETS=re.compile(r'(?:token|auth|cookie|secret|session|csrf|jwt|password|api.?key)',re.I)


def parse_observed_max_only_price(value):
    """Parse only the maximum-only shape observed after entering 50000 in the public UI.

    This is evidence of a *front-end URL encoding*, not server-side enforcement.
    Never infer meaning for other syntaxes, duplicates, or values out of range.
    """
    if not isinstance(value,str):return None
    match=re.fullmatch(r'__([1-9][0-9]{0,8})',value)
    if not match:return None
    amount=int(match.group(1))
    return amount if amount<=999_999_999 else None


def public_url(url):
    try:
        u=urlsplit(url)
        if u.scheme!='https' or u.hostname!='www.daangn.com' or u.path!=core.SEARCH_PATH:return {'valid':False}
        pairs=parse_qsl(u.query,keep_blank_values=True)
        # The real site uses a query key named 'price'. In v4.5.1 it appeared
        # in observed_param_keys but was silently omitted from public_params.
        # Preserve only a tightly restricted, nonsecret numeric-range notation.
        def safe_pair(k,v):
            if k not in SAFE_QUERY or SECRETS.search(k):return False
            if k=='price':return bool(re.fullmatch(r'[0-9,.:~_\-/]{1,80}',v))
            if k=='q':return bool(re.fullmatch(r'[\w\uac00-\ud7a3\- .,#+()/]{1,80}',v))
            return bool(re.fullmatch(r'[\w\uac00-\ud7a3\- ,]{0,80}',v))
        price_ambiguous=sum(k=='price' for k,_ in pairs)>1
        clean=[(k,v[:80]) for k,v in pairs if safe_pair(k,v) and not (price_ambiguous and k=='price')]
        seen_keys=sorted({k for k,_ in pairs if
                re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,36}',k) and not SECRETS.search(k)})
        result={'valid':True,'url':urlunsplit(('https','www.daangn.com',u.path,urlencode(clean),'')),
                'public_params':dict(clean),'observed_param_keys':seen_keys}
        if 'price' in seen_keys:
            # v4.5.2 observed exactly price=__50000 after a MAX-only UI entry.
            # Retain uniqueness: duplicate query keys are ambiguous and cannot be proof.
            price_entries=[v for k,v in pairs if k=='price']
            unique=len(price_entries)==1
            safe_value=dict(clean).get('price') if unique else None
            observed=parse_observed_max_only_price(safe_value) if unique else None
            result['price_query_evidence']={
                'present':True,'safe_value':safe_value,'unique':unique,
                'format':'UI_OBSERVED_MAX_ONLY' if observed is not None else 'UNKNOWN_OR_AMBIGUOUS',
                'observed_max_price_krw':observed,
                'interpretation':'FRONTEND_MAX_ONLY_CANDIDATE_NOT_SERVER_PROOF' if observed is not None
                                 else 'UNVERIFIED_FORMAT'}
        return result
    except Exception:return {'valid':False}


def int_price(v):
    if isinstance(v,bool):return None
    if isinstance(v,(int,float)):return int(v) if 0<=v<10**9 else None
    if isinstance(v,str):
        if v.strip() in ('나눔','무료'):return 0
        m=re.fullmatch(r'\s*([0-9,]+)\s*(?:원)?\s*',v)
        if m:return int(m.group(1).replace(',',''))
    return None


def public_filters(filters):
    if not isinstance(filters,dict):return {}
    out={}
    for k,v in filters.items():
        if not isinstance(k,str) or SECRETS.search(k):continue
        if k in CAT+MAX+ON+('regionId','search','minPrice','min_price','priceRange'):
            if isinstance(v,(int,float,bool)):out[k]=v
            elif isinstance(v,str) and re.fullmatch(r'[\w\uac00-\ud7a3\- ,]{0,75}',v):out[k]=v
            elif isinstance(v,list) and k=='categoryIds' and len(v)<=6 and all(isinstance(x,int) for x in v):out[k]=v
            elif isinstance(v,dict) and k in ('category','priceRange'):
                out[k]={name:value for name,value in v.items() if name in ('id','min','max') and
                        isinstance(value,(int,float,str)) and len(str(value))<30}
    return out


def _field(fields,query,keys):
    for source, data in (('response',fields),('url',query)):
        for k in keys:
            if k in data:return data[k],source,k
    return None,None,None


def validated_predicates(model,url,region_id,ui_ok,transport,*,ui_observation_status=None,expected=None,require_response_filters=False):
    expected=EXPECTED if expected is None else expected
    maximum=int(expected['max_price_krw'])
    minimum=int(expected.get('min_price_krw',0))
    category_id=int(expected['category_id'])
    available_requested=bool(expected['available_only'])
    safe=public_url(url); f=public_filters((model or {}).get('filters'))
    if isinstance(f.get('category'),dict):f.setdefault('categoryId',f['category'].get('id'))
    if isinstance(f.get('priceRange'),dict):f.setdefault('maxPrice',f['priceRange'].get('max'))
    q=safe.get('public_params',{})
    c,cs,ck=_field(f,q,CAT);p,ps,pk=_field(f,q,MAX);a,ass,ak=_field(f,q,ON)
    if isinstance(c,dict):c=c.get('id')
    if p is None and isinstance(f.get('priceRange'),dict):
        p,ps,pk=f['priceRange'].get('max'),'response','priceRange.max'
    category_ok=str(c) in (str(category_id),str(expected['category'])) or c==[category_id]
    # URL format alone cannot prove that the backend applied this bound.
    price_ok=int_price(p)==maximum
    price_query=safe.get('price_query_evidence') or {}
    max_only_candidate=bool(price_query.get('unique') and
                            price_query.get('observed_max_price_krw')==maximum and minimum==0)
    available_on=a is True or a==1 or (isinstance(a,str) and a.lower() in ('true','1','on','selling','available'))
    available_ok=(available_on if available_requested else not available_on)
    mi,mis,mik=_field(f,q,('minPrice','min_price','priceMin','price_from','priceFrom'))
    minimum_ok=(minimum==0 or (mis=='response' and int_price(mi)==minimum))
    region_ok=bool(model and str(model.get('region_id'))==str(region_id) and
                   str(model.get('filter_region_id'))==str(region_id))
    articles=(model or {}).get('articles') or []
    unknown=0;price_bad=0;min_bad=0;category_bad=0;sold_bad=0
    for x in articles:
        if not isinstance(x,dict):continue
        pr=int_price(x.get('price'))
        if pr is None:unknown+=1
        elif pr>maximum:price_bad+=1
        elif pr<minimum:min_bad+=1
        cat=x.get('categoryId')
        if cat is not None and str(cat)!=str(category_id):category_bad+=1
        if available_requested and x.get('isSoldOut') in (True,1,'true','TRUE'):sold_bad+=1
    # Hard failures take precedence over UI observability so a missing toolbar
    # cannot hide an observed region mismatch or price/category/sold violation.
    conflicting_price=bool(max_only_candidate and ps=='response' and p is not None and not price_ok)
    if not transport: verdict='UNVERIFIED_RESPONSE_MISSING'
    elif not region_ok:verdict='QUARANTINED_REGION_MISMATCH'
    elif price_bad or min_bad or category_bad or sold_bad:verdict='QUARANTINED_ITEM_FILTER_VIOLATION'
    elif conflicting_price:verdict='UNVERIFIED_SERVER_PRICE_CONFLICT'
    elif ui_observation_status=='OBSERVED_MISMATCH':verdict='UNVERIFIED_UI_SELECTION_MISMATCH'
    elif ui_observation_status in ('NOT_OBSERVABLE','PARTIAL_OBSERVATION','ERROR'):
        verdict='UNVERIFIED_UI_NOT_OBSERVABLE'
    elif not ui_ok:verdict='UNVERIFIED_UI_NOT_PERSISTED'  # legacy caller compatibility
    elif not (category_ok and price_ok and minimum_ok and available_ok) or (require_response_filters and
             (cs!='response' or ps!='response' or (available_requested and ass!='response'))):
        verdict='UNVERIFIED_SERVER_FILTER_FIELDS'
    elif unknown or not articles:verdict='UNVERIFIED_ITEM_PRICE_MISSING'
    else:verdict='FILTER_APPLIED_VERIFIED'
    corroborated=bool(transport and region_ok and category_ok and available_ok and max_only_candidate
                      and articles and not (unknown or price_bad or min_bad or category_bad or sold_bad)
                      and not conflicting_price and ui_observation_status!='OBSERVED_MISMATCH')
    tier=('VERIFIED_SERVER_AND_UI' if verdict=='FILTER_APPLIED_VERIFIED' else
          'URL_ITEM_CORROBORATION_ONLY' if corroborated else
          'EXPLICIT_VIOLATION' if verdict.startswith('QUARANTINED') else 'INSUFFICIENT')
    return {'status':verdict,'approved':verdict=='FILTER_APPLIED_VERIFIED',
            'evidence_tier':tier,'conditional_url_item_consistency':corroborated,
            'ui_observation_status':ui_observation_status or ('OBSERVED_MATCH' if ui_ok else 'UNKNOWN'),
            'region_ok':region_ok,'ui_verified':bool(ui_ok),'transport_verified':bool(transport),
            'criteria':{'category':{'ok':category_ok,'source':cs,'field':ck},
                         'max_price':{'ok':price_ok,'source':ps,'field':pk,
                                      'frontend_max_only_candidate':max_only_candidate,
                                      'candidate_max_krw':price_query.get('observed_max_price_krw'),
                                      'server_metadata_confirmed':price_ok and ps=='response',
                                      'minimum_ok':minimum_ok,'minimum_server_confirmed':minimum_ok and minimum>0},
                         'available_only':{'ok':available_ok,'source':ass,'field':ak}},
            'price_unknown':unknown,'price_violations':price_bad,
            'min_price_violations':min_bad,'category_violations':category_bad,'sold_violations':sold_bad,
            'price_query_observed_but_not_interpreted':bool('price' in safe.get('observed_param_keys',[])
                and not price_ok),
            'response_filter_fields':f,'url':safe}


def extract_model(obj):
    if isinstance(obj,(bytes,str)):
        try:obj=json.loads(obj)
        except Exception:return None
    candidates=[]
    def walk(x,depth=0):
        if depth>7:return
        if isinstance(x,dict):
            if isinstance(x.get('buySellArticles'),list):candidates.append(x)
            for v in x.values():
                if isinstance(v,(dict,list)):walk(v,depth+1)
        elif isinstance(x,list):
            for v in x[:30]:walk(v,depth+1)
    walk(obj)
    if not candidates:return None
    candidates.sort(key=lambda x:(isinstance(x.get('searchRegion'),dict),isinstance(x.get('currentFilters'),dict)),reverse=True)
    x=candidates[0]; filt=x.get('currentFilters') or {};region=x.get('searchRegion') or {}
    return {'region_id':str(region.get('id')) if region.get('id') is not None else None,
            'filter_region_id':str(filt.get('regionId')) if filt.get('regionId') is not None else None,
            # Search-region display name is kept in the in-memory model only.
            # Public diagnostics may emit a fixed match enum, never the text.
            'search_region_name':region.get('name')[:90]
                if isinstance(region.get('name'),str) else None,
            'filters':filt,'articles':[{'href':r.get('href') or r.get('url') or '',
                'price':r.get('price'),'categoryId':r.get('categoryId',r.get('category_id')),
                'isSoldOut':r.get('isSoldOut',r.get('soldOut',r.get('isSold')))}
                for r in x['buySellArticles'][:core.MAX_ARTICLES] if isinstance(r,dict)]}


def model_urls(m):
    return sorted({u for x in (m or {}).get('articles',[]) if (u:=core.normalized_listing(x.get('href')) )})


def compare(left,right):
    a=set(gate.hashed_listing_ids(left));b=set(gate.hashed_listing_ids(right))
    return {'left':len(a),'right':len(b),'common':len(a&b),'added':len(b-a),'removed':len(a-b),
            'jaccard':round(len(a&b)/len(a|b),6) if a or b else None,
            'left_sha256':gate.set_hash(list(a)),'right_sha256':gate.set_hash(list(b))}


def gate_run(snapshots,name,known_bad,status,*,region_ids=None,keyword='HDD'):
    rec=[]
    for s in snapshots:
        rec.append(gate._record(version='4.5',run=name,context=s['context'],sequence=s['context'],
             step=s['step'],region=s['region'],phase=s['phase'],urls=s.get('_urls',[]),
             dom=s.get('_dom',[]),verified=s.get('valid',False),collector=s.get('collector','document'),
             timestamp=s.get('time'),expected_region_id=(region_ids or {}).get(s['region'])))
    r={'run':name,'version':'4.6' if region_ids else '4.5','keyword':keyword,'samples':[x for x in rec if x is not None]}
    return gate41.apply_consistent_gate(r,historical_signatures=known_bad,capture_status=status,mode='live')
