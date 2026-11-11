# -*- coding: utf-8 -*-
"""v4.6 configurable, conservative public-search verifier. No bypass/transactions."""
import argparse,asyncio,hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
import daangn_v4_1_core as core
import daangn_browser_v4_4_1 as prior
import daangn_v4_4_gate as oldgate
import daangn_v4_5_evidence as ev
from daangn_filter_inspector import FILTER_SNAPSHOT_JS

ROOT=Path(__file__).resolve().parent
CATALOG={row['id']:row['name'] for row in json.loads((ROOT/'category_catalog_observed.json').read_text(encoding='utf-8'))['items']}
CONFIG_KEYS={'keyword','region','region_slug','control_region','control_region_slug',
             'category_id','max_price','min_price','available_only','output_dir'}


def plans_for(args):
    return (('target_a','target'),('control_a','control'),('target_b','target'),('control_b','control'))


def region_of(args, region):
    return args.regions[region]


def expected_for(args):
    return {'keyword':args.keyword,'category':args.category_name,'category_id':args.category_id,
            'max_price_krw':args.max_price,'min_price_krw':args.min_price,
            'available_only':args.available_only}

JS_MODEL=r'''() => {
 const d=window.__remixContext?.state?.loaderData||{};
 const n=d['routes/kr.search.buy-sell._index']||d[Object.keys(d).find(k=>/search.*buy-sell/.test(k))]||{};
 return {region_id:n.searchRegion?.id!=null?String(n.searchRegion.id):null,
  filter_region_id:n.currentFilters?.regionId!=null?String(n.currentFilters.regionId):null,
  filters:n.currentFilters||{}, articles:(Array.isArray(n.buySellArticles)?n.buySellArticles:[]).slice(0,650).map(x=>
  ({href:x.href||x.url||'',price:x.price,categoryId:x.categoryId??x.category_id??x.category?.id??null,
    isSoldOut:x.isSoldOut??x.soldOut??x.isSold??null}))};
}'''

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def safeerr(e):return type(e).__name__
def write(path,obj):path.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

async def controls(page,args):
    async def one(label,kind):
        c=page.get_by_label(label,exact=True)
        if await c.count():return c.first
        c=page.locator('label').filter(has_text=re.compile('^\\s*'+re.escape(label)+'\\s*$')).locator('input[type="'+kind+'"]')
        return c.first if await c.count() else None
    cat=await one(args.category_name,'radio')
    avail=await one('거래 가능만 보기','checkbox')
    maxp=page.get_by_placeholder('최대 가격',exact=True)
    if not await maxp.count():maxp=await one('최대 가격','text')
    minp=page.get_by_placeholder('최소 가격',exact=True)
    if not await minp.count():minp=await one('최소 가격','text')
    return cat,avail,maxp,minp

async def ui_state(page,args):
    try:
        cat,avail,maxp,minp=await controls(page,args)
        required=[('category',cat),('available',avail),('maximum',maxp)]
        if args.min_price:required.append(('minimum',minp))
        missing=[key for key,loc in required if loc is None or not await loc.count()]
        if missing:return {'complete':False,'failure_reason':'CONTROLS_NOT_LOCATED','missing_controls':missing}
        return {'complete':True,'category':await cat.is_checked(),'available':await avail.is_checked(),
                'maximum':ev.int_price(await maxp.first.input_value()),
                'minimum':ev.int_price(await minp.first.input_value()) if args.min_price else 0}
    except Exception as ex:return {'complete':False,'failure_reason':type(ex).__name__}

def ui_ok(x,args):
    return bool(x.get('complete') and x.get('category') and
                x.get('available') is args.available_only and
                x.get('maximum')==args.max_price and x.get('minimum')==args.min_price)


async def filter_snapshot(page):
    """Read only public visible filter UI; no page HTML or private state retained."""
    try:
        result=await asyncio.wait_for(page.evaluate(FILTER_SNAPSHOT_JS),timeout=4)
        return result if isinstance(result,dict) else {}
    except Exception:
        return {}


def panel_diagnostic(s,category_name='디지털기기'):
    labels={x.get('label','') for x in s.get('controls',[]) if isinstance(x,dict)}
    return {'panel_found':bool(s.get('panel_found')),
            'filter_trigger_found':bool(s.get('filter_trigger_found')),
            'category_label_present':category_name in labels,
            'available_label_present':'거래 가능만 보기' in labels,
            'max_price_label_present':'최대 가격' in labels,
            'apply_label_present':'적용하기' in labels}


