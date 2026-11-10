# -*- coding: utf-8 -*-
"""v4.16.1: one guarded UI click to determine the modified filter button's role.

This is intentionally separate from the v4.16 passive DOM study. Only a unique
button proven by DOM evidence to replace the original public "필터" header
button is eligible. The click stays in a fresh logged-out research context.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import daangn_browser_v4_6 as v46
import daangn_filter_dom_v4_16 as anatomy
import daangn_filter_recheck_v4_15 as v15
import daangn_render_gap_v4_12 as render


def eligible(baseline,reload_now):
    """Positive identity signals; never infer action from raw label text alone."""
    if baseline.get('status')!='OBSERVED' or reload_now.get('status')!='OBSERVED':
        return False
    if baseline.get('candidate_count')!=1 or reload_now.get('candidate_count')!=1:
        return False
    if baseline.get('candidates_truncated') or reload_now.get('candidates_truncated'):
        return False
    if len(baseline.get('candidates',[]))!=1 or len(reload_now.get('candidates',[]))!=1:
        return False
    before=baseline['candidates'][0]
    after=reload_now['candidates'][0]
    if before.get('tag')!='BUTTON' or after.get('tag')!='BUTTON':
        return False
    if before.get('access_name_source')!='ARIA_LABEL' or after.get('access_name_source')!='ARIA_LABEL':
        return False
    if before.get('access_name_length')!=2 or after.get('access_name_length')!=4:
        return False
    if not before.get('semantic_flags',{}).get('exact'):
        return False
    if not before.get('geometry',{}).get('inside_header_nav') or not after.get('geometry',{}).get('inside_header_nav'):
        return False
    if before.get('semantic_dom_position')!=after.get('semantic_dom_position'):
        return False
    for key in ('svg_count','span_count','button_count'):
        if before.get('children',{}).get(key)!=after.get('children',{}).get(key):
            return False
    if [p.get('tag') for p in before.get('ancestry',[])]!=[p.get('tag') for p in after.get('ancestry',[])]:
        return False
    if after.get('action',{}).get('type')!='button':
        return False
    if after.get('action',{}).get('disabled') or after.get('action',{}).get('pointer_events')=='NONE':
        return False
    if after.get('action',{}).get('link_kind')!='NOT_A_LINK':
        return False
    if any(after.get('semantic_flags',{}).get(word) for word in
           ('reset','apply','category','price','availability','count')):
        return False
    if after.get('semantic_flags',{}).get('exact'):
        return False
    if not any(p.get('tag')=='HEADER' for p in after.get('ancestry',[])):
        return False
    if after.get('geometry',{}).get('visible') is not True:
        return False
    if after.get('geometry',{}).get('inside_dialog') or after.get('geometry',{}).get('inside_footer'):
        return False
    return True


async def exercise(page,args,baseline,expected_reload,settle_ms):
    out={'status':'NOT_CLICKED_UNVERIFIED_IDENTITY',
         'performed':False,'eligible':False,'url_filters_persisted':None,
         'panel_found_after_click':None,'selected_ui_state':'NOT_OBSERVED',
         'access_restricted':False}
    current=await anatomy.inspect(page)
    if current.get('status')!='OBSERVED' or current.get('candidates_truncated'):
        out['status']='NOT_CLICKED_DOM_NOT_OBSERVABLE'
        return out
    if not eligible(baseline,expected_reload) or not eligible(baseline,current):
        return out
    if current['candidates'][0]['structural_fingerprint']!=expected_reload['candidates'][0]['structural_fingerprint']:
        out['status']='NOT_CLICKED_DOM_CHANGED'
        return out
    position=current['candidates'][0].get('semantic_dom_position')
    if type(position) is not int or position<0 or position>100:
        out['status']='NOT_CLICKED_UNSAFE_DOM_POSITION'
        return out
    # Use precisely the element observed by the passive DOM inspector, rather
    # than assuming its changed accessible label begins with the old word.
    button=page.locator('button,a[href],[role="button"]').nth(position)
    try:
        if await button.count()!=1 or not await button.is_visible() or not await button.is_enabled():
            out['status']='NOT_CLICKED_UNIQUE_VISIBLE_BUTTON_MISSING'
            return out
        if await button.evaluate('(e)=>e.tagName')!='BUTTON':
            out['status']='NOT_CLICKED_CONTROL_TYPE_CHANGED'
            return out
        current_name=await button.get_attribute('aria-label')
        if not isinstance(current_name,str) or len(current_name)>80 or (
                '필터' not in current_name and 'filter' not in current_name.lower()):
            out['status']='NOT_CLICKED_ACCESSIBLE_NAME_CHANGED'
            return out
        original=page.url
        prior_panel=await v46.filter_snapshot(page)
        out['panel_found_before_click']=bool(prior_panel.get('panel_found'))
        if out['panel_found_before_click']:
            out['status']='NOT_CLICKED_FILTER_PANEL_ALREADY_OPEN'
            return out
        out['eligible']=True
        await button.click(timeout=5000)
        out['performed']=True
        await page.wait_for_timeout(settle_ms)
        if (await render.snapshot(page)).get('restricted'):
            out['status']='STOP_ACCESS_RESTRICTION'
            out['access_restricted']=True
            return out
        same=v15.same_filter_params(original,page.url,args.regions['target']['id'])
        out['url_filters_persisted']=same
        if not same:
            out['status']='CLICK_CHANGED_FILTER_URL'
            return out
        panel=await v46.filter_snapshot(page)
        out['panel_found_after_click']=bool(panel.get('panel_found'))
        actual=await v15.witness(page,args)
        out['selected_ui_state']=actual.get('status','NOT_OBSERVABLE')
        out['selected_controls_visible']=bool(actual.get('panel_exposed'))
        if actual.get('status')=='OBSERVED_MATCH' and actual.get('panel_exposed'):
            out['status']='BUTTON_OPENED_FILTER_WITH_MATCHING_SELECTION'
        elif actual.get('status')=='OBSERVED_MISMATCH':
            out['status']='BUTTON_OPENED_FILTER_WITH_DIFFERENT_SELECTION'
        elif out['panel_found_after_click']:
            out['status']='BUTTON_OPENED_PANEL_SELECTION_UNOBSERVABLE'
        else:
            out['status']='BUTTON_CLICK_NO_FILTER_PANEL_OBSERVED'
    except Exception as exc:
        out['status']='CLICK_ERROR_'+type(exc).__name__
    return out


def evaluate_action(rows):
    steps=[r.get('v416_activation') or {} for r in rows]
    outcomes=[x.get('status','NOT_OBSERVED') for x in steps]
    actions=[x.get('performed') is True for x in steps]
    # A real closed->open filter panel transition proves the button's public UI
    # role, independently of whether controls inside can be re-read.
    opening=[bool(x.get('performed') is True and
                  x.get('panel_found_before_click') is False and
                  x.get('panel_found_after_click') is True and
                  x.get('url_filters_persisted') is True and
                  not x.get('access_restricted')) for x in steps]
    role_proven=len(rows)==3 and all(opening)
    verified=role_proven and all(
        x.get('selected_ui_state')=='OBSERVED_MATCH' and
        x.get('selected_controls_visible') is True for x in steps)
    mismatch=role_proven and any(x.get('selected_ui_state')=='OBSERVED_MISMATCH'
                                 for x in steps)
    if role_proven and verified:
        status='REPRODUCED_FILTER_PANEL_OPENING_SELECTION_VERIFIED'
    elif role_proven and mismatch:
        status='REPRODUCED_FILTER_PANEL_OPENING_SELECTION_MISMATCH'
    elif role_proven:
        status='REPRODUCED_FILTER_PANEL_OPENING_SELECTION_UNOBSERVABLE'
    elif any(actions):
        status='CLICK_OBSERVED_BUT_PANEL_OPENING_NOT_PROVEN'
    else:
        status='ALL_CLICKS_REJECTED_BY_IDENTITY_GATE'
    return {'status':status,'per_context_verdicts':outcomes,
        'performed_click_count':sum(actions),
        'closed_to_open_panel_transitions':sum(opening),
        'selected_state_verified_all_contexts':verified,
        'role_functionally_proven_all_contexts':role_proven,
        'strict_listing_approved_count':0}


async def run(options):
    options.filter_activation_v161=True
    code=await anatomy.run(options)
    path=options.output_dir/'v416_dom_anatomy_results.json'
    if path.is_file():
        doc=json.loads(path.read_text(encoding='utf-8'))
        doc['version']='4.16.2'
        doc['activation_evaluation']=evaluate_action(doc.get('contexts',[]))
        path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        summary=['# v4.16.2 verified filter-button activation','',
                 f"- Verdict: {doc['activation_evaluation']['status']}",
                 f"- Click count: {doc['activation_evaluation']['performed_click_count']}",
                 f"- Verified panel closed-to-open transitions: {doc['activation_evaluation']['closed_to_open_panel_transitions']}",
                 f"- Filter panel opener role verified in all contexts: {doc['activation_evaluation']['role_functionally_proven_all_contexts']}",
                 f"- Selected state verified in all contexts: {doc['activation_evaluation']['selected_state_verified_all_contexts']}",
                 '- Strict listing approvals: 0','']
        (options.output_dir/'v4161_activation_report.md').write_text('\n'.join(summary),encoding='utf-8')
    return code


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v4161_output'))
    p.add_argument('--headed',action='store_true')
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    opts=p.parse_args()
    opts.output_dir=opts.output_dir.resolve()
    opts.timeout=max(15,min(45,opts.timeout))
    opts.settle_ms=max(800,min(3500,opts.settle_ms))
    return asyncio.run(run(opts))


if __name__=='__main__':
    raise SystemExit(main())
