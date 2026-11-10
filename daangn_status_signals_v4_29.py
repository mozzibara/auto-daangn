# -*- coding: utf-8 -*-
"""v4.29 bounded public DOM/schema signal inventory for one exact-identity item.

All evidence comes from the already robots-approved, publicly rendered page.
Never read hydration stores, internal APIs, cookies, auth, seller text or links.
An exact-product Offer.availability is STOCK evidence, not transaction truth.
Uncalibrated transaction-like attributes are CANDIDATES, not FOR_SALE proof.
"""
from __future__ import annotations

import asyncio

SCHEMA_STOCK_KINDS=frozenset({
    'IN_STOCK','OUT_OF_STOCK','SOLD_OUT','RESERVED','PRE_ORDER',
    'PRE_SALE','OTHER','NOT_OBSERVABLE','AMBIGUOUS'})
STATUS_KINDS=frozenset({'FOR_SALE','RESERVED','SOLD','NOT_OBSERVABLE','AMBIGUOUS'})
SURVEY_STATUSES=frozenset({'SURVEY_COMPLETE','PRIMARY_NOT_VERIFIED',
                           'SCAN_INCOMPLETE','SCHEMA_AMBIGUOUS',
                           'PROBE_ERROR'})
COUNT_FIELDS=(
    'body_nodes_scanned','product_exact_url_match_count',
    'explicit_trade_attribute_nodes','explicit_trade_attribute_positive',
    'explicit_trade_attribute_sold','explicit_trade_attribute_reserved',
    'explicit_trade_attribute_ambiguous','unrecognized_trade_attribute_nodes',
    'exact_product_additional_trade_properties',
    'exact_product_additional_trade_positive',
    'exact_product_additional_trade_sold',
    'exact_product_additional_trade_reserved',
    'page_meta_trade_properties','page_meta_trade_positive',
    'page_meta_trade_sold','page_meta_trade_reserved',
    'primary_visible_transaction_text',
    'primary_visible_for_sale_text','primary_visible_sold_text',
    'primary_visible_reserved_text',
    'primary_hidden_transaction_text','linked_other_listing_transaction_text',
    'primary_transaction_semantic_nodes','primary_transaction_attribute_nodes',
    'current_primary_button_status_text_nodes',
    'microdata_stock_nodes'
)

