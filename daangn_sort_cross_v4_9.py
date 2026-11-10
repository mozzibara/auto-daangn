# -*- coding: utf-8 -*-
"""v4.9 conservative, UI-discovered sort x price-band experiment.

Never fabricate sort options or sort query tokens. Missing sort UI ends in a
well-defined UNVERIFIED report; no product URLs or HMAC salt are exported.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import re
import secrets
import statistics
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qsl

import daangn_v4_1_core as core
import daangn_browser_v4_4_1 as prior
import daangn_browser_v4_6 as v46
import daangn_price_bands_v4_8 as v48
import daangn_v4_5_evidence as ev
import daangn_sort_dom_inspector as dom_inspector

ROOT = Path(__file__).resolve().parent
# In each target, default/alternate sorts are tested against EXACTLY these bands.
PROFILES = {
    'cap_50000': (0, 50000),
    'cap_100000': (0, 100000),
    'band_20001_50000': (20001, 50000),
    'band_50001_100000': (50001, 100000),
}
SORT_WORDS = ('정렬', '최신순', '최근순', '오래된순', '인기순', '추천순', '관련도순', '정확도순',
              '낮은 가격순', '높은 가격순', '가격 낮은순', '가격 높은순', '가격순',
              '최신', '인기', '추천', '관련도', '정확도', 'sort', 'sort by', 'newest',
              'oldest', 'most recent', 'relevance', 'popular', 'recommended')
SORT_QUERY_KEYS = ('sort', 'order', 'sort_by', 'sortBy', 'order_by', 'ordering')
_SORTVAL = re.compile(r'[A-Za-z0-9_-]{1,48}')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def relevant_sort_label(value):
    if not isinstance(value, str):
        return False
    text = ' '.join(value.strip().split())
    return bool(0 < len(text) <= 24 and any(w == text or (text.startswith('정렬') and w in text)
                                                for w in SORT_WORDS))


def safe_sort_token(url):
    """Only an explicit unique, short public sort/order key is admitted."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != 'www.daangn.com' or parsed.path != core.SEARCH_PATH:
            return None
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        matching = [(k, v) for k, v in pairs if k in SORT_QUERY_KEYS]
        if len(matching) != 1 or not _SORTVAL.fullmatch(matching[0][1]):
            return None
        return {'key': matching[0][0], 'value': matching[0][1]}
    except Exception:
        return None


async def detect_sort(page):
    """Look for an actual visible sort dropdown/menu on the PUBLIC page only.

    No sort URL parameter or option is fabricated. The options are read from
    visible native controls; a missing control is a legitimate negative result.
    """
    selects = page.locator('select')
    for i in range(min(await selects.count(), 12)):
        sel = selects.nth(i)
        if not await sel.is_visible():
            continue
        options = await sel.locator('option').all_text_contents()
        labels = [' '.join(s.split()) for s in options]
        if len(labels) >= 2 and sum(relevant_sort_label(s) for s in labels) >= 2:
            value = await sel.input_value()
            chosen = await sel.locator('option:checked').all_text_contents()
            return {'status': 'VISIBLE_SORT_SELECT', 'kind': 'native', 'index': i,
                    'options': labels[:12], 'selected': ' '.join(chosen[0].split()) if chosen else None,
                    'native_value': value}
    candidates = page.locator('button, [role="combobox"], [role="button"], summary, [aria-haspopup="menu"], [aria-haspopup="listbox"]')
    matches = []
    for i in range(min(await candidates.count(), 80)):
        el = candidates.nth(i)
        if not await el.is_visible():
            continue
        label = (' '.join(((await el.get_attribute('aria-label')) or
                          (await el.get_attribute('title')) or
                          (await el.inner_text(timeout=1500))).split())).strip()
        if relevant_sort_label(label):
            matches.append((i, label))
    if len(matches) != 1:
        audit = await dom_inspector.inspect(page, reveal_menu=False)
        first = (audit.get('snapshots') or [{}])[0]
        evidence = {'status': (first.get('classification') or {}).get('status','SORT_DOM_NOT_CAPTURED'),
                    'visible_sort_candidates': (first.get('dom') or {}).get('visible_sort_count',0),
                    'hidden_sort_candidates': (first.get('dom') or {}).get('hidden_sort_count',0),
                    'sort_link_count': (first.get('dom') or {}).get('sort_link_count',0),
                    'role_counts': (first.get('dom') or {}).get('role_counts',{})}
        return {'status': 'SORT_UI_NOT_OBSERVABLE' if not matches else 'AMBIGUOUS_SORT_TRIGGERS',
                'kind': None, 'trigger_count': len(matches), 'dom_audit': evidence}
    idx, selected = matches[0]
    trigger = candidates.nth(idx)
    await trigger.click(timeout=5000)
    await page.wait_for_timeout(250)
    elements = page.locator('[role="option"], [role="menuitem"], [role="menuitemradio"], [role="radio"], [role="link"], a[href]')
    options = []
    for i in range(min(await elements.count(), 40)):
        e = elements.nth(i)
        if await e.is_visible():
            label = ' '.join((await e.inner_text(timeout=1500)).split())
            if relevant_sort_label(label) and label not in options:
                options.append(label)
    if len(options) < 2:
        # Some public dropdown menus use only buttons; only include exact
        # visible sort-labelled buttons, and never infer unobserved choices.
        for name in SORT_WORDS:
            loc = page.get_by_role('button', name=name, exact=True)
            if await loc.count() == 1 and await loc.is_visible() and name not in options:
                options.append(name)
    await page.keyboard.press('Escape')
    if len(options) < 2:
        return {'status': 'SORT_OPTIONS_NOT_OBSERVABLE', 'kind': 'button',
                'selected': selected, 'options': options}
    return {'status': 'VISIBLE_SORT_MENU', 'kind': 'button', 'selected': selected,
            'options': options[:12]}