async def find_filter_trigger(page):
    """Find one visible, actual filter button; no JS clicks or bypasses."""
    candidates=(page.locator('button[aria-label="필터"]'),
                page.get_by_role('button',name='필터',exact=True),
                page.locator('button').filter(has_text=re.compile(r'^\s*필터\s*$')))
    for loc in candidates:
        count=await loc.count()
        if not count or count>8:continue
        visible=[loc.nth(i) for i in range(count) if await loc.nth(i).is_visible()]
        if len(visible)==1:return visible[0]
    # v4.16/16.2 live evidence: after applying search filters the original
    # header button's aria-label changes (2 -> 4 characters). The same
    # public filter panel was then observed opening after clicking that
    # unique, structurally matched header BUTTON. Do not use all-name
    # substring matching: only this exact, fail-closed header shape qualifies.
    revised=page.locator('header button[aria-label*="필터"]')
    try:
        count=await revised.count()
        if count!=1:return None
        target=revised.first
        if not await target.is_visible() or not await target.is_enabled():
            return None
        safe=await target.evaluate("""e=>{
          const n=e.getAttribute('aria-label')||'';
          const b=e.getBoundingClientRect(),s=getComputedStyle(e);
          const block=/(?:초기화|해제|삭제|제거|지우기|리셋|reset|clear|remove|적용|apply|가격|카테고리|거래 가능)/i;
          return e.tagName==='BUTTON' && n.length===4 && n.includes('필터') &&
            !block.test(n) && (e.getAttribute('type')||'button')==='button' &&
            !e.disabled && e.getAttribute('aria-disabled')!=='true' &&
            s.pointerEvents!=='none' && b.width>0 && b.height>0 &&
            e.querySelectorAll('svg').length===1 &&
            e.parentElement?.tagName==='DIV' &&
            e.parentElement?.children.length===2 &&
            !!e.closest('header') && !e.closest('footer,[role="dialog"]');
        }""")
        return target if safe is True else None
    except Exception:
        return None


async def open_filter(page):
    # A route transition may replace the toolbar, leaving the button temporarily
    # unavailable. A missing trigger is NOT evidence that the filter was reset.
    snapshot=await filter_snapshot(page)
    if snapshot.get('panel_found'):return snapshot
    trigger=None
    for _ in range(8):
        trigger=await find_filter_trigger(page)
        if trigger is not None:break
        await page.wait_for_timeout(250)
    if trigger is None:raise RuntimeError('FILTER_TRIGGER_NOT_VISIBLE')
    await trigger.click(timeout=6000)
    for _ in range(12):
        snapshot=await filter_snapshot(page)
        if snapshot.get('panel_found'):return snapshot
        await page.wait_for_timeout(250)
    raise RuntimeError('FILTER_PANEL_NOT_OBSERVABLE')


async def set_checked_by_label(page,field,label,steps,desired=True):
    """Click a public label; never force hidden inputs or execute synthetic JS clicks."""
    if await field.is_checked() == desired:return
    steps.append('SET_'+('AVAILABLE' if label=='거래 가능만 보기' else 'CATEGORY'))
    locator=page.locator('label').filter(has_text=re.compile(r'^\s*'+re.escape(label)+r'\s*$'))
    if await locator.count():await locator.first.click(timeout=6000)
    else:
        if desired:await field.check(timeout=6000)
        else:await field.uncheck(timeout=6000)
    if await field.is_checked()!=desired:raise RuntimeError('FILTER_CONTROL_WRONG_STATE')