SURVEY_JS=r"""() => {
  const LIMIT=3500;
  const nodes=[...document.querySelectorAll('body *')];
  const primary=document.querySelector('main article')||document.querySelector('main');
  const out={
    scan_complete:nodes.length<=LIMIT,body_nodes_scanned:Math.min(nodes.length,LIMIT),
    primary_valid:false,product_exact_url_match_count:0,
    offer_availability:'NOT_OBSERVABLE',exact_product_trade_status:'NOT_OBSERVABLE',
    trade_attribute_status:'NOT_OBSERVABLE',page_meta_trade_status:'NOT_OBSERVABLE'
  };
  const counters=[
    'explicit_trade_attribute_nodes','explicit_trade_attribute_positive',
    'explicit_trade_attribute_sold','explicit_trade_attribute_reserved',
    'explicit_trade_attribute_ambiguous','unrecognized_trade_attribute_nodes',
    'exact_product_additional_trade_properties','exact_product_additional_trade_positive',
    'exact_product_additional_trade_sold','exact_product_additional_trade_reserved',
    'page_meta_trade_properties','page_meta_trade_positive',
    'page_meta_trade_sold','page_meta_trade_reserved',
    'primary_visible_transaction_text','primary_visible_for_sale_text',
    'primary_visible_sold_text','primary_visible_reserved_text',
    'primary_hidden_transaction_text','linked_other_listing_transaction_text',
    'primary_transaction_semantic_nodes','primary_transaction_attribute_nodes',
    'current_primary_button_status_text_nodes','microdata_stock_nodes'
  ];
  for(const k of counters)out[k]=0;
  const inc=k=>{out[k]=Math.min(3500,out[k]+1);};
  const normalize=v=>typeof v==='string'?v.replace(/\s+/g,' ').trim().slice(0,80):'';
  const state=v=>{
    const x=normalize(v).toLowerCase().replace(/[\s_-]/g,'');
    if(['판매중','거래가능','forsale','onsale','selling','available'].includes(x))
      return 'FOR_SALE';
    if(['예약중','reserved','reservationpending'].includes(x))return 'RESERVED';
    if(['판매완료','거래완료','sold','completed'].includes(x))return 'SOLD';
    return 'NOT_OBSERVABLE';
  };
  const finiteStock={
    InStock:'IN_STOCK',OutOfStock:'OUT_OF_STOCK',SoldOut:'SOLD_OUT',
    Reserved:'RESERVED',PreOrder:'PRE_ORDER',PreSale:'PRE_SALE'
  };
  const visible=e=>{
    if(!e||e.closest('[aria-hidden="true"],[inert]'))return false;
    let v=e,n=0;
    while(v&&n++<24){
      const t=getComputedStyle(v);
      if(t.display==='none'||t.visibility==='hidden'||t.visibility==='collapse'
         ||t.opacity==='0')return false;
      v=v.parentElement;
    }
    const b=e.getBoundingClientRect();
    return e.getClientRects().length>0&&b.width>0&&b.height>0;
  };
  const isLinked=e=>!!e.closest('a[href*="/kr/buy-sell/"]');
  const excluded=e=>!!e.closest(
    'header,nav,footer,aside,form,dialog,[role="dialog"],'+
    '[data-testid*="recommend"],[class*="recommend"],'+
    '[data-testid*="related"],[class*="related"],'+
    '[aria-label*="추천"],[class*="comment"],[data-testid*="comment"]'
  );
  const primaryScope=e=>primary&&primary.contains(e)&&!isLinked(e)&&!excluded(e);
  const direct=e=>[...e.childNodes].filter(n=>n.nodeType===3)
    .map(n=>n.textContent||'').join(' ');
  if(primary)out.primary_valid=visible(primary)&&
    [...primary.querySelectorAll('h1')].filter(visible).length===1;

  for(const el of nodes.slice(0,LIMIT)){
    if(el.closest('script,style,noscript,template,svg'))continue;
    const marker=state(direct(el))==='NOT_OBSERVABLE'
      ?state(el.getAttribute('aria-label')):state(direct(el));
    if(marker!=='NOT_OBSERVABLE'){
      if(isLinked(el)){inc('linked_other_listing_transaction_text');continue;}
      if(!primaryScope(el))continue;
      if(!visible(el)){inc('primary_hidden_transaction_text');continue;}
      if(el.matches('button,[role="button"],select,option')){
        inc('current_primary_button_status_text_nodes');
        continue;
      }
      inc('primary_visible_transaction_text');
      if(marker==='FOR_SALE')inc('primary_visible_for_sale_text');
      if(marker==='SOLD')inc('primary_visible_sold_text');
      if(marker==='RESERVED')inc('primary_visible_reserved_text');
    }
    if(!primaryScope(el))continue;
    const cls=typeof el.className==='string'?el.className:'';
    const testid=el.getAttribute('data-testid')||'';
    if(/(?:transaction|sale|listing)[- _]?(?:status|state)|(?:transaction|sale)-status/i
        .test(cls+' '+testid)||el.getAttribute('role')==='status')
      inc('primary_transaction_semantic_nodes');
    const attrs=['data-transaction-status','data-trade-status',
        'data-sale-status','data-listing-status'];
    let match=false;
    for(const attr of attrs){
      if(!el.hasAttribute(attr))continue;
      match=true;inc('explicit_trade_attribute_nodes');
      const v=state(el.getAttribute(attr));
      if(v==='FOR_SALE')inc('explicit_trade_attribute_positive');
      else if(v==='SOLD')inc('explicit_trade_attribute_sold');
      else if(v==='RESERVED')inc('explicit_trade_attribute_reserved');
      else inc('unrecognized_trade_attribute_nodes');
    }
    if(match)inc('primary_transaction_attribute_nodes');
    if(el.hasAttribute('itemprop')&&
       el.getAttribute('itemprop')==='availability')
      inc('microdata_stock_nodes');
  }

  const metaNodes=[...document.querySelectorAll('meta[property],meta[name]')].slice(0,200);
  for(const el of metaNodes){
    const name=(el.getAttribute('property')||el.getAttribute('name')||'').toLowerCase();
    if(!['product:transaction_status','article:transaction_status',
          'product:trade_status','article:sale_status'].includes(name))continue;
    inc('page_meta_trade_properties');
    const v=state(el.getAttribute('content'));
    if(v==='FOR_SALE')inc('page_meta_trade_positive');
    if(v==='SOLD')inc('page_meta_trade_sold');
    if(v==='RESERVED')inc('page_meta_trade_reserved');
  }
  const sameListing=s=>{
    if(typeof s!=='string'||s.length>2048)return false;
    try{
      const p=new URL(s,location.href);
      return p.origin===location.origin&&
        p.pathname.replace(/\/?$/,'/')===location.pathname.replace(/\/?$/,'/');
    }catch{return false;}
  };
  const products=[];
  const walk=(x,depth=0)=>{
    if(!x||depth>5||products.length>12)return;
    if(Array.isArray(x)){x.slice(0,16).forEach(v=>walk(v,depth+1));return;}
    if(typeof x!=='object')return;
    const types=Array.isArray(x['@type'])?x['@type']:[x['@type']];
    if(types.some(y=>typeof y==='string'&&y.split('/').pop()==='Product')){
      const ref=x.url||x.mainEntityOfPage;
      const uri=typeof ref==='string'?ref:ref&&typeof ref==='object'?ref['@id']:null;
      if(sameListing(uri))products.push(x);
    }
    if(x['@graph'])walk(x['@graph'],depth+1);
  };
  for(const script of [...document.querySelectorAll('script[type="application/ld+json"]')].slice(0,8)){
    const raw=script.textContent||'';
    if(raw.length>30000)continue;
    try{walk(JSON.parse(raw));}catch{}
  }
  out.product_exact_url_match_count=Math.min(20,products.length);
  if(products.length>1){
    out.offer_availability='AMBIGUOUS';
    out.exact_product_trade_status='AMBIGUOUS';
  }
  if(products.length===1){
    const product=products[0];
    let offers=product.offers;
    if(Array.isArray(offers))offers=offers.length===1?offers[0]:null;
    const uri=offers&&typeof offers==='object'?offers.availability:null;
    if(typeof uri==='string'){
      const suffix=uri.split('/').pop();
      out.offer_availability=finiteStock[suffix]||'OTHER';
    }
    const properties=Array.isArray(product.additionalProperty)
      ?product.additionalProperty:[product.additionalProperty];
    for(const prop of properties.slice(0,16)){
      if(!prop||typeof prop!=='object')continue;
      const name=normalize(prop.name||prop.propertyID).toLowerCase()
        .replace(/[\s_-]/g,'');
      if(!['transactionstatus','tradestatus','salestatus','listingstatus']
          .includes(name))continue;
      inc('exact_product_additional_trade_properties');
      const v=state(prop.value);
      if(v==='FOR_SALE')inc('exact_product_additional_trade_positive');
      if(v==='SOLD')inc('exact_product_additional_trade_sold');
      if(v==='RESERVED')inc('exact_product_additional_trade_reserved');
    }
  }
  const choose=(pos,sold,res)=>{
    const arr=[pos?'FOR_SALE':null,sold?'SOLD':null,res?'RESERVED':null].filter(Boolean);
    return arr.length===1?arr[0]:arr.length>1?'AMBIGUOUS':'NOT_OBSERVABLE';
  };
  out.trade_attribute_status=choose(out.explicit_trade_attribute_positive,
      out.explicit_trade_attribute_sold,out.explicit_trade_attribute_reserved);
  out.exact_product_trade_status=products.length>1?'AMBIGUOUS':choose(
      out.exact_product_additional_trade_positive,
      out.exact_product_additional_trade_sold,
      out.exact_product_additional_trade_reserved);
  out.page_meta_trade_status=choose(out.page_meta_trade_positive,
      out.page_meta_trade_sold,out.page_meta_trade_reserved);
  return out;
}""".strip()


