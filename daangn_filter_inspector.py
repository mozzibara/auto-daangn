#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded, read-only filter UI inspection for logged-out public web search.

One navigation and one click on the site's own '필터' button. Never select or
apply options. Do not infer app-specific filters as webpage capabilities.
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

FILTER_TYPES = (
    ("neighborhood_only", "동네매물만 보기", ("동네매물만", "동네 매물만", "동네 매물")),
    ("price", "가격 / 최소·최대 금액", ("가격", "최소", "최대", "원 이상", "원 이하")),
    ("category", "카테고리", ("카테고리", "디지털기기", "생활가전")),
    ("availability", "거래 가능만 보기", ("거래 가능만", "판매 중", "판매중", "거래 완료")),
    ("sort", "정렬", ("추천순", "낮은 가격순", "높은 가격순", "최신순", "가까운순", "정렬")),
    ("distance", "거리·근처", ("2km", "가까운", "근처", "거리")),
)

FILTER_SNAPSHOT_JS = r'''() => {
  const isVisible = el => {
    if (!el || !el.getBoundingClientRect) return false;
    const b=el.getBoundingClientRect(), s=getComputedStyle(el);
    return b.width>0 && b.height>0 && s.visibility!=='hidden' && s.display!=='none';
  };
  const potentials = [...document.querySelectorAll('[role="dialog"], [aria-modal="true"], [class*="bottom-sheet__content"], [class*="drawer__content"], [data-state="open"]')]
       .filter(isVisible);
  const score = el => {
    const t=(el.innerText||'').slice(0,8000);
    return ['필터','가격','카테고리','거래 가능','동네'].reduce((n,x)=>n+(t.includes(x)?1:0),0);
  };
  potentials.sort((a,b)=>score(b)-score(a));
  const panel = potentials.length && score(potentials[0]) ? potentials[0] : null;
  const root = panel || document;
  const nodes = [...root.querySelectorAll('button, label, input, select, [role="checkbox"], [role="radio"], [role="switch"], [role="combobox"], [role="option"], [role="heading"]')]
    .filter(isVisible).filter(el=>!el.closest('a[href*="/kr/buy-sell/"]')).slice(0,130);
  const clean = x => (x||'').replace(/\s+/g,' ').trim().slice(0,120);
  const controls = nodes.map(el => ({
    tag:el.tagName.toLowerCase(), role:el.getAttribute('role')||'',
    type:el.tagName==='INPUT' ? (el.getAttribute('type')||'text') : '',
    label:clean(el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
      (el.tagName==='INPUT'? (el.closest('label')?.innerText||'') : el.innerText)||''),
    checked:el.matches('input[type="checkbox"],input[type="radio"]') ? !!el.checked :
       ['checkbox','radio','switch'].includes(el.getAttribute('role')) ? el.getAttribute('aria-checked') : null,
    disabled:!!el.disabled,
  })).filter(x=>x.label || x.role).slice(0,120);
  const lines = panel ? (panel.innerText||'').split('\n').map(clean).filter(Boolean).slice(0,70) : [];
  return {panel_found:!!panel, controls, panel_lines:lines,
    filter_trigger_found:!!document.querySelector('button[aria-label="필터"]'),
    selected_region_button:[...document.querySelectorAll('button[aria-label]')]
        .map(x=>x.getAttribute('aria-label')).find(x=>x&&x.startsWith('지역 선택:'))||null};
}'''


def summarize_filters(snapshot: dict) -> list[dict]:
    # Only literal visible text is evidence; missing UI doesn't imply lack of support.
    terms = ' '.join([str(x.get('label') or '') for x in snapshot.get('controls',[])] +
                     snapshot.get('panel_lines',[]))
    result=[]
    for key,label,needles in FILTER_TYPES:
        matching=[x for x in needles if x.casefold() in terms.casefold()]
        result.append({'id':key,'label':label,
                       'observation':'VISIBLE_UI_EVIDENCE' if matching else 'NOT_OBSERVED',
                       'matched_visible_terms':matching})
    return result