def choose_sorts(probe):
    if probe.get('status') not in ('VISIBLE_SORT_SELECT', 'VISIBLE_SORT_MENU'):
        return None
    options = probe.get('options') or []
    selected = probe.get('selected')
    if not selected or selected not in options or selected == '정렬':
        return None
    alt = next((s for s in options if s != selected and s != '정렬' and relevant_sort_label(s)), None)
    return (selected, alt) if alt else None


async def set_sort(page, label, expected_default, probe):
    """Use actual Playwright UI actions to select an observed option."""
    if label not in (probe.get('options') or []):
        return {'status': 'UNOBSERVED_SORT_CHOICE'}
    if label == expected_default:
        return {'status': 'DEFAULT_UI_OBSERVED', 'label': label, 'token': safe_sort_token(page.url)}
    if probe.get('kind') == 'native':
        sel = page.locator('select').nth(probe['index'])
        if not await sel.is_visible():
            return {'status': 'SORT_CONTROL_LOST'}
        await sel.select_option(label=label, timeout=6000)
        await page.wait_for_timeout(900)
        selected = await sel.locator('option:checked').all_text_contents()
        if not selected or ' '.join(selected[0].split()) != label:
            return {'status': 'SORT_SELECTION_NOT_CONFIRMED'}
    elif probe.get('kind') == 'button':
        buttons = page.locator('button, [role="combobox"], [role="button"], summary, [aria-haspopup="menu"], [aria-haspopup="listbox"]')
        triggers = []
        for i in range(min(await buttons.count(), 80)):
            el = buttons.nth(i)
            if not await el.is_visible():
                continue
            name = ' '.join(((await el.get_attribute('aria-label')) or
                             (await el.get_attribute('title')) or
                             (await el.inner_text(timeout=1500))).split())
            if name == expected_default:
                triggers.append(el)
        if len(triggers) != 1:
            return {'status': 'SORT_CONTROL_LOST'}
        await triggers[0].click(timeout=6000)
        await page.wait_for_timeout(250)
        option_candidates = page.locator('[role="option"], [role="menuitem"], [role="menuitemradio"], [role="radio"], button')
        choices = []
        for i in range(min(await option_candidates.count(), 100)):
            el = option_candidates.nth(i)
            if await el.is_visible() and ' '.join((await el.inner_text(timeout=1500)).split()) == label:
                choices.append(el)
        if len(choices) != 1:
            return {'status': 'SORT_CHOICE_NOT_UNAMBIGUOUS', 'choice_count': len(choices)}
        await choices[0].click(timeout=6000)
        await page.wait_for_timeout(900)
    else:
        return {'status': 'UNSUPPORTED_SORT_WIDGET'}
    return {'status': 'SORT_UI_SELECTED', 'label': label, 'token': safe_sort_token(page.url)}


