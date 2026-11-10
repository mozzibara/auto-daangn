# -*- coding: utf-8 -*-
"""v4.15 actual-filter-state persistence audit for the logged-out public search UI.

An old panel-container heuristic can report NOT_OBSERVABLE even while filter
controls exist. Re-observe visible controls, reopen only the actual public
filter button, and compare an SPA route transition with a fresh reload of
the exact URL that the UI produced. No fabricated search URL/API/cursor.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

import daangn_v4_1_core as core
import daangn_v4_5_evidence as evidence
import daangn_browser_v4_6 as v46
import daangn_full_route_v4_14 as v14
import daangn_render_gap_v4_12 as render

FILTER_KEYS=('q','in','price','category_id','only_on_sale')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


SURFACE_JS = r"""() => {
  const showing = (e) => {
    if (!e || !e.getBoundingClientRect) return false;
    const b=e.getBoundingClientRect(),st=getComputedStyle(e);
    return b.width>0 && b.height>0 && e.getClientRects().length>0 &&
           st.display!=='none' && st.visibility!=='hidden';
  };
  const controls=[...document.querySelectorAll('button,[role="button"],a[href]')];
  const names=(e)=>(e.getAttribute('aria-label') || e.innerText || '').trim().replace(/\s+/g,' ').slice(0,80);
  const exact=controls.filter(e => names(e)==='필터');
  const broad=controls.filter(e=>/^(?:필터|검색\s*필터|필터링|검색\s*조건|filter|filters|search filters)$/i.test(names(e)));
  const plausible=controls.filter(e=>/(?:필터|filter)/i.test(names(e)) &&
      names(e).length<35);
  const alternatives=plausible.filter(e=>!broad.includes(e));
  const resetPattern=/(?:초기화|지우기|해제|제거|삭제|리셋|clear|reset|remove)/i;
  const editPattern=/(?:편집|변경|수정|설정|열기|edit|change|configure)/i;
  const reset=alternatives.filter(e=>resetPattern.test(names(e)));
  const edit=alternatives.filter(e=>!resetPattern.test(names(e))&&editPattern.test(names(e)));
  const unknown=alternatives.filter(e=>!reset.includes(e)&&!edit.includes(e));
  const labels=[...document.querySelectorAll('label')];
  const countVisible=(x)=>x.filter(showing).length;
  const filterAttrs=[...document.querySelectorAll('button[aria-label="필터"]')];
  const anchors=[...document.querySelectorAll('a[href*="/kr/buy-sell/"]')];
  const filterPanels=[...document.querySelectorAll('[role="dialog"], [aria-modal="true"], [class*="bottom-sheet__content"], [class*="drawer__content"], [data-state="open"]')];
  return {
    exact_filter_control_count:exact.length,
    exact_filter_control_visible:countVisible(exact),
    known_aria_filter_count:filterAttrs.length,
    known_aria_filter_visible:countVisible(filterAttrs),
    broad_named_filter_count:broad.length,
    broad_named_filter_visible:countVisible(broad),
    any_filter_token_control_count:plausible.length,
    any_filter_token_control_visible:countVisible(plausible),
    alternate_filter_reset_visible:countVisible(reset),
    alternate_filter_edit_visible:countVisible(edit),
    alternate_filter_unknown_visible:countVisible(unknown),
    all_button_count:controls.filter(e=>e.tagName==='BUTTON').length,
    all_visible_button_count:controls.filter(e=>e.tagName==='BUTTON' && showing(e)).length,
    filter_dialog_candidate_count:filterPanels.length,
    filter_dialog_candidate_visible:countVisible(filterPanels),
    visible_category_label_count:countVisible(labels.filter(e=>e.innerText?.trim()==='디지털기기')),
    visible_available_label_count:countVisible(labels.filter(e=>e.innerText?.trim()==='거래 가능만 보기')),
    max_price_placeholder_count:document.querySelectorAll('input[placeholder="최대 가격"]').length,
    visible_max_price_placeholder_count:countVisible([...document.querySelectorAll('input[placeholder="최대 가격"]')]),
    listing_anchor_count:anchors.length,
    viewport_width:innerWidth
  };
}""".strip()


async def surface(page):
    """Non-identifying DOM counts to distinguish unmounted vs hidden controls."""
    try:
        result=await page.evaluate(SURFACE_JS)
        return result if isinstance(result,dict) else {'status':'UNOBSERVED'}
    except Exception as exc:
        return {'status':'ERROR_'+type(exc).__name__}



async def visible_count(locator,limit=12):
    """Never assume a hidden mounted control is visible; cap DOM enumeration."""
    try:
        count=await locator.count()
        if count>limit:
            return -1
        shown=0
        for i in range(count):
            shown+=int(bool(await locator.nth(i).is_visible()))
        return shown
    except Exception:
        return -1


async def witness(page,args):
    """Boolean/small integer proof only; never export labels, HTML, selectors or URLs."""
    original=await v46.filter_snapshot(page)
    try:
        maximum=page.get_by_placeholder('최대 가격',exact=True)
        category=page.locator('label').filter(
            has_text=re.compile(r'^\s*'+re.escape(args.category_name)+r'\s*$'))
        available=page.locator('label').filter(
            has_text=re.compile(r'^\s*거래 가능만 보기\s*$'))
        apply=page.get_by_role('button',name='적용하기',exact=True)
        trigger=await v46.find_filter_trigger(page)
        counts={
            'price_input_visible':await visible_count(maximum),
            'category_label_visible':await visible_count(category),
            'availability_label_visible':await visible_count(available),
            'apply_button_visible':await visible_count(apply)}
        # A positive witness is an actual visible control set, not a CSS class.
        exposed=all(counts[k]==1 for k in counts)
        state=await v46.ui_state(page,args) if exposed else {
            'complete':False,'failure_reason':'FILTER_CONTROLS_NOT_EXPOSED'}
        status=('OBSERVED_MATCH' if exposed and v46.ui_ok(state,args) else
                'OBSERVED_MISMATCH' if exposed and state.get('complete') else
                'PARTIAL_OBSERVATION' if exposed else 'NOT_OBSERVABLE')
        # v4.17: a real filter panel can be open while the older label/placeholder
        # locators do not resolve. Independently inspect native checked/ARIA
        # state and the actual visible price input. The panel must be open and
        # all three fields observed before any positive UI proof is admitted.
        panel_probe=None
        if original.get('panel_found'):
            from daangn_filter_panel_v4_17 import observe
            panel_probe=await observe(page,args)
            alternative=panel_probe.get('interpretation') or {}
            if alternative.get('selected_state_complete') is True:
                status=alternative.get('status','NOT_OBSERVABLE')
                exposed=True
                state={'complete':True,
                       'category':alternative.get('category'),
                       'available':alternative.get('available'),
                       'maximum':alternative.get('maximum'),
                       'minimum':0}
                if status=='OBSERVED_MATCH' and not v46.ui_ok(state,args):
                    status='OBSERVED_MISMATCH'
            elif not exposed and alternative.get('status')=='PARTIAL_OBSERVATION':
                status='PARTIAL_OBSERVATION'
        region=core.region_id_in_url(page.url)
        return {'status':status,'panel_exposed':exposed,
            'panel_probe':panel_probe,
            'legacy_panel_found':bool(original.get('panel_found')),
            'trigger_available':trigger is not None,
            'control_visibility':counts,
            'selected_state_complete':bool(state.get('complete')),
            'selected_category':state.get('category') if exposed else None,
            'selected_available_only':state.get('available') if exposed else None,
            'selected_maximum_krw':state.get('maximum') if exposed else None,
            'selected_minimum_krw':state.get('minimum') if exposed else None,
            'region_id_matches':region==str(args.regions['target']['id']),
            'failure_reason':state.get('failure_reason')}
    except Exception as exc:
        return {'status':'NOT_OBSERVABLE','panel_exposed':False,
                'legacy_panel_found':bool(original.get('panel_found')),
                'trigger_available':False,'control_visibility':{},
                'region_id_matches':False,'failure_reason':type(exc).__name__}


async def verify_filter(page,args,settle_ms,*,max_open_polls=10):
    """At most one real user-visible Filter click; fail closed on ambiguity."""
    trace={'attempted_trigger_click':False,'initial':await witness(page,args)}
    if trace['initial']['panel_exposed']:
        result=trace['initial']
        trace['outcome']='ALREADY_EXPOSED'
    else:
        trigger=None
        for _ in range(8):
            probe=await witness(page,args)
            if probe['panel_exposed']:
                break
            trigger=await v46.find_filter_trigger(page)
            if trigger is not None:
                break
            await page.wait_for_timeout(250)
        if probe['panel_exposed']:
            result=probe
            trace['outcome']='SPONTANEOUSLY_EXPOSED'
        elif trigger is None:
            result=probe
            trace['outcome']='FILTER_TRIGGER_NOT_VISIBLE'
        else:
            trace['attempted_trigger_click']=True
            try:
                await trigger.click(timeout=6000)
            except Exception as exc:
                result=await witness(page,args)
                trace['outcome']='FILTER_TRIGGER_CLICK_'+type(exc).__name__
            else:
                result=await witness(page,args)
                for _ in range(max_open_polls):
                    if result['panel_exposed']:
                        break
                    await page.wait_for_timeout(max(150,min(settle_ms//6,350)))
                    result=await witness(page,args)
                trace['outcome']=('VISIBLE_FILTER_CONTROLS_AFTER_OPEN'
                    if result['panel_exposed'] else 'FILTER_CONTROLS_NOT_EXPOSED_AFTER_OPEN')
    trace['final']=result
    trace['observation_status']=result['status']
    trace['failure_reason']=result.get('failure_reason')
    return trace


def same_filter_params(previous,current,expected_region_id):
    before=evidence.public_url(previous)
    after=evidence.public_url(current)
    p=before.get('public_params') or {}
    q=after.get('public_params') or {}
    return bool(before.get('valid') and after.get('valid') and
        all(k in p and p[k]==q.get(k) for k in FILTER_KEYS) and
        core.region_id_in_url(current)==str(expected_region_id))


def classify_cause(old_status,spa,reload,filter_persisted):
    """Diagnostic attribution remains a hypothesis, never literal source proof."""
    a=(spa or {}).get('observation_status')
    b=(reload or {}).get('observation_status')
    if not filter_persisted:
        return 'FILTER_URL_CHANGED_OR_RELOAD_INVALID'
    if 'OBSERVED_MISMATCH' in (a,b):
        return 'ACTUAL_FILTER_SELECTION_MISMATCH'
    if old_status=='NOT_OBSERVABLE' and a=='OBSERVED_MATCH' and b=='OBSERVED_MATCH':
        return 'LEGACY_PANEL_HEURISTIC_OR_SETTLE_FALSE_NEGATIVE_CANDIDATE'
    if a!='OBSERVED_MATCH' and b=='OBSERVED_MATCH':
        return 'SPA_TRANSITION_OR_TOOLBAR_REMOUNT_NOT_PERSISTENT_FAILURE'
    if a=='OBSERVED_MATCH' and b!='OBSERVED_MATCH':
        return 'RELOAD_UI_NOT_STABLY_OBSERVABLE'
    if a!='OBSERVED_MATCH' and b!='OBSERVED_MATCH':
        return 'FILTER_UI_UNOBSERVABLE_BOTH_PHASES'
    return 'UI_SELECTION_PERSISTENTLY_CONFIRMED'


async def durable_recheck(page,args,observed_url,settle_ms,old_recheck,*,dom_probe=None):
    """Compare actual SPA UI with same-filter full document; return only redacted facts."""
    old_status=(old_recheck or {}).get('status','NOT_RECORDED')
    old_reason=(old_recheck or {}).get('failure_reason')
    spa_surface=await surface(page)
    spa_dom_v16=await dom_probe(page) if dom_probe is not None else None
    spa=await verify_filter(page,args,settle_ms)
    # Closing is optional; full-page reload is independent of the old panel.
    if (await v46.filter_snapshot(page)).get('panel_found'):
        close=page.get_by_role('button',name='닫기',exact=True)
        if await visible_count(close)==1:
            try:
                await close.click(timeout=5000)
            except Exception:
                pass
    reload_status='NOT_ATTEMPTED'
    reload_trace=None
    reload_surface={'status':'NOT_OBSERVED'}
    reload_dom_v16=None
    try:
        response=await page.goto(observed_url,wait_until='domcontentloaded',timeout=args.timeout*1000)
        reload_status=('HTTP_200' if response is not None and response.status==200
                       else 'NON_200_OR_MISSING')
        await page.wait_for_timeout(settle_ms)
        reload_surface=await surface(page)
        if reload_status=='HTTP_200' and dom_probe is not None:
            reload_dom_v16=await dom_probe(page)
        if reload_status=='HTTP_200' and same_filter_params(
            observed_url,page.url,args.regions['target']['id']):
            security_state=await render.snapshot(page)
            if security_state.get('restricted'):
                return {'legacy_recheck_status':old_status,
                        'legacy_failure_reason':old_reason,
                        'spa':spa,'reload':{'observation_status':'NOT_OBSERVABLE',
                        'spa_surface':spa_surface,'reload_surface':reload_surface,
                        'spa_dom_v16':spa_dom_v16,'reload_dom_v16':reload_dom_v16,
                                         'outcome':'ACCESS_RESTRICTION'},
                        'reload_status':'ACCESS_RESTRICTION',
                        'same_filter_url_after_reload':False,
                        'cause_classification':'STOP_ACCESS_RESTRICTION',
                        'stable_selection_verified':False,
                        'access_restricted':True,
                        'no_synthetic_requests':True}
            reload_trace=await verify_filter(page,args,settle_ms)
        else:
            reload_trace={'observation_status':'NOT_OBSERVABLE',
                          'outcome':'INVALID_RELOAD_URL_OR_HTTP'}
    except Exception as exc:
        reload_status='RELOAD_'+type(exc).__name__
        reload_trace={'observation_status':'NOT_OBSERVABLE',
                      'outcome':'RELOAD_FAILED'}
    persisted=reload_status=='HTTP_200' and same_filter_params(
        observed_url,page.url,args.regions['target']['id'])
    cause=classify_cause(old_status,spa,reload_trace,persisted)
    return {'legacy_recheck_status':old_status,
            'legacy_failure_reason':old_reason,
            'spa':spa,'reload':reload_trace,
            'spa_surface':spa_surface,'reload_surface':reload_surface,
            'spa_dom_v16':spa_dom_v16,'reload_dom_v16':reload_dom_v16,
            'reload_status':reload_status,
            'same_filter_url_after_reload':persisted,
            'cause_classification':cause,
            'stable_selection_verified':bool(persisted and
                 spa.get('observation_status')=='OBSERVED_MATCH' and
                 reload_trace.get('observation_status')=='OBSERVED_MATCH'),
            'no_synthetic_requests':True}


def classify_surface(baseline,spa,reload):
    """DOM-level observation only, not source-code or server causation."""
    before=(baseline or {}).get('known_aria_filter_visible')
    after=(spa or {}).get('known_aria_filter_count')
    refreshed=(reload or {}).get('known_aria_filter_count')
    if before and after==0 and refreshed==0:
        return 'FILTER_BUTTON_NOT_MOUNTED_AFTER_APPLY_OR_RELOAD'
    if before and after and (spa or {}).get('known_aria_filter_visible')==0:
        return 'FILTER_BUTTON_MOUNTED_BUT_HIDDEN_AFTER_APPLY'
    if (spa or {}).get('any_filter_token_control_visible',0)>0:
        return 'ALTERNATE_FILTER_NAMED_CONTROL_VISIBLE'
    if before==0:
        return 'BASELINE_FILTER_BUTTON_NOT_OBSERVED'
    return 'FILTER_CONTROL_LAYOUT_CHANGE_UNCLASSIFIED'



def evaluate(rows):
    base=v14.evaluate(rows)
    ok=base.get('capture_complete') is True
    diag=[r.get('ui_persistence') or {} for r in rows]
    complete=ok and len(diag)==3 and all(d.get('reload_status') for d in diag)
    causes=[d.get('cause_classification','UNOBSERVED') for d in diag]
    surface_causes=[classify_surface(row.get('baseline_surface'),
        (row.get('ui_persistence') or {}).get('spa_surface'),
        (row.get('ui_persistence') or {}).get('reload_surface')) for row in rows]
    stable=[d.get('stable_selection_verified') is True for d in diag]
    if any(r.get('access_blocked') for r in rows):
        verdict='STOP_ACCESS_RESTRICTION'
    elif not complete:
        verdict='INCONCLUSIVE_UI_DIAGNOSTICS_INCOMPLETE'
    elif all(stable):
        verdict='PERSISTENT_UI_FILTER_SELECTION_CONFIRMED'
    elif any(c=='ACTUAL_FILTER_SELECTION_MISMATCH' for c in causes):
        verdict='OBSERVED_FILTER_SELECTION_MISMATCH'
    elif all(c=='FILTER_UI_UNOBSERVABLE_BOTH_PHASES' for c in causes):
        verdict='UI_FILTER_NOT_REOBSERVABLE_IN_BOTH_PHASES'
    else:
        verdict='PARTIAL_FILTER_OBSERVABILITY'
    return {'status':verdict,'capture_complete':complete,
        'route_capture_complete':base.get('capture_complete'),
        'contexts_expected':3,'contexts_captured':base.get('contexts_captured'),
        'route_counts':base.get('route_article_counts'),
        'dom_counts':[(r.get('dom_evidence') or {}).get('dom_unique_count') for r in rows],
        'legacy_observation_statuses':[x.get('legacy_recheck_status') for x in diag],
        'stable_spa_statuses':[(x.get('spa') or {}).get('observation_status') for x in diag],
        'stable_reload_statuses':[(x.get('reload') or {}).get('observation_status') for x in diag],
        'root_cause_candidates':causes,
        'filter_surface_change_classifications':surface_causes,
        'stable_selection_verified':stable,
        'verified_candidate_count':base.get('certified_candidate_count',0),
        'strict_listing_approved_count':0,
        'backend_enforcement_proven':False,
        'whole_marketplace_complete_proven':False}


def report(doc):
    e=doc['evaluation']
    lines=['# v4.15 filter UI persistence and observability audit','',
        f"- Verdict: **{e['status']}**",
        f"- Complete: {e['capture_complete']}; Route capture: {e['route_capture_complete']}",
        '', '| Context | Legacy | SPA control witness | Reload witness | Cause candidate |',
        '|---|---|---|---|---|']
    for row in doc['contexts']:
        d=row.get('ui_persistence') or {}
        lines.append('| '+' | '.join(map(str,[
            row.get('context'),d.get('legacy_recheck_status'),
            (d.get('spa') or {}).get('observation_status'),
            (d.get('reload') or {}).get('observation_status'),
            d.get('cause_classification')]))+' |')
    lines+=['','## Filter-control surface differential',
            '- Compare baseline (before filter), SPA after filter, and exact filtered-document reload. All fields are counts, not raw markup or text.',
            '', '| Context | Baseline filter button visible | SPA filter button visible | Reload filter button visible | SPA alternate filter controls visible |',
            '|---|---:|---:|---:|---:|']
    for row in doc['contexts']:
        ui=row.get('ui_persistence') or {}
        lines.append('| '+' | '.join(map(str,[
            row.get('context'),
            (row.get('baseline_surface') or {}).get('known_aria_filter_visible'),
            (ui.get('spa_surface') or {}).get('known_aria_filter_visible'),
            (ui.get('reload_surface') or {}).get('known_aria_filter_visible'),
            (ui.get('spa_surface') or {}).get('any_filter_token_control_visible')
        ]))+' |')
    lines+=['','## Alternate filter control semantics (no text retained)','',
        '| Context | Reset-type | Edit-type | Unknown-type |',
        '|---|---:|---:|---:|']
    for row in doc['contexts']:
        alt=(row.get('ui_persistence') or {}).get('spa_surface') or {}
        lines.append('| '+' | '.join(map(str,[
            row.get('context'),alt.get('alternate_filter_reset_visible'),
            alt.get('alternate_filter_edit_visible'),
            alt.get('alternate_filter_unknown_visible')]))+' |')
    lines+=['','## Interpretation',
       '- Visible actual filter controls and values are independently checked; a known panel CSS wrapper is not the acceptance criterion.',
       '- A reload is only performed on the exact filtered URL observed from the original UI action, with query and region persistence required.',
       '- Missing buttons, hidden inputs, stale Remix loader state, incomplete control exposure and actual mismatches are distinct statuses.',
       '- UI confirmation does not waive response-level filter metadata or per-item condition evidence.',
       '- No listing URLs, IDs, HTML, snapshots, cookies or request bodies are stored. Strict listing approval remains zero.','']
    return '\n'.join(lines)


async def run(options):
    rows=[]
    salt=secrets.token_bytes(32)
    # Reuse the real v4.14 Route capture and augment with independent UI checks.
    options.filter_recheck_v15=True
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(headless=not options.headed)
            try:
                for name,region in (('cheonan_a','cheonan'),
                                    ('asan_control','asan'),('cheonan_b','cheonan')):
                    row=await v14.capture(browser,name,region,options,salt)
                    rows.append(row)
                    print('v4.15',name,row['status'],
                          'route',row.get('route_count'),
                          'legacy',(row.get('ui_persistence') or {}).get('legacy_recheck_status'),
                          'cause',(row.get('ui_persistence') or {}).get('cause_classification'))
                    if row.get('status','').startswith('STOP_') or row.get('access_blocked'):
                        break
                    await asyncio.sleep(2)
            finally:
                await browser.close()
    except Exception as exc:
        rows.append({'context':'browser','status':'STOP_'+type(exc).__name__,
                     'access_blocked':False})
    results=evaluate(rows)
    doc={'version':'4.15','utc_time':now(),'scope':{
        'keyword':'HDD','region':'cheonan','control':'asan',
        'price_cap_krw':50000,'real_filter_ui_only':True,
        'actual_correlated_route_only':True},
        'evaluation':results,'contexts':[v14.sanitized_context(row)
                       | {'ui_persistence':row.get('ui_persistence')} for row in rows],
        'limited_acceptance':{'blocked':True,'approved_listings':[]}}
    options.output_dir.mkdir(parents=True,exist_ok=True)
    (options.output_dir/'v415_ui_persistence_results.json').write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (options.output_dir/'v415_ui_persistence_report.md').write_text(
        report(doc),encoding='utf-8')
    (options.output_dir/'v415_limited_accept.json').write_text(
        '{"blocked":true,"approved_listings":[]}\n',encoding='utf-8')
    print('v4.15 status',results['status'])
    return 0 if results['capture_complete'] else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v415_output'))
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