async def set_filter(page,args,steps):
    steps.append('OPEN_FILTER')
    await open_filter(page)
    steps.append('LOCATE_CONTROLS')
    cat,avail,maxp,minp=await controls(page,args)
    if cat is None or avail is None or maxp is None or not await maxp.count() or (args.min_price and (minp is None or not await minp.count())):
        raise RuntimeError('FILTER_INPUT_MISSING')
    await set_checked_by_label(page,cat,args.category_name,steps)
    await set_checked_by_label(page,avail,'거래 가능만 보기',steps,args.available_only)
    if args.min_price:
        steps.append('FILL_MIN_PRICE');await minp.first.fill(str(args.min_price),timeout=6000)
        steps.append('COMMIT_MIN_PRICE');await minp.first.press('Tab',timeout=6000)
    steps.append('FILL_MAX_PRICE');await maxp.first.fill(str(args.max_price),timeout=6000)
    steps.append('COMMIT_MAX_PRICE');await maxp.first.press('Tab',timeout=6000)
    steps.append('CONFIRM_SELECTED_STATE')
    state=await ui_state(page,args)
    if not ui_ok(state,args):raise RuntimeError('FILTER_INPUT_NOT_CONFIRMED')
    steps.append('LOCATE_APPLY_BUTTON')
    apply=page.get_by_role('button',name='적용하기',exact=True)
    if await apply.count()!=1 or not await apply.is_enabled():raise RuntimeError('APPLY_NOT_AVAILABLE')
    return apply,state


async def check_after(page,args,steps=None):
    """Independently report UI observability and actual selected state.

    When the control cannot be inspected, NOT_OBSERVABLE is not equivalent to
    OBSERVED_MISMATCH. URL persistence is recorded by the caller separately.
    """
    try:
        if steps is not None:steps.append('REOPEN_FOR_PERSISTENCE')
        opened=await open_filter(page)
        if steps is not None:steps.append('CHECK_PERSISTED_SELECTION')
        state=await ui_state(page,args)
        state['panel_diagnostic']=panel_diagnostic(opened,args.category_name)
        state['observation_status']=('OBSERVED_MATCH' if ui_ok(state,args) else
             'OBSERVED_MISMATCH' if state.get('complete') else 'PARTIAL_OBSERVATION')
        close=page.get_by_role('button',name='닫기',exact=True)
        if await close.count():
            if steps is not None:steps.append('CLOSE_FILTER')
            try:
                await close.first.click(timeout=6000)
            except Exception as close_err:
                # Closing failure does not erase an already observed selection.
                state['close_failure']=type(close_err).__name__
        return state
    except Exception as ex:
        reason=type(ex).__name__
        if isinstance(ex,RuntimeError) and str(ex) in ('FILTER_TRIGGER_NOT_VISIBLE',
                                                        'FILTER_PANEL_NOT_OBSERVABLE'):
            reason=str(ex)
        return {'complete':False,'observation_status':'NOT_OBSERVABLE',
                'failure_reason':reason,
                'panel_diagnostic':panel_diagnostic(await filter_snapshot(page),args.category_name)}

async def snap(page):return await page.evaluate(core.JS_SNAPSHOT),await page.evaluate(JS_MODEL)


def stage(args,name,region,step,dom,model,url,status=200,filter_evidence=None,
          transport='document',*,region_authority=None):
    urls=ev.model_urls(model);visible=[u for v in dom.get('dom_visible',[]) if (u:=core.normalized_listing(v))]
    meta=region_of(args,region);rid=meta['id'];label=meta['term']
    model_region_ok=bool(model and str(model.get('region_id'))==rid
                         and str(model.get('filter_region_id'))==rid)
    if region_authority is None:
        # Historical URL+visible-control proof. Never infer from the boot loader.
        region_ok=bool(model_region_ok and core.region_id_in_url(url)==rid
                       and label in (dom.get('region_button') or ''))
    else:
        # New evidence must come from a fresh, UI-triggered correlated Route.
        # False or partial proof cannot fall back to legacy URL validation.
        region_ok=bool(model_region_ok and isinstance(region_authority,dict)
                       and region_authority.get('verified') is True)
    dom_ok=bool(visible and len(set(visible)&set(urls))/len(set(visible))>=.8)
    # Separate factual search-document integrity from filter applicability.
    # Missing filter proof is UNVERIFIED, not evidence of a corrupted response.
    core_valid=bool(status==200 and region_ok and dom_ok and urls and not dom.get('challenge')
                and not dom.get('login_wall'))
    filter_violated=bool(filter_evidence and str(filter_evidence.get('status','')).startswith('QUARANTINED_'))
    valid=core_valid and not filter_violated
    which='base' if step<=2 else 'filtered';num=1 if step in (1,3) else 2
    return {'id':f'v46_{which}:{name}:{num}:{region}','context':name,'region':region,
            'step':num,'phase':'cold_first' if num==1 else 'same_url_repeat','time':now(),
            'valid':valid,'core_valid':core_valid,
            'filter_proof_approved':bool(filter_evidence and filter_evidence.get('approved')) if filter_evidence is not None else None,
            'http_status':status,'region_ok':region_ok,'dom_ok':dom_ok,'count':len(urls),
            'set_sha256':oldgate.set_hash(oldgate.hashed_listing_ids(urls)),
            'url':ev.public_url(url),'response_filter_fields':ev.public_filters((model or {}).get('filters')),
            'filter_evidence':filter_evidence,'collector':transport,'_urls':urls,'_dom':visible}