def correlated_route(event, key, region, sort_token):
    """Price + region + filter + optional explicit sort token must match.

    v4.6 public_request includes only sanitized query parameters. A sort token
    is a required exact match for an alternate sort, not inferred from item order.
    """
    p = (event.get('public_request') or {}).get('public_params', {})
    if not v48.matched_route(event, key, region):
        return False
    if sort_token is None:
        return True
    return p.get(sort_token['key']) == sort_token['value']


def ordered_items(model, salt):
    rows = []
    seen = set()
    for article in (model or {}).get('articles', []):
        if not isinstance(article, dict):
            continue
        normalized = core.normalized_listing(article.get('href'))
        stable = v48.gate.stable_article_id(normalized) if normalized else None
        if not stable:
            continue
        token = hmac.new(salt, stable.encode('ascii'), hashlib.sha256).hexdigest()[:24]
        if token not in seen:
            rows.append(token)
            seen.add(token)
    return rows


def sort_profile_args(args, key):
    return v48.profile_args(args, key)


async def capture_apply(page, args, name, region, key, salt, sort_token, sort_label):
    a = sort_profile_args(args, key)
    steps = []
    net = v46.Network()
    page.on('response', net.hook)
    try:
        button, selected = await v46.set_filter(page, a, steps)
        await button.click(timeout=6000)
        await page.wait_for_timeout(a.settle_ms)
        await net.drain()
    finally:
        page.remove_listener('response', net.hook)
    dom, boot = await v46.snap(page)
    observed_url = page.url
    observed_token = safe_sort_token(observed_url)
    candidates = [x for x in net.events if correlated_route(x, key, a.regions[region], sort_token)]
    doc = 200 in net.document_status and bool(ev.public_url(observed_url).get('valid'))
    # Without a uniquely correlated route, a document fallback may be inspected,
    # but it never qualifies as proof of a sorting effect.
    model = candidates[-1]['model'] if candidates else boot if doc else None
    ui = await v46.check_after(page, a, steps)
    proof = ev.validated_predicates(model, observed_url, a.regions[region]['id'],
        v46.ui_ok(selected, a) and v46.ui_ok(ui, a), bool(candidates or doc),
        ui_observation_status=ui.get('observation_status'),
        expected=v46.expected_for(a), require_response_filters=True)
    stage = v46.stage(a, name, region, 3, dom, model, observed_url, 200, proof,
                      'spa_route' if candidates else 'document' if doc else 'unmatched_route')
    stage.update({'id': f'v49:{name}:{key}:{sort_label}:apply', 'profile_key': key,
                  'sort_label': sort_label, 'sort_token': observed_token,
                  'selected_sort_token': sort_token, 'matched_route_count': len(candidates),
                  'price_url_shape_observed': v48.range_shape(
                       ev.public_url(observed_url).get('public_params', {}).get('price'),
                       *PROFILES[key]),
                  'observed_order': ordered_items(model, salt),
                  'price_profile': v48.v47.aggregate_articles(model, PROFILES[key][1]),
                  'network_blocked': net.blocked,
                  'ui_observation': ui.get('observation_status')})
    v48.bounded_stage(stage, model, salt, key, ui)
    return stage


async def capture_repeat(page, args, name, region, key, url, salt, sort_token, sort_label):
    a = sort_profile_args(args, key)
    response = await page.goto(url, wait_until='domcontentloaded', timeout=a.timeout * 1000)
    await page.wait_for_timeout(a.settle_ms)
    dom, model = await v46.snap(page)
    ui = await v46.check_after(page, a)
    proof = ev.validated_predicates(model, page.url, a.regions[region]['id'],
        v46.ui_ok(ui, a), bool(response and response.status == 200),
        ui_observation_status=ui.get('observation_status'),
        expected=v46.expected_for(a), require_response_filters=True)
    stage = v46.stage(a, name, region, 4, dom, model, page.url,
                      response.status if response else None, proof)
    stage.update({'id': f'v49:{name}:{key}:{sort_label}:repeat', 'profile_key': key,
                  'sort_label': sort_label, 'sort_token': safe_sort_token(page.url),
                  'selected_sort_token': sort_token,
                  'price_url_shape_observed': v48.range_shape(
                      ev.public_url(page.url).get('public_params', {}).get('price'), *PROFILES[key]),
                  'observed_order': ordered_items(model, salt),
                  'ui_observation': ui.get('observation_status'),
                  'url_persistence': 'PERSISTED_IN_URL' if ev.public_url(page.url).get('public_params') == ev.public_url(url).get('public_params')
                                     and safe_sort_token(page.url) == safe_sort_token(url)
                                     else 'URL_STATE_CHANGED'})
    v48.bounded_stage(stage, model, salt, key, ui)
    return stage


