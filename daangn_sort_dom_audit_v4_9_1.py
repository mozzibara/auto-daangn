# -*- coding: utf-8 -*-
"""Bounded, owner-approved observational audit of sort DOM on public search.

Read only. Each viewport uses one known public search URL. No fabricated sort
parameter, no listing exports, no HTML or screenshots retained.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import daangn_v4_1_core as core
import daangn_browser_v4_6 as v46
import daangn_sort_dom_inspector as inspector

VIEWPORTS = {'desktop': {'width': 1440, 'height': 900},
             'mobile': {'width': 390, 'height': 844}}


def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')


def aggregate(rows):
    snaps=[s for r in rows for scan in r.get('inspections',[]) for s in scan.get('snapshots',[])]
    allcand=[c for s in snaps for c in (s.get('dom') or {}).get('candidates',[])]
    linktokens={(t['key'],t['value']) for c in allcand for t in [c.get('sort_link_token')] if t}
    labels={c['label'] for c in allcand if c.get('label')}
    status='STOP_NO_VALID_PUBLIC_DOM' if not any(r.get('http_status')==200 and r.get('region_ok') and not r.get('challenge_detected') for r in rows) else (
           'SORT_QUERY_LINKS_OBSERVED' if linktokens else
           'SORT_LABELED_UI_OBSERVED' if labels else
           'SORT_UI_NOT_OBSERVABLE_IN_SCANNED_DOM')
    return {'status': status,
            'captured_viewports':sum(r.get('status')=='CAPTURED_PUBLIC_DOM' and r.get('http_status')==200 and r.get('region_ok') for r in rows),
            'sort_query_link_tokens_observed':[{'key':k,'value':v} for k,v in sorted(linktokens)][:12],
            'recognized_sort_labels':sorted(labels)[:20],
            'visible_sort_candidates':sum((s.get('dom') or {}).get('visible_sort_count',0) for s in snaps),
            'hidden_sort_candidates':sum((s.get('dom') or {}).get('hidden_sort_count',0) for s in snaps),
            'structural_role_counts':{k:sum((s.get('dom') or {}).get('role_counts',{}).get(k,0) for s in snaps)
                                      for k in ('button','combobox','menu','menuitem','menuitemradio','listbox','option','tab','link')},
            'observational_only':True,
            'sort_choice_verified':False,
            'backend_sort_effect_verified':False,
            'fixed_server_limit_verified':False,
            'all_sort_features_absent_proven':False,
            'approved_listings':0}


def safe_result(row):
    return {k:v for k,v in row.items() if k not in ('_raw','_private')}


async def inspect_viewport(browser, name, viewport, *, timeout, settle_ms):
    region=core.BY_KEY['cheonan']
    ctx=await browser.new_context(locale='ko-KR',viewport=viewport)
    row={'viewport':name,'dimensions':viewport,'time_utc':now(),
         'status':'NOT_STARTED','http_status':None,'region_ok':False,
         'challenge_detected':None,'inspections':[],
         'filter_panel_opened':False,'error_type':None}
    try:
        page=await ctx.new_page()
        page.set_default_timeout(timeout*1000)
        response=await page.goto(core.search_url('HDD',region),
                                 wait_until='domcontentloaded',timeout=timeout*1000)
        row['http_status']=response.status if response else None
        if row['http_status']!=200:
            row['status']='STOP_HTTP_NOT_200'
            return row
        await page.wait_for_timeout(settle_ms)
        row['region_ok']=core.region_id_in_url(page.url)==region['id']
        if not row['region_ok']:
            row['status']='STOP_REGION_MISMATCH'
            return row
        probe=await page.evaluate('''() => ({
          challenged:/captcha|verify you are human|access denied|비정상적인 접근/i.test((document.body?.innerText||'').slice(0,2200)),
          region_ui_ok:[...document.querySelectorAll('button[aria-label]')].some(e=>(e.getAttribute('aria-label')||'').includes('불당동')),
          public_dom_controls:document.querySelectorAll('a,button,select,[role]').length
        })''')
        row['challenge_detected']=bool(probe['challenged'])
        row['region_ui_ok']=bool(probe['region_ui_ok'])
        row['public_dom_controls']=min(int(probe['public_dom_controls']),999999)
        if row['challenge_detected']:
            row['status']='STOP_CHALLENGE'
            return row
        if not row['region_ui_ok'] or row['public_dom_controls']<10:
            row['status']='STOP_PUBLIC_DOM_NOT_READY'
            return row
        row['inspections'].append({'surface':'search_page',**(await inspector.inspect(page))})
        # Filter drawer is public and read-only; inspect menu/ARIA labels but do
        # not choose or apply any category, price or sort setting.
        trigger=await v46.find_filter_trigger(page)
        if trigger is not None:
            try:
                await trigger.click(timeout=4000)
                await page.wait_for_timeout(350)
                row['filter_panel_opened']=True
                row['inspections'].append({'surface':'filter_drawer',**(await inspector.inspect(page,reveal_menu=False))})
                await page.keyboard.press('Escape')
            except Exception as exc:
                row['filter_panel_error_type']=type(exc).__name__
        row['status']='CAPTURED_PUBLIC_DOM'
    except Exception as exc:
        row['status']='STOP_'+type(exc).__name__
        row['error_type']=type(exc).__name__
    finally:
        await ctx.close()
    return row


def report(doc):
    a=doc['evaluation']
    lines=['# v4.9.1 public sort DOM reconnaissance','',
           f"- Status: **{a['status']}**",
           f"- Captured viewports: **{a['captured_viewports']}**",
           '- Probe inspected links, menus, visible and hidden ARIA controls, native selects and filter drawer.',
           '- No raw HTML, listing URL, cookie, account or unrestricted text saved.','',
           '## Evidence','',
           f"- Recognized sort labels: `{a['recognized_sort_labels']}`",
           f"- Explicit public sort-link tokens: `{a['sort_query_link_tokens_observed']}`",
           f"- DOM sort candidates, visible (across snapshots): **{a['visible_sort_candidates']}**",
           f"- DOM sort candidates, hidden (across snapshots): **{a['hidden_sort_candidates']}**",'']
    for r in doc['views']:
        lines.append(f"## {r['viewport']} — {r['status']}")
        lines.append(f"- HTTP {r['http_status']}; region match: `{r['region_ok']}`; filter drawer opened: `{r['filter_panel_opened']}`")
        for scan in r['inspections']:
            for s in scan.get('snapshots',[]):
                d=s['dom'];cl=s['classification']
                lines.append(f"- {scan['surface']} / {s['phase']}: `{cl['status']}`, candidates visible={d['visible_sort_count']}, hidden={d['hidden_sort_count']}, select={d['select_count']}, sort links={d['sort_link_count']}, aria-has-popup={d['dropdown_hint_count']}, aria-expanded={d['expanded_hint_count']}")
        lines.append('')
    lines+=['## Evidence limits','',
           '- No observed sort control does **not** establish site-wide absence of sorting.',
           '- A sort-labelled control or URL token is not evidence of server sorting until selection, route correlation, and independent repetition are verified.',
           '- Fixed response-count ceilings and ranking-caused omission remain unproven.',
           '- This audit never approves or exports shopping listings.','']
    return '\n'.join(lines)


async def run(args):
    p=Path(args.output_dir);p.mkdir(parents=True,exist_ok=True)
    checked=core.public_robots_check('HDD')
    rows=[]
    if checked.get('allowed'):
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser=await pw.chromium.launch(headless=not args.headed)
                try:
                    for name,viewport in VIEWPORTS.items():
                        rows.append(await inspect_viewport(browser,name,viewport,
                                    timeout=args.timeout,settle_ms=args.settle_ms))
                        await asyncio.sleep(args.pause_ms/1000)
                finally:
                    await browser.close()
        except Exception as exc:
            rows.append({'viewport':'browser','status':'STOP_'+type(exc).__name__,
                         'http_status':None,'region_ok':False,'inspections':[],
                         'filter_panel_opened':False,'challenge_detected':None})
    else:
        rows.append({'viewport':'preflight','status':'STOP_ROBOTS_UNVERIFIED_OR_DENIED',
                     'http_status':None,'region_ok':False,'inspections':[],
                     'filter_panel_opened':False,'challenge_detected':None})
    a=aggregate(rows)
    if len(rows)!=2 or any(r.get('status')!='CAPTURED_PUBLIC_DOM' for r in rows):
        a['status']='STOP_INCOMPLETE_DOM_RECON'
    doc={'version':'4.9.1','time_utc':now(),
         'design':{'keyword':'HDD','region':'cheonan','viewports':VIEWPORTS,
                   'surfaces':['search_page','filter_drawer'],
                   'sort_options':'OBSERVED_UI_ONLY'},
         'views':rows,'evaluation':a,
         'run_level':{'status':a['status'],'blocked':True,'accepted_count':0}}
    (p/'daangn_sort_dom_v4_9_1_results.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (p/'daangn_sort_dom_v4_9_1_report.md').write_text(report(doc),encoding='utf-8')
    (p/'daangn_sort_dom_v4_9_1_limited_accept.json').write_text('{"blocked":true,"samples":[]}\n',encoding='utf-8')
    print('sort DOM evidence:',a['status'],'public sort labels:',a['recognized_sort_labels'])
    return 0 if a['captured_viewports']==2 and len(rows)==2 and all(r['status']=='CAPTURED_PUBLIC_DOM' for r in rows) else 2


def main():
    parser=argparse.ArgumentParser(description='Bounded public DOM sort control audit, no sort guessing')
    parser.add_argument('--output-dir',type=Path,default=Path('v491_output'))
    parser.add_argument('--headed',action='store_true')
    parser.add_argument('--timeout',type=int,default=25)
    parser.add_argument('--settle-ms',type=int,default=1600)
    parser.add_argument('--pause-ms',type=int,default=1800)
    args=parser.parse_args()
    args.timeout=max(15,min(args.timeout,45));args.settle_ms=max(800,min(args.settle_ms,3500))
    args.pause_ms=max(1200,min(args.pause_ms,5000))
    return asyncio.run(run(args))

if __name__=='__main__':raise SystemExit(main())