async def document(page,args,name,region,step,url=None):
    r=await page.goto(url or core.search_url(args.keyword,region_of(args,region)),wait_until='domcontentloaded',timeout=args.timeout*1000)
    await page.wait_for_timeout(args.settle_ms)
    d,m=await snap(page)
    f=None
    if step==4:
        state=await check_after(page,args)
        f=ev.validated_predicates(m,page.url,region_of(args,region)['id'],ui_ok(state,args),
                                  bool(r and r.status==200),
                                  ui_observation_status=state.get('observation_status'),expected=expected_for(args),require_response_filters=True)
    s=stage(args,name,region,step,d,m,page.url,r.status if r else None,f)
    if step==4:
        s['ui_recheck']={'observation_status':state.get('observation_status'),
                         'failure_reason':state.get('failure_reason'),
                         'panel_diagnostic':state.get('panel_diagnostic')}
    return s

class Network:
    def __init__(self):self.events=[];self.tasks=set();self.blocked=False;self.document_status=[]
    def hook(self,r):
        try:
            u=urlsplit(r.url)
            if u.hostname!='www.daangn.com' or u.path!=core.SEARCH_PATH:return
            if r.status in core.BLOCK_STATUS:self.blocked=True
            if r.request.resource_type=='document':self.document_status.append(r.status)
            if not core._is_search_route_response(r.url) or r.request.resource_type not in ('fetch','xhr'):return
            async def collect():
                try:
                    size=r.headers.get('content-length','')
                    if size.isdigit() and int(size)>core.MAX_BODY:return
                    raw=await asyncio.wait_for(r.body(),timeout=12)
                    if r.status==200 and len(raw)<=core.MAX_BODY:
                        m=ev.extract_model(raw)
                        if m:self.events.append({'model':m,'digest':hashlib.sha256(raw).hexdigest(),'status':r.status,
                                              'public_request':ev.public_url(r.url)})
                except Exception:pass
            task=asyncio.create_task(collect());self.tasks.add(task);task.add_done_callback(self.tasks.discard)
        except Exception:pass
    async def drain(self):
        if self.tasks:
            try:await asyncio.wait_for(asyncio.gather(*list(self.tasks),return_exceptions=True),timeout=14)
            except asyncio.TimeoutError:pass

async def apply_filter(page,args,name,region,steps):
    net=Network();page.on('response',net.hook)
    try:
        button,selected=await set_filter(page,args,steps)
        steps.append('CLICK_APPLY')
        await button.click(timeout=6000)
        steps.append('SETTLE_APPLIED_RESULTS')
        await page.wait_for_timeout(args.settle_ms)
        steps.append('READ_SEARCH_NETWORK_RESPONSES')
        await net.drain()
    finally:page.remove_listener('response',net.hook)
    steps.append('CAPTURE_APPLIED_RESULTS')
    dom,boot=await snap(page);url=page.url
    state=await check_after(page,args,steps)
    # SPA boot loader may be STALE. Never trust it unless a new document-style
    # filter URL was observed and the route fetch is absent.
    new_filter_query=any(k in ev.public_url(url).get('public_params',{}) for k in (*ev.CAT,*ev.MAX,*ev.ON))
    documented=bool(new_filter_query and 200 in net.document_status)
    m=net.events[-1]['model'] if net.events else boot if documented else None
    proof=ev.validated_predicates(m,url,region_of(args,region)['id'],ui_ok(selected,args) and ui_ok(state,args),
                                   bool(net.events) or documented,
                                   ui_observation_status=state.get('observation_status'),expected=expected_for(args),require_response_filters=True)
    s=stage(args,name,region,3,dom,m,url,200,proof,'spa_route' if net.events else 'document')
    s['observed_route_response_sha256']=[e['digest'] for e in net.events[-2:]]
    return s,{'selected':selected,'after':state,'fetch_count':len(net.events),
              'document_statuses':net.document_status[-3:],'blocked':net.blocked}