def rank_comparison(order_a, order_b):
    """Pure set overlap + rank position stats. IDs from same ephemeral salt."""
    left = list(dict.fromkeys(order_a))
    right = list(dict.fromkeys(order_b))
    lhs, rhs = set(left), set(right)
    shared = lhs & rhs
    li, ri = {t:i+1 for i,t in enumerate(left)}, {t:i+1 for i,t in enumerate(right)}
    gaps = [abs(li[t]-ri[t]) for t in shared]
    return {'left_count':len(lhs), 'right_count':len(rhs), 'common':len(shared),
            'left_only':len(lhs-rhs), 'right_only':len(rhs-lhs),
            'jaccard':round(len(shared)/len(lhs|rhs),6) if lhs or rhs else None,
            'shared_median_rank_displacement':statistics.median(gaps) if gaps else None,
            'shared_mean_rank_displacement':round(sum(gaps)/len(gaps),3) if gaps else None,
            'exact_rank_unchanged_count':sum(li[t]==ri[t] for t in shared),
            'relative_order_inversions_not_measured': True}


def summarize_context(profile_rows, default, alternate):
    """Compare same price bounds across sorts; distinct price windows separately."""
    metrics = {}
    for key in PROFILES:
        if (default,key) not in profile_rows or (alternate,key) not in profile_rows:
            continue
        a, b = profile_rows[(default,key)], profile_rows[(alternate,key)]
        metrics[key] = rank_comparison(a, b)
    if len(metrics) != len(PROFILES):
        return {'complete': False, 'by_profile': metrics}
    all_sets = {name:set(ids) for name,ids in profile_rows.items()}
    overall = set().union(*all_sets.values())
    by_sort = {s:set().union(*(all_sets[(s,k)] for k in PROFILES)) for s in (default,alternate)}
    union_bands = {s:set().union(*(all_sets[(s,k)] for k in PROFILES if k.startswith('band_'))) for s in (default,alternate)}
    sizes=[len(items) for items in all_sets.values()]
    plateau=bool(sizes and min(sizes)>=200 and max(sizes)-min(sizes)<=20)
    return {'complete': True, 'by_profile':metrics, 'all_unique_observed':len(overall),
            'near_plateau_candidate':plateau,
            'window_displacement_candidate':bool(plateau and any(x['left_only'] or x['right_only'] for x in metrics.values())),
            'default_unique':len(by_sort[default]), 'alternate_unique':len(by_sort[alternate]),
            'novel_from_alternate':len(by_sort[alternate]-by_sort[default]),
            'novel_from_default':len(by_sort[default]-by_sort[alternate]),
            'alternate_band_only_vs_default_cap100':len(union_bands[alternate]-all_sets[(default,'cap_100000')]),
            'within_sample_window_omissions_only': True,
            'server_fixed_result_limit_proven': False,
            'rank_based_causality_proven': False}


def safe_stage(x):
    return {k:v for k,v in x.items() if not k.startswith('_')}