def render_report(payload: dict) -> str:
    s=payload['snapshot']
    rows=['# 당근 v4.4.1 공개 검색 필터 UI 탐색 보고서','',
          f"- 검색어: {payload['keyword']}",f"- 지역: {payload['region']}",
          f"- 결과: **{payload['status']}**",f"- 필터 창 인식: {s.get('panel_found',False)}",'',
          '## 필터 유형 감지','', '| 필터 | 관측 상태 | 근거 텍스트 |', '|---|---|---|']
    for f in payload['detected_filters']:
        rows.append(f"| {f['label']} | {f['observation']} | {', '.join(f['matched_visible_terms']) or '-'} |")
    rows += ['', '## 필터 창의 공개 텍스트 (최대 70줄)', '']
    rows += [f"- {x}" for x in s.get('panel_lines',[]) ] or ['- 감지된 텍스트 없음']
    rows += ['','## 주의', '',
             '- 웹의 실제 표시 UI만 읽었으며, 필터 옵션을 선택하거나 적용하지 않았습니다.',
             '- NOT_OBSERVED는 기능이 없다는 뜻이 아닙니다. 화면 구조와 스크립트 렌더링에 영향을 받습니다.',
             '- 앱 전용 메뉴는 웹에서 제공된다고 간주하지 않습니다.',
             '- 페이지 로딩/필터 클릭 실패 또는 접근 제한 발생 시 결과를 미확정으로 처리합니다.',
             '- HTML/쿠키/개인정보/검색 결과 본문을 저장하지 않습니다.','']
    return '\n'.join(rows)


async def run_filter_probe(args, core) -> int:
    result={'version':'4.4.1','mode':'filters',
            'timestamp_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'keyword':args.keyword,'region':args.region, 'status':'INDETERMINATE',
            'snapshot':{}, 'detected_filters':[],
            'filter_options_applied':False,'cookie_values_saved':False}
    robot=core.public_robots_check(args.keyword)
    if not robot.get('allowed'):
        result['status']='STOP_ROBOTS_UNVERIFIED_OR_DISALLOWED'
    else:
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=not args.headed)
                try:
                    context=await browser.new_context()
                    page=await context.new_page()
                    region=core.BY_KEY[args.region]
                    response=await page.goto(core.search_url(args.keyword,region),
                                             wait_until='domcontentloaded',timeout=args.timeout*1000)
                    code=response.status if response else None
                    if code in (401,403,429) or code != 200:
                        result['status']='STOP_HTTP_'+str(code)
                    else:
                        await page.wait_for_timeout(args.settle_ms)
                        html_check=await page.evaluate('''() => ({
                          regionButton: [...document.querySelectorAll('button[aria-label]')]
                            .map(x=>x.getAttribute('aria-label')||'')
                            .find(x=>x.startsWith('지역 선택:'))||'',
                          challenged: /captcha|verify you are human|access denied|비정상적인 접근/i
                            .test((document.body?.innerText||'').slice(0,3000))})''')
                        if html_check['challenged']:
                            result['status']='STOP_CHALLENGE'
                        elif core.region_id_in_url(page.url) != region['id']:
                            result['status']='STOP_REGION_URL_MISMATCH'
                        elif region['term'] not in html_check['regionButton']:
                            result['status']='STOP_REGION_UI_MISMATCH'
                        else:
                            button=page.locator('button[aria-label="필터"]')
                            if await button.count() == 0:
                                result['status']='FILTER_BUTTON_NOT_FOUND'
                            else:
                                await button.first.click(timeout=min(8000,args.timeout*1000))
                                await page.wait_for_timeout(750)
                                snap=await page.evaluate(FILTER_SNAPSHOT_JS)
                                result['snapshot']=snap
                                result['detected_filters']=summarize_filters(snap)
                                result['status']='CAPTURED_FILTER_DIALOG' if snap['panel_found'] else 'FILTER_DIALOG_NOT_LOCATED'
                    await context.close()
                finally:
                    await browser.close()
        except ImportError:
            result['status']='PLAYWRIGHT_NOT_INSTALLED'
        except Exception as exc:
            result['status']='STOP_'+type(exc).__name__
    out=Path(args.output_dir)
    out.mkdir(parents=True,exist_ok=True)
    (out/'daangn_browser_v4_4_1_filters.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'daangn_browser_v4_4_1_filters.md').write_text(render_report(result),encoding='utf-8')
    print('v4.4.1 filter inspection:',result['status'])
    print('Saved:',out/'daangn_browser_v4_4_1_filters.json')
    print('Saved:',out/'daangn_browser_v4_4_1_filters.md')
    return 0 if result['status']=='CAPTURED_FILTER_DIALOG' else 2