async def one(browser,args,name,region):
    ctx=await browser.new_context(locale='ko-KR',viewport={'width':1280,'height':850})
    page=await ctx.new_page();page.set_default_timeout(args.timeout*1000)
    p={'context':name,'region':region,'status':'INCOMPLETE','stages':[],'ui':{},'error':None,
       'failure_phase':None,'filter_steps':[],'failure_panel':None}
    try:
        for i in (1,2):
            p['filter_steps'].append('BASELINE_DOCUMENT_'+str(i))
            s=await document(page,args,name,region,i);p['stages'].append(s)
            if not s['valid']:p['status']='STOP_BASELINE_INVALID';return p
            await asyncio.sleep(args.pause_ms/1000)
        s,ui=await apply_filter(page,args,name,region,p['filter_steps']);p['stages'].append(s);p['ui']=ui
        if ui['blocked']:p['status']='STOP_ACCESS_RESTRICTED';return p
        await asyncio.sleep(args.pause_ms/1000)
        p['filter_steps'].append('FILTERED_DOCUMENT_REPEAT')
        p['stages'].append(await document(page,args,name,region,4,page.url))
        first_url=p['stages'][2]['url'].get('public_params',{})
        repeat_url=p['stages'][3]['url'].get('public_params',{})
        keys=['q','in','category_id','price'] + (['only_on_sale'] if args.available_only else [])
        persisted=all(first_url.get(k)==repeat_url.get(k) and k in first_url for k in keys)
        p['ui']['url_persistence']={'status':'PERSISTED_IN_URL' if persisted else 'URL_STATE_CHANGED',
            'checked_keys':list(keys),'observed_after_navigation':True}
        core_ok=all(s['valid'] for s in p['stages'])
        proof_ok=persisted and all(s.get('filter_evidence',{}).get('approved') for s in p['stages'][2:])
        p['status']='CAPTURED_FOUR_STAGES' if core_ok and proof_ok else (
            'UNVERIFIED_FILTER_PROOF' if core_ok else 'STOP_INVALID_STAGE_EVIDENCE')
    except Exception as e:
        p['status']='STOP_'+safeerr(e);p['error']=safeerr(e)
        p['failure_phase']=p['filter_steps'][-1] if p['filter_steps'] else 'UNDETERMINED'
        p['failure_panel']=panel_diagnostic(await filter_snapshot(page),args.category_name)
    finally:await ctx.close()
    return p