async def target_context(browser, args, name, order, salt):
    ctx = await browser.new_context(locale='ko-KR', viewport={'width':1280,'height':850})
    page = await ctx.new_page()
    page.set_default_timeout(args.timeout*1000)
    record = {'context':name,'region':'target','status':'INCOMPLETE','phase':None,
              'sort_probe':{},'sorts':None,'profiles':[],'baseline':[],'error':None}
    try:
        for step in (1,2):
            record['phase']='BASELINE_'+str(step)
            st=await v46.document(page,args,name,'target',step)
            record['baseline'].append(safe_stage(st))
            if not st.get('core_valid'):
                raise RuntimeError('BASELINE_INVALID')
            await asyncio.sleep(args.pause_ms/1000)
        record['phase']='SORT_DISCOVERY'
        probe = await detect_sort(page)
        record['sort_probe'] = probe
        sorts = choose_sorts(probe)
        if not sorts:
            record['status']='UNVERIFIED_SORT_UI_NOT_OBSERVABLE'
            return record
        record['sorts'] = list(sorts)
        # Counterbalanced sort-order and price-order; no broad parallel scraping.
        combos = [(s,k) for s in (sorts if name=='target_a' else sorts[::-1])
                  for k in (tuple(PROFILES) if name=='target_a' else tuple(reversed(tuple(PROFILES))))]
        for label,key in combos:
            record['phase']=f'SORT_{label}_PRICE_{key}'
            response=await page.goto(core.search_url(args.keyword,args.regions['target']),
                    wait_until='domcontentloaded', timeout=args.timeout*1000)
            if response is None or response.status!=200:
                raise RuntimeError('RESET_INVALID')
            await page.wait_for_timeout(args.settle_ms)
            current=await detect_sort(page)
            if (current.get('status') not in ('VISIBLE_SORT_SELECT','VISIBLE_SORT_MENU') or
                    not all(x in (current.get('options') or []) for x in sorts)):
                record['status']='UNVERIFIED_SORT_CONTROL_LOST'
                break
            selected = await set_sort(page,label,current['selected'],current)
            if selected.get('status') not in ('DEFAULT_UI_OBSERVED','SORT_UI_SELECTED'):
                record['sort_selection_failure']=selected
                record['status']='UNVERIFIED_SORT_SELECTION'
                break
            requested_token=selected.get('token')
            # A non-default option without an explicit public sort token cannot
            # be tied to the later search route; stop instead of guessing.
            if label != sorts[0] and requested_token is None:
                record['sort_selection_failure']={'status':'SORT_QUERY_NOT_OBSERVABLE','label':label}
                record['status']='UNVERIFIED_SORT_QUERY_NOT_OBSERVABLE'
                break
            await asyncio.sleep(args.pause_ms/1000)
            applied=await capture_apply(page,args,name,'target',key,salt,requested_token,label)
            if applied['network_blocked'] or not applied['core_valid']:
                record['failure_observation']=safe_stage(applied)
                raise RuntimeError('ACCESS_OR_APPLY_INVALID')
            applied_token=applied['sort_token']
            sort_preserved=(requested_token == applied_token)
            if label != sorts[0] and not sort_preserved:
                record['failure_observation']=safe_stage(applied)
                record['status']='UNVERIFIED_SORT_STATE_NOT_PERSISTED'
                break
            await asyncio.sleep(args.pause_ms/1000)
            repeated=await capture_repeat(page,args,name,'target',key,page.url,salt,requested_token,label)
            row={'sort_label':label,'profile_key':key,'applied':safe_stage(applied),
                 'repeat':safe_stage(repeated),'selection':selected,
                 'sort_correlated':bool(sort_preserved and applied['matched_route_count']>0 and
                                     (label==sorts[0] or requested_token is not None)),
                 'repeat_jaccard':rank_comparison(applied['observed_order'],repeated['observed_order'])['jaccard']}
            record['profiles'].append(row)
            if not repeated['core_valid'] or repeated['url_persistence']!='PERSISTED_IN_URL':
                raise RuntimeError('REPEAT_INVALID')
            await asyncio.sleep(args.pause_ms/1000)
        else:
            record['status']='CAPTURED_ALL_PROFILES'
    except Exception as exc:
        record['status']='STOP_'+type(exc).__name__
        record['error']=str(exc)[:70] if isinstance(exc, RuntimeError) else type(exc).__name__
    finally:
        await ctx.close()
    return record


