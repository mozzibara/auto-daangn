# -*- coding: utf-8 -*-
"""v4.9.1 read-only and bounded public search sort-DOM reconnaissance.

Only recognized sort UI labels / allowlisted sort URL query tokens are emitted.
Never save raw HTML, arbitrary aria text, raw links, cookies, or DOM IDs.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

SORT_DOM_JS = r'''() => {
  const keys=['sort','order','sort_by','sortBy','order_by','ordering'];
  const safeToken=/^[A-Za-z0-9_-]{1,48}$/;
  const roles=['button','combobox','menu','menubar','menuitem','menuitemradio','listbox','option','radio','tab','link'];
  const tracked='select,option,button,a[href],summary,details,[role],[aria-haspopup],[aria-controls],[aria-expanded],[data-testid],[class*="sort" i],[id*="sort" i]';
  const result={scanned:0, truncated:false, tag_counts:{}, role_counts:{},
    dropdown_hint_count:0, expanded_hint_count:0, hidden_sort_count:0,
    visible_sort_count:0, sort_link_count:0, select_count:0,
    candidates:[], select_options:[], visibility_basis:'computed style and bounding client rect',
    shadow_root_hosts_seen:0};
  const clean=(t) => String(t||'').replace(/\s+/g,' ').trim().slice(0,90);
  const sortLabel=(v)=>{
    const t=clean(v);
    if(!t || t.length>76)return null;
    if (/^(정렬|정렬 방식)(?:\s*[:：-]\s*(?:최신순|최근순|오래된순|인기순|추천순|관련도순|정확도순|낮은 가격순|높은 가격순|가격 낮은순|가격 높은순|가격순|가까운순))?$/i.test(t))return t;
    if (/^(?:최신순|최근순|오래된순|인기순|추천순|관련도순|정확도순|낮은 가격순|높은 가격순|가격 낮은순|가격 높은순|가격순|가까운순)$/i.test(t))return t;
    if (/^(?:sort(?: by)?)(?:\s*[:：-]\s*(?:newest|oldest|most recent|relevance|popular|recommended|price low to high|price high to low))?$/i.test(t))return t;
    if (/^(?:newest|oldest|most recent|relevance|popular|recommended|price low to high|price high to low)$/i.test(t))return t;
    return null;
  };
  const visible=(el)=>{
    if(!el||!el.getBoundingClientRect)return false;
    const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&s.opacity!=='0'
      && !el.closest('[hidden],[inert],[aria-hidden="true"]');
  };
  const sortHref=(raw)=>{
    if(!raw)return null;
    try{
      const u=new URL(raw,location.href);
      if(u.protocol!=='https:'||u.hostname!=='www.daangn.com'||u.pathname!=='/kr/search/buy-sell/')return null;
      const found=[];
      for(const [k,v] of u.searchParams)if(keys.includes(k))found.push([k,v]);
      if(found.length!==1||!safeToken.test(found[0][1]))return null;
      return {key:found[0][0],value:found[0][1]};
    }catch{return null;}
  };
  const nodes=[...document.querySelectorAll(tracked)];
  result.truncated=nodes.length>2200;
  for(const el of nodes.slice(0,2200)){
    result.scanned++;
    const tag=el.tagName.toLowerCase(), role=el.getAttribute('role')||'';
    result.tag_counts[tag]=(result.tag_counts[tag]||0)+1;
    if(roles.includes(role))result.role_counts[role]=(result.role_counts[role]||0)+1;
    if(el.shadowRoot)result.shadow_root_hosts_seen++;
    const open=el.getAttribute('aria-expanded');
    const haspopup=el.getAttribute('aria-haspopup');
    if(haspopup&&haspopup!=='false')result.dropdown_hint_count++;
    if(open!==null)result.expanded_hint_count++;
    if(tag==='select'){
      result.select_count++;
      const opts=[...el.options].slice(0,20).map(o=>sortLabel(o.label||o.textContent)).filter(Boolean);
      if(opts.length && result.select_options.length<12){
        result.select_options.push({visible:visible(el),matched_option_labels:[...new Set(opts)].slice(0,12),
          selected_label:sortLabel(el.selectedOptions?.[0]?.label),option_count:el.options.length});
      }
    }
    const labels=[el.getAttribute('aria-label'),el.getAttribute('title')];
    if(!['select','option'].includes(tag))labels.push(el.innerText||'');
    else if(tag==='option')labels.push(el.label||el.textContent||'');
    const label=labels.map(sortLabel).find(x=>x)||null;
    const testid=(el.getAttribute('data-testid')||'').slice(0,100);
    const sortHint=/sort|sorting|sort-by|order-by/i.test(testid) ||
      /(?:^|[-_ ])sort(?:[-_ ]|$)/i.test((el.getAttribute('class')||'').slice(0,180)) ||
      /(?:^|[-_ ])sort(?:[-_ ]|$)/i.test((el.getAttribute('id')||'').slice(0,100));
    const hrefToken=tag==='a'?sortHref(el.getAttribute('href')):null;
    if(hrefToken)result.sort_link_count++;
    if(!(label||sortHint||hrefToken))continue;
    const isVisible=visible(el);
    if(isVisible)result.visible_sort_count++;
    else result.hidden_sort_count++;
    if(result.candidates.length>=45)continue;
    result.candidates.push({tag,role:roles.includes(role)?role:'',label,
      visible:isVisible,aria_has_popup:haspopup==='menu'||haspopup==='listbox'||haspopup==='true'?haspopup:null,
      aria_expanded:open==='true'?true:open==='false'?false:null,
      aria_controls_present:!!el.getAttribute('aria-controls'),
      testid_sort_hint:sortHint,
      sort_link_token:hrefToken,
      is_interactive:['button','summary','select','a'].includes(tag)||['button','combobox','menuitem'].includes(role),
      is_disabled:el.hasAttribute('disabled')||el.getAttribute('aria-disabled')==='true'});
  }
  return result;
}'''


def classify(snapshot: dict) -> dict:
    """Interpret observational DOM evidence; never imply backend sorting support."""
    if not isinstance(snapshot, dict) or 'scanned' not in snapshot:
        return {'status': 'SORT_DOM_NOT_CAPTURED', 'selectable_options_proven': False,
                'server_sort_effect_proven': False}
    candidates = snapshot.get('candidates') or []
    links = sum(bool(c.get('sort_link_token')) for c in candidates)
    labeled_visible = [c for c in candidates if c.get('visible') and c.get('label')]
    hidden = [c for c in candidates if not c.get('visible')]
    hinted = [c for c in candidates if c.get('testid_sort_hint') or c.get('aria_has_popup')]
    if links or snapshot.get('sort_link_count', 0): status = 'SORT_QUERY_LINK_OBSERVED'
    elif labeled_visible: status = 'VISIBLE_SORT_LABEL_OBSERVED'
    elif hidden: status = 'HIDDEN_SORT_CANDIDATE_ONLY'
    elif hinted: status = 'STRUCTURAL_SORT_HINT_ONLY'
    else: status = 'SORT_UI_NOT_OBSERVABLE_IN_SNAPSHOT'
    return {'status': status,
            'sort_link_count':snapshot.get('sort_link_count',0),
            'labeled_visible_count':len(labeled_visible),
            'hidden_candidate_count':len(hidden),
            'selectable_options_proven':False, 'server_sort_effect_proven':False,
            'scope':'OBSERVED_DOM_ONLY'}


async def inspect(page, *, reveal_menu=True):
    """Scan visible and hidden ARIA, native controls and sort query links.

    Click at most two *visible, explicitly sort-labelled non-anchor* triggers.
    This does not submit a form, select an option, or leave the page.
    """
    snapshots=[]
    try:
        base=await asyncio.wait_for(page.evaluate(SORT_DOM_JS), timeout=7)
        snapshots.append({'phase':'before','dom':base,'classification':classify(base)})
        if reveal_menu:
            nodes=page.locator('button,summary,[role="combobox"],[role="button"],[aria-haspopup]')
            count=min(await nodes.count(),280)
            opened=0
            for i in range(count):
                el=nodes.nth(i)
                try:
                    if not await el.is_visible() or not await el.is_enabled():continue
                    aria=await el.get_attribute('aria-label') or ''
                    title=await el.get_attribute('title') or ''
                    label=(aria or title or (await el.inner_text(timeout=700))).strip()
                    from daangn_sort_cross_v4_9 import relevant_sort_label
                    if not relevant_sort_label(label):continue
                    await el.click(timeout=2500)
                    await page.wait_for_timeout(200)
                    expanded=await asyncio.wait_for(page.evaluate(SORT_DOM_JS),timeout=7)
                    snapshots.append({'phase':'opened_sort_trigger','dom':expanded,
                                      'classification':classify(expanded)})
                    opened+=1
                    await page.keyboard.press('Escape')
                    if opened>=2:break
                except Exception:
                    # DOM may re-render on click; do not force interaction.
                    continue
        return {'status':'CAPTURED_DOM_SNAPSHOTS','snapshots':snapshots,
                'actions':{'sort_triggers_opened':max(0,len(snapshots)-1),
                           'sort_options_selected':0,'links_followed':0},
                'raw_dom_saved':False,'original_listing_links_saved':False}
    except Exception as exc:
        return {'status':'STOP_'+type(exc).__name__, 'snapshots':snapshots,
                'raw_dom_saved':False,'original_listing_links_saved':False}