def sanitize(raw):
    """Fail-closed privacy allowlist; do not treat research candidates as proof."""
    if not isinstance(raw,dict):
        return {'status':'PROBE_ERROR','direct_for_sale_proven':False}
    safe={}
    for key in COUNT_FIELDS:
        value=raw.get(key)
        safe[key]=value if type(value) is int and 0<=value<=3500 else None
    fields=('offer_availability','exact_product_trade_status',
            'trade_attribute_status','page_meta_trade_status')
    for name in fields:
        valid=SCHEMA_STOCK_KINDS if name=='offer_availability' else STATUS_KINDS
        v=raw.get(name)
        safe[name]=v if isinstance(v,str) and v in valid else 'NOT_OBSERVABLE'
    safe['scan_complete']=raw.get('scan_complete') is True
    safe['primary_valid']=raw.get('primary_valid') is True
    if not safe['primary_valid']:
        status='PRIMARY_NOT_VERIFIED'
    elif not safe['scan_complete'] or any(safe[k] is None for k in COUNT_FIELDS):
        status='SCAN_INCOMPLETE'
    elif safe['product_exact_url_match_count']>1 or any(
        safe[k]=='AMBIGUOUS' for k in fields):
        status='SCHEMA_AMBIGUOUS'
    else:
        status='SURVEY_COMPLETE'
    return {'status':status,'direct_for_sale_proven':False,
            'machine_trade_field_calibrated':False,
            'stock_metadata_is_transaction_proof':False,
            'listing_scoped_attribute_is_transaction_proof':False,
            'confirmed_listing_ui_only':False,
            **safe}


async def probe(page):
    try:
        raw=await asyncio.wait_for(page.evaluate(SURVEY_JS),timeout=7)
        return sanitize(raw)
    except Exception as exc:
        return {'status':'PROBE_ERROR',
                'error_type':type(exc).__name__[:64],
                'direct_for_sale_proven':False,
                'machine_trade_field_calibrated':False,
                'stock_metadata_is_transaction_proof':False}