def evaluate(plans):
    targets={p['context']:p for p in plans if p.get('region')=='target'}
    all_done=len(targets)==2 and all(p['status']=='CAPTURED_ALL_PROFILES' and len(p['profiles'])==8 for p in targets.values())
    if not all_done:
        statuses=[p['status'] for p in plans]
        return {'status':'UNVERIFIED_SORT_UI_OR_INCOMPLETE', 'capture_complete':False,
                'context_statuses':statuses,'sort_effect_observed':False,
                'server_fixed_result_limit_proven':False,'rank_based_causality_proven':False,
                'approved_for_listing_export':False}
    sorts=targets['target_a']['sorts']
    if sorts!=targets['target_b']['sorts'] or not sorts or len(sorts)!=2 or sorts[0]==sorts[1]:
        return {'status':'UNVERIFIED_SORT_OPTIONS_INCONSISTENT', 'capture_complete':True,
                'sort_effect_observed':False,'approved_for_listing_export':False,
                'server_fixed_result_limit_proven':False,'rank_based_causality_proven':False}
    contexts={};valid=True;repeat_warnings={}
    for name,p in targets.items():
        indexed={(x['sort_label'],x['profile_key']):x for x in p['profiles']}
        maps={k:row['repeat']['observed_order'] for k,row in indexed.items()}
        contexts[name]=summarize_context(maps,*sorts)
        repeat_warnings[name]={f'{k[0]}::{k[1]}':v['repeat_jaccard'] for k,v in indexed.items() if v['repeat_jaccard'] is None or v['repeat_jaccard']<.98}
        valid &= all(x['sort_correlated'] and x['applied']['core_valid'] and x['repeat']['core_valid'] and
                     x['applied']['price_url_shape_observed'] and x['repeat']['price_url_shape_observed'] and
                     x['applied']['matched_route_count']>0 and x['repeat_jaccard'] is not None and
                     x['repeat_jaccard']>=.98 and x['repeat']['url_persistence']=='PERSISTED_IN_URL' and
                     len(x['repeat']['observed_order']) == x['repeat']['count'] and
                     all(not any(s['price_profile'].get(t,0) for t in ('unknown','price_above_bound','below_minimum'))
                             for s in (x['applied'],x['repeat']))
                     for x in indexed.values())
    comparisons={f'{label}::{key}':v48.set_comparison(
            {t:None for t in next(x for x in targets['target_a']['profiles'] if x['sort_label']==label and x['profile_key']==key)['repeat']['observed_order']},
            {t:None for t in next(x for x in targets['target_b']['profiles'] if x['sort_label']==label and x['profile_key']==key)['repeat']['observed_order']})
            for label in sorts for key in PROFILES}
    stable=all(x['jaccard'] is not None and x['jaccard']>=.98 for x in comparisons.values())
    alternate_tokens_differ=all(
        next(x for x in p['profiles'] if x['sort_label']==sorts[1] and x['profile_key']==key)['repeat']['sort_token'] !=
        next(x for x in p['profiles'] if x['sort_label']==sorts[0] and x['profile_key']==key)['repeat']['sort_token']
        for p in targets.values() for key in PROFILES)
    valid = bool(valid and alternate_tokens_differ)
    sort_diff=any(x['left_only'] or x['right_only'] or x['shared_mean_rank_displacement']
                  for c in contexts.values() for x in c['by_profile'].values())
    status=('OBSERVED_SORT_ASSOCIATED_RESPONSE_DIFFERENCE' if valid and stable and sort_diff else
            'UNVERIFIED_SORT_EFFECT' if not valid or not stable else 'OBSERVED_NO_SORT_DIFFERENCE')
    return {'status':status,'capture_complete':True,'sorts':sorts,'context_summaries':contexts,
            'repeat_warnings':repeat_warnings,'independent_per_sort_overlap':comparisons,
            'sort_association_valid':bool(valid),'distinct_sort_query_tokens':alternate_tokens_differ,
            'independent_reproducibility':bool(stable),
            'sort_effect_observed':bool(valid and stable and sort_diff),
            'server_fixed_result_limit_proven':False, 'rank_based_causality_proven':False,
            'backend_price_enforcement_proven':False,'approved_for_listing_export':False}