def report(x):
    lines=['# 당근 v4.6 범용 검색·필터 검증 보고서','',
      f"- 대상: {x['configuration']['keyword']} / 지역 {x['configuration']['region']['label']} / 카테고리 {x['configuration']['category']} / 최대 {x['configuration']['max_price_krw']}원",
      f"- 비교 지역: {x['configuration']['control_region']['label']} (승인 파일에서 제외)",'',
      f"- 실행: **{x['run_level']['status']}**",f"- 실행 전체 차단: **{x['run_level']['blocked']}**",
      f"- 대상 지역의 제한적 승인 표본: **{x['run_level']['accepted_count']}**",'',
      '## 컨텍스트별 필터 검증','',
      '| 컨텍스트 | 지역 | 기준 첫/재방문 | 필터 적용/재방문 | price 쿼리 값 | UI 재확인 | URL 재방문 | 증거 수준 | 필터 입증 상태 |',
      '|---|---|---|---|---|---|---|---|---|']
    for p in x['plans']:
        st=p['stages'];counts=[str(z['count']) for z in st]+['-']*4
        evidence=st[2].get('filter_evidence',{}) if len(st)>2 else {}
        price_query=((evidence or {}).get('url') or {}).get('price_query_evidence') or {}
        price_value=price_query.get('safe_value') if price_query.get('present') else '-'
        if price_value is None:price_value='키 있음·값 기록 제한'
        after=(p.get('ui') or {}).get('after') or {}
        after_status=after.get('observation_status') or 'NOT_CAPTURED'
        url_status=((p.get('ui') or {}).get('url_persistence') or {}).get('status','NOT_CAPTURED')
        tier=evidence.get('evidence_tier','NOT_CAPTURED')
        lines.append(f"| {p['context']} | {p['region']} | {counts[0]}/{counts[1]} | {counts[2]}/{counts[3]} | {price_value} | {after_status} | {url_status} | {tier} | {evidence.get('status','NOT_CAPTURED')} |")
    failures=[p for p in x['plans'] if p.get('failure_phase')]
    if failures:
        lines+=['','## 중단 단계 진단','']
        for p in failures:
            lines.append(f"- `{p['context']}`: `{p['failure_phase']}` / `{p['error']}` / 공개 필터 UI: {p.get('failure_panel')}")
    lines+=['','## 상품 집합 전후 비교','',
            '| 컨텍스트 | 무필터 재방문→필터 UI 적용 | 필터 UI 적용→필터 재방문 |','|---|---|---|']
    for k,val in x['comparisons'].items():
        a=val.get('before_after') or {};b=val.get('post_repeat') or {}
        lines.append(f"| {k} | J={a.get('jaccard')} / 제거 {a.get('removed')} / 추가 {a.get('added')} | J={b.get('jaccard')} |")
    lines+=['','## 핵심 진단 주의','',
       '- `price=__<금액>`은 최대 가격 UI 이후 관측된 형식 후보로만 기록하며 서버 가격 필터의 단독 증거로 사용하지 않습니다.',
       '- 필터 증거 누락은 `UNVERIFIED`로 분류하며, URL/HTTP/DOM 오류와 구분합니다.',
       '- UI 버튼/패널 미발견은 `NOT_OBSERVABLE`, 실제 모든 선택 상태가 확인됐는데 불일치하면 `OBSERVED_MISMATCH`입니다.',
       '- 필터 URL의 재방문 유지 여부는 UI 재확인과 별도 필드(`url_persistence`)로 기록합니다.','',
       '## 검증 경계','',
       '- v4.4.1 초기 공통 목록 격리는 무필터/필터 그룹마다 별도로 적용.',
       '- 서버가 실제 필터 메타데이터를 반환하는지 미확인이라면 승인하지 않습니다.',
       '- `run_level.blocked=true`인 경우 승인 파일에 매물 URL을 내보내지 않습니다.',
       '- 가격 미상·요청한 가격 범위 밖·판매 완료 명시 등은 보류/격리.',
       '- 매물 지역 정확성·전체 수집률·판매 가능 여부·자동 수집 허가는 검증되지 않았습니다.',
       '- 비로그인·무쿠키저장·무우회·제한된 요청 횟수만 사용합니다.','']
    return '\n'.join(lines)

