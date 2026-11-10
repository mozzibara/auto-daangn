# -*- coding: utf-8 -*-
"""v4.28 independent, bounded visible primary-item FOR_SALE UI witness.

This script NEVER uses JSON-LD, linked-card badges, CTA presence or text from
a description as positive sale evidence. No raw DOM/text/URLs are exported.
"""
from __future__ import annotations
import asyncio

VISIBLE_STATES=frozenset({'AVAILABLE','RESERVED','SOLD'})
PROBE_STATUSES=frozenset({'DIRECT_FOR_SALE_UI','DIRECT_OTHER_TRANSACTION_UI',
                          'AMBIGUOUS_DIRECT_UI','NO_DIRECT_FOR_SALE_UI',
                          'PRIMARY_NOT_VERIFIED','SCAN_INCOMPLETE'})

UI_JS=r"""() => {
  const MAX=3500;
  const nodes=document.querySelectorAll('body *');
  const primary=document.querySelector('main article')||document.querySelector('main');
  const out={
    scan_complete:nodes.length<=MAX,
    scanned_nodes:Math.min(nodes.length,MAX),
    primary_valid:false,
    primary_visible_positive_status:0,
    primary_visible_sold_status:0,
    primary_visible_reserved_status:0,
    primary_visible_unmarked_available_text:0,
    primary_hidden_positive_status:0,
    related_positive_status:0,
    other_scope_positive_status:0,
    primary_chat_cta:0,
    primary_purchase_cta:0,
    primary_price_offer_cta:0
  };
  if(!primary)return out;
  const norm=v=>typeof v==='string'?v.replace(/\s+/g,' ').trim().slice(0,80):'';
  const direct=e=>[...e.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE)
                   .map(n=>n.textContent||'').join(' ');
  const token=s=>{
    const t=norm(s);
    if(['판매중','판매 중','거래가능','거래 가능'].includes(t))return 'AVAILABLE';
    if(['판매완료','판매 완료','거래완료','거래 완료'].includes(t))return 'SOLD';
    if(['예약중','예약 중'].includes(t))return 'RESERVED';
    return null;
  };
  const visibility=e=>{
    if(e.closest('[aria-hidden="true"],[inert]'))return false;
    let a=e,h=0;
    while(a&&h++<24){
      const s=getComputedStyle(a);
      if(s.display==='none'||s.visibility==='hidden'||
         s.visibility==='collapse'||s.opacity==='0')return false;
      a=a.parentElement;
    }
    const b=e.getBoundingClientRect();
    return !!e.getClientRects().length&&b.width>0&&b.height>0;
  };
  const headings=[...primary.querySelectorAll('h1')].filter(visibility);
  out.primary_valid=visibility(primary)&&headings.length===1;
  const excluded=e=>!!e.closest(
    'aside,nav,header,footer,form,[data-testid*="recommend"],'+
    '[class*="recommend"],[data-testid*="related"],[class*="related"],'+
    '[class*="comment"],[data-testid*="comment"],[aria-label*="추천"]');
  const linked=e=>!!e.closest('a[href*="/kr/buy-sell/"]');
  const mark=e=>{
    const c=typeof e.className==='string'?e.className:'';
    const d=e.getAttribute('data-testid')||'';
    return e.getAttribute('role')==='status'||
      /status|sale-state|transaction-state|reservation/i.test(c+' '+d);
  };
  const inc=(key)=>{out[key]=Math.min(3500,out[key]+1);};
  for(const e of [...nodes].slice(0,MAX)){
    if(e.closest('script,style,noscript,template,svg'))continue;
    const value=token(direct(e))||token(e.getAttribute('aria-label'));
    if(value){
      if(linked(e)){
        if(value==='AVAILABLE')inc('related_positive_status');
        continue;
      }
      if(!primary.contains(e)||excluded(e)){
        if(value==='AVAILABLE')inc('other_scope_positive_status');
        continue;
      }
      if(!visibility(e)){
        if(value==='AVAILABLE')inc('primary_hidden_positive_status');
        continue;
      }
      if(!mark(e)){
        if(value==='AVAILABLE')inc('primary_visible_unmarked_available_text');
        continue;
      }
      if(value==='AVAILABLE')inc('primary_visible_positive_status');
      if(value==='SOLD')inc('primary_visible_sold_status');
      if(value==='RESERVED')inc('primary_visible_reserved_status');
      continue;
    }
    if(!primary.contains(e)||excluded(e)||linked(e)||!visibility(e))continue;
    if(!e.matches('button,a,[role="button"]'))continue;
    const label=norm(e.getAttribute('aria-label')||direct(e));
    // The CTA is purely contextual. It can appear on non-for-sale controls.
    if(['채팅하기','채팅','판매자와 채팅하기'].includes(label))inc('primary_chat_cta');
    if(['구매하기','바로 구매하기'].includes(label))inc('primary_purchase_cta');
    if(['가격 제안하기','가격제안하기'].includes(label))inc('primary_price_offer_cta');
  }
  return out;
}""".strip()

COUNTERS=(
    'scanned_nodes','primary_visible_positive_status',
    'primary_visible_sold_status','primary_visible_reserved_status',
    'primary_visible_unmarked_available_text','primary_hidden_positive_status',
    'related_positive_status','other_scope_positive_status',
    'primary_chat_cta','primary_purchase_cta','primary_price_offer_cta')


def sanitize(raw):
    """Only finite integers/flags; reject arbitrary DOM values and URLs."""
    if not isinstance(raw,dict):return {'status':'PRIMARY_NOT_VERIFIED'}
    safe={k:(raw.get(k) if type(raw.get(k)) is int and 0<=raw[k]<=3500
             else None) for k in COUNTERS}
    valid=raw.get('primary_valid') is True
    complete=raw.get('scan_complete') is True
    pos=safe.get('primary_visible_positive_status') or 0
    neg=(safe.get('primary_visible_sold_status') or 0)+(
        safe.get('primary_visible_reserved_status') or 0)
    if not valid:status='PRIMARY_NOT_VERIFIED'
    elif not complete or any(safe[k] is None for k in COUNTERS):
        status='SCAN_INCOMPLETE'
    elif pos and neg:status='AMBIGUOUS_DIRECT_UI'
    elif pos:status='DIRECT_FOR_SALE_UI'
    elif neg:status='DIRECT_OTHER_TRANSACTION_UI'
    else:status='NO_DIRECT_FOR_SALE_UI'
    return {'status':status,'scan_complete':complete,'primary_valid':valid,
            'explicit_positive_proof':status=='DIRECT_FOR_SALE_UI',
            'ctas_are_transaction_proof':False,
            'jsonld_is_transaction_proof':False,
            **safe}


async def probe(page):
    try:
        raw=await asyncio.wait_for(page.evaluate(UI_JS),timeout=7)
        return sanitize(raw)
    except Exception as exc:
        return {'status':'PRIMARY_NOT_VERIFIED',
                'exception_type':type(exc).__name__,
                'explicit_positive_proof':False,
                'ctas_are_transaction_proof':False,
                'jsonld_is_transaction_proof':False}