def report(payload):
    evl=payload['evaluation']
    lines=['# v4.9 sort x price-window observed search comparison','',
           f"- Capture: **{evl['status']}**; complete: `{evl['capture_complete']}`.",
           '- Sort controls must be observed and used through the actual public UI; no guessed URL parameters.',
           '- Missing sort control/response evidence means **UNVERIFIED**, not a no-sort-effect conclusion.',
           '- A similar response size does not establish a fixed response-count limit.',
           '- No public listing URLs, HMAC salts, accounts, or cookies are exported.','']
    for p in payload.get('plans', []):
        lines.append(f"## {p.get('context')} — {p.get('status')}")
        sp=p.get('sort_probe') or {}
        lines.append(f"- Sort UI probe: `{sp.get('status','NOT_MEASURED')}`; options: `{sp.get('options',[])}`")
        for row in p.get('profiles',[]):
            lines.append(f"- `{row['sort_label']} / {row['profile_key']}`: {row['repeat']['count']} items; URL token match={row['sort_correlated']}; apply-repeat J={row['repeat_jaccard']}")
        if p.get('error'):
            lines.append(f"- Failure class: `{p.get('error')}`")
        lines.append('')
    for name,stats in evl.get('context_summaries',{}).items():
        lines.append(f"## {name}: observed response overlap")
        lines.append(f"- Combined distinct items: {stats['all_unique_observed']}; alternate-sort additional items: {stats['novel_from_alternate']}")
        for key,x in stats['by_profile'].items():
            lines.append(f"- {key}: default {x['left_count']}, alternate {x['right_count']}, J={x['jaccard']}, mean rank shift={x['shared_mean_rank_displacement']}")
        lines.append('')
    lines.extend(['## Interpretation boundary','',
         '- Distinct returned order is not by itself proof of a particular server ranking algorithm.',
         '- Absence of a listing from one query does not mean it is absent from the site.',
         '- A fixed server return limit would require direct total-count/page/cursor evidence and independent repeated confirmation.',
         '- This research run never approves or exports shopping listings.',''])
    return '\n'.join(lines)


def publish(output, plans, evaluation):
    output.mkdir(parents=True, exist_ok=True)
    doc={'version':'4.9','time_utc':now(), 'design':{
        'keyword':'HDD','target_region':'cheonan','category_id':1,'available_only':True,
        'price_profiles':PROFILES,'independent_target_contexts':2,
        'sort_options':'OBSERVED_FROM_LIVE_UI_ONLY'},
        'plans':plans, 'evaluation':evaluation,
        'run_level':{'status':evaluation['status'],'blocked':True,'accepted_count':0}}
    # Privacy invariant: only sanitized public query, HMAC pseudonyms, price,
    # aggregate metrics; never original listing URLs / ephemeral salt.
    (output/'daangn_sort_cross_v4_9_results.json').write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'daangn_sort_cross_v4_9_report.md').write_text(report(doc),encoding='utf-8')
    (output/'daangn_sort_cross_v4_9_limited_accept.json').write_text(
        json.dumps({'version':'4.9','blocked':True,'samples':[]},indent=2)+'\n',encoding='utf-8')
    print('v4.9',evaluation['status'],'complete',evaluation['capture_complete'],'approved',0)
    return 0 if evaluation['capture_complete'] else 2


async def run(args):
    if not core.public_robots_check('HDD').get('allowed'):
        e=evaluate([]);e['status']='STOP_ROBOTS_UNVERIFIED_OR_DENIED'
        return publish(args.output_dir,[],e)
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        e=evaluate([]);e['status']='STOP_PLAYWRIGHT_MISSING'
        return publish(args.output_dir,[],e)
    plans=[];salt=secrets.token_bytes(32)
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=not args.headed)
            try:
                for name in ('target_a','target_b'):
                    plan=await target_context(browser,args,name,None,salt)
                    plans.append(plan)
                    print(name,plan['status'],'profiles',len(plan.get('profiles',[])))
                    if plan['status']!='CAPTURED_ALL_PROFILES':
                        break
                    await asyncio.sleep(args.pause_ms/1000)
            finally:
                await browser.close()
    except Exception as exc:
        plans.append({'context':'browser','region':'unknown','status':'STOP_'+type(exc).__name__,
                      'sort_probe':{},'profiles':[],'baseline':[]})
    return publish(args.output_dir,plans,evaluate(plans))


def main():
    p=argparse.ArgumentParser(description='Owner-approved v4.9 UI-sort x price-window experiment')
    p.add_argument('--output-dir',type=Path,default=Path('v49_output'))
    p.add_argument('--headed',action='store_true')
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--pause-ms',type=int,default=2000)
    args=p.parse_args()
    args.regions={'target':dict(core.BY_KEY['cheonan']),'control':dict(core.BY_KEY['asan'])}
    args.keyword='HDD';args.category_id=1;args.category_name=v46.CATALOG[1]
    args.available_only=True;args.min_price=0;args.max_price=50000
    args.timeout=max(15,min(args.timeout,45));args.settle_ms=max(800,min(args.settle_ms,4000))
    args.pause_ms=max(1000,min(args.pause_ms,8000));args.output_dir=args.output_dir.resolve()
    return asyncio.run(run(args))

if __name__ == '__main__':
    raise SystemExit(main())
