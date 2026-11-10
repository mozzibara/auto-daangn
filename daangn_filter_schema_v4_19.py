# -*- coding: utf-8 -*-
"""v4.19: privacy-bounded structural audit of actual Route price-filter metadata.

The only input is the body of a first-party UI-induced Route response, already
bound by request parameters and SHA-256 in v4.18. Do not persist raw JSON,
URLs, item data, user-derived string values, or unknown raw property names.

Three separate concepts:
  raw currentFilters price field; extractor/allowlist mapping; and independent
  empirical price-response behavior. None alone authorizes listing export.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime,timezone
import json
import re
from pathlib import Path
import secrets

import daangn_v4_5_evidence as ev
import daangn_price_crossover_v4_18 as crossover

# Only finite, audited names may enter evidence; unrelated fields are counted,
# never copied. "price" can encode the frontend URL, not necessarily a backend cap.
PRICE_ALIASES=frozenset({
    'maxPrice','max_price','priceMax','price_to','priceTo',
    'priceRange','minPrice','min_price','priceMin','price_from','priceFrom',
    'price','maxAmount','maximumPrice','maximum_price','priceCap','priceFilter',
    'price_range','price_limit','priceLimit','price_limit_max',
    'maximumAmount','minAmount','minimumPrice','rangeMax','max',
})
EXPECTED_CURRENT_FILTER_KEYS=frozenset({
    'regionId','categoryId','categoryIds','category','category_id',
    'onlyOnSale','only_on_sale','onlyAvailable','availableOnly',
    'only_available','onSaleOnly','isSelling','onlySelling',
    'maxPrice','max_price','priceMax','priceTo','price_to','priceRange',
    'price','minPrice','min_price','priceMin','priceFrom','price_from',
    'maxAmount','maximumPrice','maximum_price','priceCap','priceFilter',
    'price_range','price_limit','priceLimit','price_limit_max',
    'maximumAmount','minAmount','minimumPrice','rangeMax'})
KNOWN_MAX=frozenset(ev.MAX)|{'maxAmount','maximumPrice','maximum_price','priceCap',
    'price_limit','priceLimit','price_limit_max','maximumAmount','rangeMax',
    'priceRange','price_range'}
ALLOWED_SOURCE={'CURRENT_FILTERS','CURRENT_FILTERS_NESTED',
                'LOADER_OTHER','ANCESTOR_OR_OTHER_LOADER'}
CAP_KEYS=40
MAX_NODES=450
MAX_DEPTH=8
MAX_OBS=25


def _safe_int(value):
    if type(value) is int and 0<=value<1_000_000_000:return value
    if isinstance(value,str) and re.fullmatch(r'[0-9]{1,9}',value):
        return int(value)
    return None


def _type_name(v):
    if v is None:return 'null'
    if type(v) is bool:return 'bool'
    if type(v) is int:return 'integer'
    if type(v) is float:return 'float'
    if isinstance(v,str):return 'string'
    if isinstance(v,dict):return 'object'
    if isinstance(v,list):return 'array'
    return 'other'


def _price_candidate(key,value,scope,expected):
    """Finite structural field record; never serialize raw string values."""
    if key not in PRICE_ALIASES:return None
    nested=(value.get('max') if key in ('priceRange','price_range') and
            isinstance(value,dict) else None)
    encoded=ev.parse_observed_max_only_price(value) if key=='price' else None
    amount=_safe_int(nested if nested is not None else value)
    kind='ENCODED_RANGE' if encoded is not None else 'NUMERIC' if amount is not None else _type_name(value).upper()
    return {'location':scope,
        'name':key,
        'type':_type_name(value),
        'value_kind':kind,
        'equals_requested_max':(amount==expected if amount is not None else
                                encoded==expected if encoded is not None else None),
        # Numeric value itself is not needed for this causal/schema audit.
        'nested_max_present':isinstance(value,dict) and 'max' in value,
        'nonempty':value is not None}


def inspect_payload(raw,model,requested_cap):
    """Inspect the original matched Route *in memory*, separate from extractor.

    The response's 'buySellArticles' array is a hard boundary: no item fields
    are traversed, even for nested objects. The selected loader is the same
    candidate ordering as extract_model(), and all evidence is allowlisted.
    """
    try:
        obj=json.loads(raw) if isinstance(raw,(bytes,str)) else raw
    except (ValueError,TypeError,UnicodeDecodeError):
        return {'status':'NON_JSON'}
    if not isinstance(obj,(dict,list)) or requested_cap not in (20000,50000,100000):
        return {'status':'UNSUPPORTED_INPUT'}
    loaders=[]
    stack=[(obj,0)]
    scanned=0
    while stack and scanned<MAX_NODES:
        node,depth=stack.pop()
        scanned+=1
        if depth>MAX_DEPTH:continue
        if isinstance(node,dict):
            if isinstance(node.get('buySellArticles'),list):
                loaders.append(node)
                # Do not descend into item arrays, ever.
                continue
            for k,v in list(node.items())[:60]:
                if k=='buySellArticles':continue
                if isinstance(v,(dict,list)) and not ev.SECRETS.search(str(k)):
                    stack.append((v,depth+1))
        elif isinstance(node,list):
            for child in node[:14]:
                if isinstance(child,(dict,list)):stack.append((child,depth+1))
    if not loaders:return {'status':'LOADER_NOT_FOUND',
        'nodes_inspected':min(scanned,MAX_NODES),
        'traversal_truncated':bool(stack)}
    loaders.sort(key=lambda x:(isinstance(x.get('searchRegion'),dict),
                                isinstance(x.get('currentFilters'),dict)),reverse=True)
    loader=loaders[0]
    raw_filters=loader.get('currentFilters')
    has_filters=isinstance(raw_filters,dict)
    fields=raw_filters if has_filters else {}
    allowed_keys=sorted(k for k in fields if isinstance(k,str) and
                        k in EXPECTED_CURRENT_FILTER_KEYS)[:CAP_KEYS]
    unknown_count=sum(not (isinstance(k,str) and k in EXPECTED_CURRENT_FILTER_KEYS)
                       for k in fields)
    records=[]
    def add(key,val,scope,parent=None):
        if key=='max' and parent not in ('priceRange','price_range','priceFilter','price'):
            return
        record=_price_candidate(key,val,scope,requested_cap)
        if record is not None and len(records)<MAX_OBS:records.append(record)
    # Parent filter fields: avoid scanning non-filter strings.
    for k,v in list(fields.items())[:90]:
        add(k,v,'CURRENT_FILTERS')
        if isinstance(v,dict):
            for nk,nv in list(v.items())[:20]:
                add(nk,nv,'CURRENT_FILTERS_NESTED',parent=k)
    # Loader siblings only: no article data; prevents stale wrapper ambiguity.
    for k,v in list(loader.items())[:90]:
        if k in ('buySellArticles','currentFilters'):continue
        add(k,v,'LOADER_OTHER')
        if isinstance(v,dict) and ('filter' in k.lower() or
            'price' in k.lower() or k.lower() in
            ('searchparams','searchoptions','queryparams','requestparams','query','search')):
            for nk,nv in list(v.items())[:20]:
                add(nk,nv,'LOADER_OTHER',parent=k)
    # Bounded wrapper scan outside the chosen loader: distinct from currentFilters.
    outer=[(obj,0)]
    seen=0
    while outer and seen<MAX_NODES and len(records)<MAX_OBS:
        node,depth=outer.pop()
        seen+=1
        if depth>MAX_DEPTH or node is loader:continue
        if isinstance(node,dict):
            if isinstance(node.get('buySellArticles'),list):
                continue
            for k,v in list(node.items())[:50]:
                if ev.SECRETS.search(str(k)):continue
                add(k,v,'ANCESTOR_OR_OTHER_LOADER')
                if isinstance(v,(dict,list)):outer.append((v,depth+1))
        elif isinstance(node,list):
            for v in node[:12]:
                if isinstance(v,(dict,list)):outer.append((v,depth+1))
    # Compare exact selected raw currentFilters against the deployed parser.
    raw_max=[record for record in records if
             record['location'] in ('CURRENT_FILTERS','CURRENT_FILTERS_NESTED')
             and record['name'] in KNOWN_MAX
             and record['equals_requested_max'] is True]
    parsed=(model or {}).get('filters') or {}
    f=ev.public_filters(parsed)
    encoded_raw=ev.parse_observed_max_only_price(fields.get('price'))
    encoded_model=ev.parse_observed_max_only_price(parsed.get('price'))
    encoded_echo_found=encoded_raw is not None
    encoded_echo_matches=(encoded_raw==requested_cap) if encoded_echo_found else None
    model_preserves_encoded_echo=bool(encoded_echo_found and encoded_model==encoded_raw)
    public_filters_preserves_price=('price' in f)
    parsed_price=[]
    for key in ev.MAX:
        if key in f and ev.int_price(f[key])==requested_cap:
            parsed_price.append(key)
    if isinstance(f.get('priceRange'),dict) and ev.int_price(
            f['priceRange'].get('max'))==requested_cap:
        parsed_price.append('priceRange.max')
    raw_price_any=any(r['location'] in ('CURRENT_FILTERS','CURRENT_FILTERS_NESTED')
                      for r in records)
    other_price_any=any(r['location'] in ('LOADER_OTHER','ANCESTOR_OR_OTHER_LOADER')
                        for r in records)
    raw_current_max=bool(raw_max)
    parser_conflict=raw_current_max and not parsed_price
    response_conflict=any(r['location'] in ('CURRENT_FILTERS','CURRENT_FILTERS_NESTED')
        and r['name'] in KNOWN_MAX and r['value_kind']=='NUMERIC' and
        r['equals_requested_max'] is False for r in records)
    if scanned>=MAX_NODES or seen>=MAX_NODES or len(records)>=MAX_OBS:
        verdict='INCONCLUSIVE_TRAVERSAL_LIMIT'
    elif not has_filters:
        verdict='CURRENT_FILTERS_OBJECT_MISSING'
    elif response_conflict:
        verdict='RAW_RESPONSE_MAX_CONFLICT'
    elif encoded_echo_found and not encoded_echo_matches:
        verdict='CURRENT_FILTERS_ENCODED_PRICE_ECHO_MISMATCH'
    elif parser_conflict:
        verdict='RAW_PRICE_CAP_PRESENT_BUT_PARSER_UNRECOGNIZED'
    elif raw_current_max and parsed_price:
        verdict='RAW_PRICE_CAP_PRESENT_AND_PARSER_RECOGNIZED'
    elif encoded_echo_found and not model_preserves_encoded_echo:
        verdict='CURRENT_FILTERS_ENCODED_PRICE_ECHO_DROPPED_BY_MODEL'
    elif encoded_echo_found and not public_filters_preserves_price:
        verdict='CURRENT_FILTERS_ENCODED_PRICE_ECHO_OMITTED_BY_ALLOWLIST'
    elif encoded_echo_found:
        verdict='CURRENT_FILTERS_ENCODED_PRICE_ECHO_PRESENT'
    elif raw_price_any:
        verdict='PRICE_LIKE_FIELD_PRESENT_BUT_MAX_NOT_CONFIRMED'
    elif other_price_any:
        verdict='PRICE_FIELD_OUTSIDE_CURRENT_FILTERS'
    else:
        verdict='RAW_CURRENT_FILTERS_MAX_FIELD_ABSENT'
    return {
       'status':'OBSERVED',
       'verdict':verdict,
       'loader_candidates':min(len(loaders),20),
       'current_filters_object_present':has_filters,
       'current_filters_key_count':min(len(fields),100),
       'current_filters_allowlisted_keys':allowed_keys,
       'current_filters_unmapped_key_count':min(unknown_count,100),
       'raw_current_filters_max_matches':len(raw_max),
       'raw_response_max_conflict':response_conflict,
       'raw_current_filters_price_encoded_echo_found':encoded_echo_found,
       'raw_current_filters_price_echo_matches_requested_cap':encoded_echo_matches,
       'extract_model_price_echo_preserved':model_preserves_encoded_echo,
       'public_filters_price_echo_preserved':public_filters_preserves_price,
       'parser_recognized_max_matches':len(parsed_price),
       'other_scope_price_like_found':other_price_any,
       'price_field_records':records,
       'nodes_inspected':min(scanned,MAX_NODES),
       'traversal_truncated':bool(stack) or bool(outer),
       'item_rows_not_inspected':True,
       'response_body_persisted':False}


def independent_evidence_grade(behavior,fields):
    """New advisory tier independent of historical FILTER_APPLIED_VERIFIED.

    Rank never modifies validated_predicates, item admission or listing export.
    """
    if behavior.get('status')=='STOP_ACCESS_RESTRICTION':
        tier='STOP_ACCESS_RESTRICTION'
    elif behavior.get('price_cap_violations'):
        tier='CONTRADICTED_BY_ITEM_PRICE'
    elif any(isinstance(x,dict) and x.get('verdict')=='RAW_RESPONSE_MAX_CONFLICT'
             for x in fields):
        tier='CONTRADICTED_BY_RESPONSE_METADATA'
    elif any(isinstance(x,dict) and
             x.get('verdict')=='CURRENT_FILTERS_ENCODED_PRICE_ECHO_MISMATCH'
             for x in fields):
        tier='CONTRADICTED_BY_RETURNED_PRICE_ECHO'
    elif not behavior.get('capture_complete') or len(fields)!=7 or any(
        not isinstance(x,dict) or x.get('status')!='OBSERVED' or
        x.get('verdict')=='INCONCLUSIVE_TRAVERSAL_LIMIT'
        for x in fields):
        tier='INSUFFICIENT_STRUCTURAL_EVIDENCE'
    elif (behavior.get('behavioral_server_price_cap_supported') is True and
          behavior.get('ui_all_caps_verified') is True and
          behavior.get('all_item_prices_known') is True and
          behavior.get('response_declares_max_price_cap_all_profiles') is True and
          all(x.get('verdict')=='RAW_PRICE_CAP_PRESENT_AND_PARSER_RECOGNIZED'
              for x in fields)):
        tier='SERVER_DECLARED_AND_BEHAVIORAL'
    elif (behavior.get('behavioral_server_price_cap_supported') is True and
          behavior.get('ui_all_caps_verified') is True and
          behavior.get('all_item_prices_known') is True):
        tier='BEHAVIORAL_ROUTE_CORROBORATED'
    elif (behavior.get('capture_complete') and
          behavior.get('ui_all_caps_verified') is True):
        tier='UI_AND_ROUTE_OBSERVED_NOT_CAUSALLY_ESTABLISHED'
    else:
        tier='INSUFFICIENT'
    return {
        'tier':tier,
        'behavioral_server_price_cap_supported':behavior.get(
            'behavioral_server_price_cap_supported') is True,
        'direct_response_max_cap_confirmed_all':behavior.get(
            'response_declares_max_price_cap_all_profiles') is True,
        'historical_filter_applied_verified_overridden':False,
        'old_listing_gate_modified':False,
        'listing_admission_approved':False,
        'strict_listing_approved_count':0,
        'backend_internal_implementation_proven':False,
        'full_marketplace_recall_proven':False}


def evaluate(observations):
    behavior=crossover.cross_comparison(observations)
    shapes=[x.get('v419_filter_structure') for x in observations]
    grade=independent_evidence_grade(behavior,shapes)
    profile_schemas=[{
       'context':row.get('context'),'profile':row.get('profile'),
       'max_price_krw':row.get('max_price_krw'),
       'status':(row.get('v419_filter_structure') or {}).get('status','NOT_OBSERVED'),
       'verdict':(row.get('v419_filter_structure') or {}).get('verdict'),
       'structure':row.get('v419_filter_structure'),
       'parser_response_price_field_confirmed':row.get('response_price_metadata') is True,
       'response_filter_status':row.get('response_filter_status')}
       for row in observations]
    verdicts=[x.get('verdict') or 'NOT_OBSERVED' for x in profile_schemas]
    summary={k:verdicts.count(k) for k in sorted(set(verdicts))}
    return {'version':'4.19',
        'crosscheck':behavior,
        'independent_evidence_grade':grade,
        'response_structure_summary':summary,
        'observations':profile_schemas,
        'strict_listing_acceptance':{'blocked':True,'approved_listings':[]},
        'design':{'target':'cheonan','control':'asan',
            'max_price_caps_krw':[20000,50000,100000],
            'response_body_sha_correlated':True,
            'per_item_fields_not_inspected':True,
            'raw_body_and_urls_stored':False}}


def report(doc):
    evl=doc['crosscheck']
    grade=doc['independent_evidence_grade']
    s=['# v4.19: Route currentFilters metadata structural diagnosis','',
       f"- Independent evidence tier: **{grade['tier']}**",
       f"- Crossover verdict: {evl['status']}",
       f"- Real UI and Route capture complete: {evl['capture_complete']}",
       f"- Behaviorally supported price-cap results: {evl['behavioral_server_price_cap_supported']}",
       f"- Direct response maximum field on all profiles: {evl['response_declares_max_price_cap_all_profiles']}",
       '- Legacy FILTER_APPLIED_VERIFIED and strict listing approval: UNCHANGED, 0 approved.',
       '', '| Context | Cap KRW | Raw currentFilters structure | Parser price field |',
       '|---|---:|---|---|']
    for row in doc['observations']:
        s.append('| '+' | '.join(map(str,[row.get('context'),row.get('max_price_krw'),
            row.get('verdict'),row.get('parser_response_price_field_confirmed')]))+' |')
    s+=['','## Interpretation','',
       '- Structural observations identify whether the original UI-correlated Route loader has an explicit maximum-price field in currentFilters or another safe loader scope.',
       '- Absence in this specific public Route is not proof that the backend ignores the user-selected maximum, and not proof that no other private internal metadata exists.',
       '- The new BEHAVIORAL_ROUTE_CORROBORATED tier is *advisory*, supported by independent repeated price-cap contrasts; it cannot replace required response metadata in the legacy strict listing gate.',
       '- No response bodies, uncontrolled keys, listing data, raw URLs, cookies or session identifiers are exported.',
       '- A positive behavioral tier does not establish the backend query implementation or full marketplace recall.','']
    return '\n'.join(s)


async def run(options):
    options.filter_structure_v419=True
    rows=[]
    salt=secrets.token_bytes(32)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=not options.headed)
            try:
                for name,region,profiles in crossover.DESIGN:
                    for key in profiles:
                        row=await crossover.capture(browser,name,region,key,salt,options)
                        rows.append(row)
                        print('v4.19',name,key,row.get('status'),
                              (row.get('v419_filter_structure') or {}).get('verdict'),
                              row.get('raw_route_rows'))
                        if row.get('status','').startswith('STOP_') or row.get('access_restricted'):
                            break
                        await asyncio.sleep(2)
                    if rows and (rows[-1].get('status','').startswith('STOP_') or
                                 rows[-1].get('access_restricted')):
                        break
            finally:
                await browser.close()
    except Exception as ex:
        rows.append({'context':'browser','status':'STOP_'+type(ex).__name__,
             'access_restricted':False,'_rows':{}})
    doc=evaluate(rows)
    options.output_dir.mkdir(parents=True,exist_ok=True)
    (options.output_dir/'v419_filter_schema_results.json').write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (options.output_dir/'v419_filter_schema_report.md').write_text(
        report(doc),encoding='utf-8')
    (options.output_dir/'v419_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if (doc['crosscheck']['capture_complete'] and
        doc['independent_evidence_grade']['tier'] not in (
        'STOP_ACCESS_RESTRICTION','CONTRADICTED_BY_ITEM_PRICE',
        'INSUFFICIENT_STRUCTURAL_EVIDENCE',
        'CONTRADICTED_BY_RESPONSE_METADATA',
        'CONTRADICTED_BY_RETURNED_PRICE_ECHO')) else 2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=Path('v419_output'))
    parser.add_argument('--headed',action='store_true')
    parser.add_argument('--timeout',type=int,default=25)
    parser.add_argument('--settle-ms',type=int,default=1600)
    options=parser.parse_args()
    options.output_dir=options.output_dir.resolve()
    options.timeout=max(15,min(45,options.timeout))
    options.settle_ms=max(800,min(3500,options.settle_ms))
    return asyncio.run(run(options))


if __name__=='__main__':
    raise SystemExit(main())