def publish(args,plans,status,history):
    allst=[s for p in plans for s in p['stages']]
    base=[s for s in allst if s['id'].startswith('v46_base:')]
    filt=[s for s in allst if s['id'].startswith('v46_filtered:')]
    complete=(status=='CAPTURED_COMPLETE' and len(plans)==4 and len(base)==8 and len(filt)==8 and
              all(p['status']=='CAPTURED_FOUR_STAGES' for p in plans))
    last_status='CAPTURED_COMPLETE' if complete else status if status!='CAPTURED_COMPLETE' else 'STOP_INCOMPLETE'
    known=prior.historical_collision_signatures(history)
    bg=ev.gate_run(base,'v46_base',known,'CAPTURED_COMPLETE' if complete else 'STOP_INCOMPLETE',region_ids={k:v['id'] for k,v in args.regions.items()},keyword=args.keyword)
    fg=ev.gate_run(filt,'v46_filtered',known,'CAPTURED_COMPLETE' if complete else 'STOP_INCOMPLETE',region_ids={k:v['id'] for k,v in args.regions.items()},keyword=args.keyword)
    blocked=not complete or bg['run_level']['blocked'] or fg['run_level']['blocked']
    d={s['id']:s for s in filt}
    accept=[x for x in fg['decisions'] if not blocked and x['sample_level_allowed'] and
            x['region']=='target' and x['phase']=='same_url_repeat']
    allowids={x['sample_id'] for x in accept}
    approvals=[]
    for x in accept:
        s=d[x['sample_id']];hashed=set(oldgate.hashed_listing_ids(s['_urls']))
        urls=sorted({u for u in s['_urls'] if (pid:=oldgate.stable_article_id(u)) and
                 hashlib.sha256(pid.encode('ascii')).hexdigest()[:24] in hashed})
        approvals.append({'sample_id':x['sample_id'],'region':args.regions['target']['label'],'verdict':x['verdict'],
               'sample_level_allowed':True,'public_listing_urls':urls,
               'listing_id_hashes':sorted(hashed),'set_sha256':x['set_sha256'],
               'filter_proof':s['filter_evidence']})
    exclude=[]
    for x in bg['decisions']+fg['decisions']:
        if x['sample_id'] in allowids:continue
        reason='CONTROL_NOT_EXPORTED' if x['sample_level_allowed'] else ('QUARANTINED' if x['verdict'].startswith('QUARANTINED') else 'UNVERIFIED')
        exclude.append({'sample_id':x['sample_id'],'region':x['region'],
          'verdict':x['verdict'],'reason':reason,'target_export_allowed':False,'why':x['why']})
    qa=[x for x in exclude if x['reason']=='QUARANTINED'];ua=[x for x in exclude if x['reason']=='UNVERIFIED'];ca=[x for x in exclude if x['reason']=='CONTROL_NOT_EXPORTED']
    comp={}
    for p in plans:
        xs=p['stages'];comp[p['context']]={
           'before_after':ev.compare(xs[1]['_urls'],xs[2]['_urls']) if len(xs)>2 else None,
           'post_repeat':ev.compare(xs[2]['_urls'],xs[3]['_urls']) if len(xs)>3 else None}
    data={'version':'4.6','timestamp_utc':now(),
          'configuration':{'keyword':args.keyword,'region':args.regions['target'],
             'control_region':args.regions['control'],'category':args.category_name,
             'category_id':args.category_id,'max_price_krw':args.max_price,
             'min_price_krw':args.min_price,'available_only':args.available_only},
          'run_level':{'status':last_status,'blocked':blocked,'accepted_count':len(approvals)},
          'plans':[{'context':p['context'],'region':p['region'],'status':p['status'],
                    'ui':p['ui'],'error':p['error'],
                    'filter_steps':p.get('filter_steps',[]),
                    'failure_phase':p.get('failure_phase'),
                    'failure_panel':p.get('failure_panel'),
                    'stages':[{k:v for k,v in s.items() if not k.startswith('_')} for s in p['stages']]}
                   for p in plans],
          'baseline_gate':bg,'filtered_gate':fg,'comparisons':comp,
          'historic_bad_signatures_checked':len(known),'private_credentials_stored':False}
    approved={'version':'4.6','approved_for_automated_purchase':False,
              'approved_for_geographic_assertions':False,'run_level_blocked':blocked,'samples':approvals,'allowed_sample_count':len(approvals),
              'note':'Filtered target repeat consistency only; real sale/geography/completeness not verified.'}
    quarantine={'version':'4.6','run_level_blocked':blocked,'quarantined':qa,'unverified':ua,
       'not_exported_controls':ca,'samples':exclude,
       'blocked_sample_count':len(qa)+len(ua),'excluded_count':len(exclude)}
    ids_a={x['sample_id'] for x in approvals};ids_e={x['sample_id'] for x in exclude}
    ids_all={x['sample_id'] for x in bg['decisions']+fg['decisions']}
    if ids_a&ids_e or ids_a|ids_e!=ids_all or (blocked and approvals):raise ValueError('EXPORT_CONTRACT_INVALID')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    prefix='daangn_browser_v4_6_'
    for name,obj in [('results.json',data),('limited_accept.json',approved),('quarantine.json',quarantine)]:
        write(args.output_dir/(prefix+name),obj)
    (args.output_dir/(prefix+'report.md')).write_text(report(data),encoding='utf-8')
    print('v4.6:',last_status,'run_level_blocked:',blocked,'approved_target:',len(approvals),
       'quarantined:',len(qa),'unverified:',len(ua),'controls_not_exported:',len(ca))
    return 0 if complete else 2

async def run(args):
    history=prior.evidence_reference(args.reference)
    robots=core.public_robots_check(args.keyword)
    if not robots.get('allowed'):return publish(args,[],'STOP_ROBOTS_UNVERIFIED_OR_DISALLOWED',history)
    try:from playwright.async_api import async_playwright
    except ImportError:return publish(args,[],'PLAYWRIGHT_NOT_INSTALLED',history)
    plans=[];status='CAPTURED_COMPLETE'
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=not args.headed)
            try:
                for i,(name,region) in enumerate(plans_for(args)):
                    result=await one(browser,args,name,region)
                    plans.append(result)
                    print('Context',name,result['status'],[s['count'] for s in result['stages']])
                    if result['status']=='UNVERIFIED_FILTER_PROOF':status=result['status']
                    elif result['status']!='CAPTURED_FOUR_STAGES':status=result['status'];break
                    if i<len(plans_for(args))-1:await asyncio.sleep(args.pause_ms/1000)
            finally:await browser.close()
    except Exception as e:status='STOP_BROWSER_'+safeerr(e)
    return publish(args,plans,status,history)

