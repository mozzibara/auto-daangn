# -*- coding: utf-8 -*-
"""v4.17 independent, read-only, UI-visible selected-filter state verifier.

Do not treat URL parameters, stale Remix loaderData or server-filter hints as
observed controls. Read only native input/ARIA state on a genuine public filter
panel opened by the site's visible button. Fail closed on duplicates, hidden
labels, missing fields and unrecognized UI. No raw DOM, text, IDs or URLs saved.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
from pathlib import Path
from datetime import datetime, timezone

import daangn_v4_5_evidence as evidence
import daangn_full_route_v4_14 as full
import daangn_browser_v4_6 as browser

PANEL_JS=r"""(expected) => {
  const visible=el=>{
    if(!el?.getBoundingClientRect)return false;
    const b=el.getBoundingClientRect(),s=getComputedStyle(el);
    return b.width>0&&b.height>0&&el.getClientRects().length>0&&
           s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0';
  };
  const clean=s=>String(s||'').replace(/\s+/g,' ').trim().slice(0,90);
  const panelCandidates=[...document.querySelectorAll(
    '[role="dialog"],[aria-modal="true"],[class*="bottom-sheet__content"],[class*="drawer__content"],[data-state="open"]')]
    .filter(visible);
  const score=el=>{
    const s=clean((el.innerText||'').slice(0,3000));
    return ['필터','가격','카테고리','거래 가능','동네'].reduce((n,k)=>n+(s.includes(k)?1:0),0);
  };
  panelCandidates.sort((a,b)=>score(b)-score(a));
  const panel=panelCandidates.length&&score(panelCandidates[0])?panelCandidates[0]:null;
  const result={
    panel_found:!!panel,
    panel_visible:!!panel&&visible(panel),
    panel_candidates:Math.min(20,panelCandidates.length),
    controls:{label_count:0,radio_count:0,checkbox_count:0,
      textbox_count:0,visible_textboxes:0},
    category:{state:'NOT_OBSERVED',source:'NONE',matches:0},
    availability:{state:'NOT_OBSERVED',source:'NONE',matches:0},
    maximum:{state:'NOT_OBSERVED',source:'NONE',matches:0,value_krw:null}
  };
  if(!panel)return result;
  const all=[...panel.querySelectorAll('label,[role="radio"],[role="checkbox"],[role="switch"]')];
  const labelText=el=>clean(el.innerText||el.getAttribute('aria-label')||'');
  const candi=el=>({
    el,text:labelText(el),
    tag:el.tagName,
    role:el.getAttribute('role')||'',
    visible:visible(el)
  });
  const observed=all.map(candi).filter(x=>x.visible);
  result.controls.label_count=Math.min(100,observed.filter(x=>x.tag==='LABEL').length);
  result.controls.radio_count=Math.min(100,panel.querySelectorAll('input[type="radio"],[role="radio"]').length);
  result.controls.checkbox_count=Math.min(100,panel.querySelectorAll('input[type="checkbox"],[role="checkbox"],[role="switch"]').length);
  const inputs=[...panel.querySelectorAll('input')].filter(e=>
    ['text','number','search','tel',''].includes((e.getAttribute('type')||'text').toLowerCase()));
  result.controls.textbox_count=Math.min(100,inputs.length);
  result.controls.visible_textboxes=Math.min(100,inputs.filter(visible).length);
  function relatedControl(e){
    let found=null;
    if(e.matches('input[type="checkbox"],input[type="radio"],[role="checkbox"],[role="radio"],[role="switch"]'))
      found=e;
    if(!found)found=e.querySelector('input[type="checkbox"],input[type="radio"],[role="checkbox"],[role="radio"],[role="switch"]');
    if(!found&&e.tagName==='LABEL'&&e.htmlFor){
      const linked=document.getElementById(e.htmlFor);
      if(linked&&panel.contains(linked))found=linked;
    }
    if(!found)return {state:'NOT_OBSERVED',source:'NONE'};
    const type=(found.getAttribute('type')||'').toLowerCase();
    if(found.tagName==='INPUT'&&['checkbox','radio'].includes(type))
      return {state:found.checked?'CHECKED':'UNCHECKED',source:'NATIVE_CHECKED'};
    const aria=found.getAttribute('aria-checked');
    if(aria==='true'||aria==='false')
      return {state:aria==='true'?'CHECKED':'UNCHECKED',source:'ARIA_CHECKED'};
    return {state:'NOT_OBSERVED',source:'NONE'};
  }
  function exactOrCount(text,word){
    return text===word||text.startsWith(word+' ')||text.startsWith(word+'(');
  }
  function uniqueState(name,matcher){
    const matches=observed.filter(matcher);
    const out={state:'NOT_OBSERVED',source:'NONE',matches:Math.min(20,matches.length)};
    if(matches.length!==1){
      out.state=matches.length?'AMBIGUOUS':'NOT_OBSERVED';
      return out;
    }
    const val=relatedControl(matches[0].el);
    out.state=val.state;out.source=val.source;
    return out;
  }
  result.category=uniqueState('category',x=>exactOrCount(x.text,expected.category));
  result.availability=uniqueState('available',x=>exactOrCount(x.text,'거래 가능만 보기'));
  const maxSignal=/(?:최대|이하|상한|max(?:imum)?)/i;
  const minSignal=/(?:최소|이상|하한|min(?:imum)?)/i;
  function priceEvidence(el){
    if(!visible(el))return null;
    const sources=[
      ['PLACEHOLDER',clean(el.getAttribute('placeholder'))],
      ['ARIA_LABEL',clean(el.getAttribute('aria-label'))],
      ['TITLE',clean(el.getAttribute('title'))],
      ['WRAPPING_LABEL',el.closest('label')?clean(el.closest('label').innerText):'']
    ];
    const labelId=el.getAttribute('id');
    if(labelId){
      const linked=[...panel.querySelectorAll('label[for]')]
        .filter(x=>x.getAttribute('for')===labelId&&visible(x));
      if(linked.length===1)sources.push(['ASSOCIATED_LABEL',clean(linked[0].innerText)]);
    }
    const positive=sources.filter(([source,name])=>maxSignal.test(name)&&!minSignal.test(name));
    if(positive.length!==1 && positive.length>1){
      // Multiple independently agreeing max labels are still one input;
      // choose the best direct semantic source, not an unverified DOM rank.
      return {element:el,provenance:positive[0][0]};
    }
    return positive.length===1?{element:el,provenance:positive[0][0]}:null;
  }
  const prices=inputs.map(priceEvidence).filter(Boolean);
  result.maximum.matches=Math.min(20,prices.length);
  if(prices.length===1){
    const raw=clean(prices[0].element.value);
    const matched=/^([0-9,]+)(?:\s*원)?$/.exec(raw);
    result.maximum.match_provenance=prices[0].provenance;
    if(matched){
      const n=Number(matched[1].replace(/,/g,''));
      if(Number.isSafeInteger(n)&&n>=0&&n<1e9){
        result.maximum={state:'OBSERVED',source:'VISIBLE_INPUT',matches:1,
                        value_krw:n,match_provenance:prices[0].provenance};
      }
    }
  }else if(prices.length>1){
    result.maximum.state='AMBIGUOUS';
  }
  return result;
}""".strip()

STATES={'NOT_OBSERVED','CHECKED','UNCHECKED','AMBIGUOUS','OBSERVED'}
SOURCES={'NONE','NATIVE_CHECKED','ARIA_CHECKED','VISIBLE_INPUT'}


def sanitize(raw):
    """No untrusted property names, strings or raw input values can enter artifacts."""
    if not isinstance(raw,dict):
        return {'status':'UNVERIFIED'}
    counts=raw.get('controls') if isinstance(raw.get('controls'),dict) else {}
    def bounded(v,cap=100):
        return v if type(v) is int and 0<=v<=cap else None
    def item(key):
        inp=raw.get(key) if isinstance(raw.get(key),dict) else {}
        source=inp.get('source')
        state=inp.get('state')
        p={'state':state if state in STATES else 'NOT_OBSERVED',
           'source':source if source in SOURCES else 'NONE',
           'matches':bounded(inp.get('matches'),20)}
        if key=='maximum':
            n=inp.get('value_krw')
            p['value_krw']=n if type(n) is int and 0<=n<1_000_000_000 else None
            source_tag=inp.get('match_provenance')
            p['match_provenance']=source_tag if source_tag in (
                'PLACEHOLDER','ARIA_LABEL','TITLE','WRAPPING_LABEL','ASSOCIATED_LABEL') else 'NONE'
        return p
    return {'status':'OBSERVED',
      'panel_found':raw.get('panel_found') is True,
      'panel_visible':raw.get('panel_visible') is True,
      'panel_candidates':bounded(raw.get('panel_candidates'),20),
      'controls':{k:bounded(counts.get(k)) for k in
        ('label_count','radio_count','checkbox_count','textbox_count','visible_textboxes')},
      'category':item('category'),
      'availability':item('availability'),
      'maximum':item('maximum')}


def interpret(data,expected_price=50000):
    if not isinstance(data,dict) or data.get('status')!='OBSERVED' or not data.get('panel_found'):
        return {'status':'NOT_OBSERVABLE','selected_state_complete':False,
                'category':None,'available':None,'maximum':None,'field_verdicts':{}}
    cat=data['category']['state']
    avail=data['availability']['state']
    price=data['maximum']['value_krw'] if data['maximum']['state']=='OBSERVED' else None
    complete=cat in ('CHECKED','UNCHECKED') and avail in ('CHECKED','UNCHECKED') and price is not None
    field_verdicts={
      'category':('MATCH' if cat=='CHECKED' else 'MISMATCH' if cat=='UNCHECKED' else 'UNVERIFIED'),
      'availability':('MATCH' if avail=='CHECKED' else 'MISMATCH' if avail=='UNCHECKED' else 'UNVERIFIED'),
      'maximum_price':('MATCH' if price==expected_price else 'MISMATCH' if price is not None else 'UNVERIFIED')}
    status=('OBSERVED_MATCH' if complete and all(v=='MATCH' for v in field_verdicts.values())
      else 'OBSERVED_MISMATCH' if complete else
      'PARTIAL_OBSERVATION' if any(v!='UNVERIFIED' for v in field_verdicts.values())
      else 'NOT_OBSERVABLE')
    return {'status':status,'selected_state_complete':complete,
      'category':cat=='CHECKED' if cat in ('CHECKED','UNCHECKED') else None,
      'available':avail=='CHECKED' if avail in ('CHECKED','UNCHECKED') else None,
      'maximum':price,'field_verdicts':field_verdicts}


async def observe(page,args):
    try:
        raw=await asyncio.wait_for(page.evaluate(PANEL_JS,{'category':args.category_name}),timeout=5)
        safe=sanitize(raw)
        return {'evidence':safe,'interpretation':interpret(safe,args.max_price)}
    except Exception as ex:
        return {'evidence':{'status':'ERROR_'+type(ex).__name__},
                'interpretation':{'status':'NOT_OBSERVABLE','selected_state_complete':False,
                                  'field_verdicts':{}}}


def assemble(rows,base):
    """Build an output from the unsanitized in-memory captures.

    v4.14's generic JSON omits ui_persistence by design; reloading that file
    would erase precisely the SPA/reload witnesses this experiment studies.
    Retain only explicit, already-sanitized diagnostic fields here.
    """
    complete=base.get('capture_complete') is True
    doc={'version':'4.17','utc_time':datetime.now(timezone.utc).isoformat(timespec='seconds'),
       'evaluation':{
         'status':'INCONCLUSIVE_UI_SELECTION_INCOMPLETE',
         'capture_complete':complete,
         'route_counts':base.get('route_article_counts'),
         'strict_listing_approved_count':0,
         'server_max_price_enforcement_proven':False},
       'contexts':[],
       'strict_listing_accept':{'blocked':True,'approved_listings':[]}}
    state=[]
    for row in rows:
        diag=row.get('ui_persistence') or {}
        spa=diag.get('spa') or {}
        reload=diag.get('reload') or {}
        a=spa.get('final') or {}
        z=reload.get('final') or {}
        both=bool(a.get('status')=='OBSERVED_MATCH' and
             z.get('status')=='OBSERVED_MATCH' and
             diag.get('same_filter_url_after_reload') is True and
             a.get('region_id_matches') is True and z.get('region_id_matches') is True)
        state.append(both)
        doc['contexts'].append({
           'context':row.get('context'),
           'route_count':row.get('route_count'),
           'legacy_filter_proof':row.get('filter_proof_status'),
           'legacy_recheck_status':diag.get('legacy_recheck_status'),
           'spa':{'status':a.get('status','NOT_OBSERVABLE'),
                  'outcome':spa.get('outcome'),
                  'panel_probe':a.get('panel_probe'),
                  'control_visibility':a.get('control_visibility'),
                  'selected_state_complete':a.get('selected_state_complete')},
           'reload':{'status':z.get('status','NOT_OBSERVABLE'),
                     'outcome':reload.get('outcome'),
                     'panel_probe':z.get('panel_probe'),
                     'control_visibility':z.get('control_visibility'),
                     'selected_state_complete':z.get('selected_state_complete')},
           'same_filter_url_after_reload':diag.get('same_filter_url_after_reload'),
           'response_filter_fields':row.get('v415_response_filter_field_status'),
           'candidate_gate':row.get('candidate_gate',False)})
    diagnostic_complete=bool(complete and len(state)==3 and all(
        (r.get('ui_persistence') or {}).get('reload') for r in rows))
    doc['evaluation']['route_capture_complete']=complete
    doc['evaluation']['capture_complete']=diagnostic_complete
    if diagnostic_complete:
        if all(state):
            doc['evaluation']['status']='REPRODUCED_SELECTED_FILTERS_VISIBLE'
        elif any(x.get('spa',{}).get('status')=='OBSERVED_MISMATCH' or
                 x.get('reload',{}).get('status')=='OBSERVED_MISMATCH' for x in doc['contexts']):
            doc['evaluation']['status']='FILTER_SELECTION_MISMATCH_OBSERVED'
        else:
            doc['evaluation']['status']='FILTER_UI_PARTIALLY_OR_NOT_OBSERVABLE'
    doc['evaluation']['selected_state_verified_all_contexts']=bool(diagnostic_complete and all(state))
    doc['evaluation']['diagnostic_contexts_captured']=sum(bool((r.get('ui_persistence') or {}).get('reload'))
                                                       for r in rows)
    return doc


async def run(args):
    args.filter_recheck_v15=True
    args.filter_dom_v16=False
    args.filter_activation_v161=False
    salt=secrets.token_bytes(32)
    rows=[]
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(headless=not args.headed)
            try:
                for name,region in [('cheonan_a','cheonan'),('asan_control','asan'),('cheonan_b','cheonan')]:
                    row=await full.capture(browser,name,region,args,salt)
                    rows.append(row)
                    print('v4.17',name,'route',row.get('route_count'),
                          'spa',((row.get('ui_persistence') or {}).get('spa') or {}).get('observation_status'),
                          'reload',((row.get('ui_persistence') or {}).get('reload') or {}).get('observation_status'))
                    if row.get('status','').startswith('STOP_') or row.get('access_blocked'):
                        break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as exc:
        rows.append({'context':'browser','region':None,
                     'status':'STOP_'+type(exc).__name__,
                     'access_blocked':False})
    base=full.evaluate(rows)
    result=assemble(rows,base)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'v417_filter_state_results.json').write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# v4.17 UI filter state recheck','',
       f"- Verdict: {result['evaluation']['status']}",
       f"- Whole observed Route capture: {result['evaluation']['capture_complete']}",
       f"- SPA/reload evidence contexts: {result['evaluation']['diagnostic_contexts_captured']}/3",
       f"- Selected controls verified across all contexts: {result['evaluation']['selected_state_verified_all_contexts']}",
       '', '| Context | Route rows | SPA | Reload | URL persisted |',
       '|---|---:|---|---|---|']
    for row in result['contexts']:
        lines.append(f"| {row['context']} | {row['route_count']} | {row['spa']['status']} | {row['reload']['status']} | {row['same_filter_url_after_reload']} |")
    lines+=['','- Proof is restricted to visible public UI controls: category, availability, maximum price.',
            '- URL or Route fields alone are not accepted as selected UI control state.',
            '- The original Route evidence and strict item-listing gates remain separate.',
            '- No raw HTML, labels, URLs, product identifiers or customer data are exported.',
            '- Strict listing approvals remain zero; server-side price enforcement is not proven.','']
    (args.output_dir/'v417_filter_state_report.md').write_text('\n'.join(lines),encoding='utf-8')
    (args.output_dir/'v417_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    return 0 if result['evaluation']['capture_complete'] else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v417_output'))
    p.add_argument('--headed',action='store_true')
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    args=p.parse_args()
    args.output_dir=args.output_dir.resolve()
    args.timeout=max(15,min(45,args.timeout))
    args.settle_ms=max(800,min(3500,args.settle_ms))
    return asyncio.run(run(args))


if __name__=='__main__':
    raise SystemExit(main())