def main():
    p=argparse.ArgumentParser(description='Daangn v4.6 configurable public search filter diagnostic')
    p.add_argument('--config',type=Path,help='UTF-8 JSON settings file (optional)')
    p.add_argument('--headed',action='store_true')
    for name in ('keyword','region','region-slug','control-region','control-region-slug',
                 'category-id','max-price','min-price','output-dir'):
        p.add_argument('--'+name,default=None)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--available-only',action='store_true',default=None)
    mode.add_argument('--include-sold',action='store_true',default=False)
    p.add_argument('--reference',type=Path,default=ROOT/'evidence/reference_runs.json')
    p.add_argument('--timeout',type=int,default=25)
    p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--pause-ms',type=int,default=1500)
    args=p.parse_args()
    config={}
    if args.config is not None:
        try:
            config=json.loads(args.config.read_text(encoding='utf-8'))
        except (OSError,ValueError) as e:p.error('cannot read config JSON: '+type(e).__name__)
        if not isinstance(config,dict) or set(config)-CONFIG_KEYS:p.error('config contains unsupported fields')
        if 'available_only' in config and type(config['available_only']) is not bool:
            p.error('available_only must be a JSON boolean')
        for key in ('max_price','min_price','category_id'):
            if key in config and (type(config[key]) is not int):
                p.error(key+' must be a JSON integer')
        for key in ('keyword','region','region_slug','control_region','control_region_slug','output_dir'):
            if key in config and type(config[key]) is not str:
                p.error(key+' must be a JSON string')
    def val(key,default):
        key_arg=key.replace('-','_')
        override=getattr(args,key_arg)
        return override if override is not None else config.get(key_arg,default)
    args.keyword=str(val('keyword','HDD')).strip()
    if not 1<=len(args.keyword)<=60 or any(c in args.keyword for c in ('\r','\n','\x00')):
        p.error('keyword must contain 1..60 characters, no control newlines')
    args.regions={}
    for k,flag in [('target','region'),('control','control-region')]:
        preset=str(val(flag,'cheonan' if k=='target' else 'asan')).strip()
        if not 1<=len(preset)<=40 or any(c in preset for c in ('\r','\n','\x00','|')):
            p.error('region label must be 1..40 characters, without newlines or pipes')
        slug=val(flag+'-slug',None)
        if slug is None and preset in core.BY_KEY and core.BY_KEY[preset]['id']:
            args.regions[k]=dict(core.BY_KEY[preset]);continue
        if slug is None:p.error('custom region requires --'+flag+'-slug with public name-id')
        slug=str(slug).strip()
        m=re.fullmatch(r'([\w\uac00-\ud7a3 ()·.]{1,40})-([0-9]{1,12})',slug)
        if not m:p.error('invalid '+flag+'-slug; expected name-id e.g. 불당동-2292')
        args.regions[k]={'key':k,'label':preset,'term':m.group(1),'id':m.group(2),'slug':slug}
    if args.regions['target']['id']==args.regions['control']['id']:
        p.error('target and control must have distinct region IDs')
    try:
        args.category_id=int(val('category-id',1))
        args.max_price=int(val('max-price',50000))
        args.min_price=int(val('min-price',0))
    except (TypeError,ValueError):p.error('category id and price bounds must be integers')
    if args.category_id not in CATALOG:p.error('category id not in observed catalog')
    args.category_name=CATALOG[args.category_id]
    if not (1<=args.max_price<=999_999_999 and 0<=args.min_price<=args.max_price):
        p.error('price range invalid or outside 0..999999999')
    args.available_only=(False if args.include_sold else True if args.available_only else
                         bool(config.get('available_only',True)))
    args.output_dir=Path(val('output-dir','v46_output')).resolve()
    args.timeout=max(15,min(45,args.timeout))
    args.settle_ms=max(800,min(4000,args.settle_ms))
    args.pause_ms=max(1000,min(8000,args.pause_ms))
    return asyncio.run(run(args))

if __name__=='__main__':raise SystemExit(main())
