# -*- coding: utf-8 -*-
"""v4.5.3 diagnostic-only filter verifier; Windows: run_v45_3.cmd --headed."""
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
PLANS=(('cheonan_a','cheonan'),('asan_a','asan'),('cheonan_b','cheonan'),('asan_b','asan'))
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

async def controls(page):
    async def one(label,kind):
        c=page.get_by_label(label,exact=True)
        if await c.count():return c.first
        c=page.locator('label').filter(has_text=re.compile('^\\s*'+re.escape(label)+'\\s*$')).locator('input[type="'+kind+'"]')
        return c.first if await c.count() else None
    cat=await one('디지털기기','radio');avail=await one('거래 가능만 보기','checkbox')
    maxp=page.get_by_placeholder('최대 가격',exact=True)
    if not await maxp.count():maxp=await one('최대 가격','text')
    return cat,avail,maxp

async def ui_state(page):
    try:
        cat,avail,maxp=await controls(page)
        missing=[key for key,loc in [('category',cat),('available',avail),('maximum',maxp)]
                 if loc is None or not await loc.count()]
        if missing:return {'complete':False,'failure_reason':'CONTROLS_NOT_LOCATED',
                           'missing_controls':missing}
        return {'complete':True,'category':await cat.is_checked(),'available':await avail.is_checked(),
                'maximum':ev.int_price(await maxp.first.input_value())}
    except Exception as ex:return {'complete':False,'failure_reason':type(ex).__name__}

def ui_ok(x):return bool(x.get('complete') and x.get('category') and x.get('available') and x.get('maximum')==50000)


async def filter_snapshot(page):
    """Read only public visible filter UI; no page HTML or private state retained."""
    try:
        result=await asyncio.wait_for(page.evaluate(FILTER_SNAPSHOT_JS),timeout=4)
        return result if isinstance(result,dict) else {}
    except Exception:
        return {}


def panel_diagnostic(s):
    labels={x.get('label','') for x in s.get('controls',[]) if isinstance(x,dict)}
    return {'panel_found':bool(s.get('panel_found')),
            'filter_trigger_found':bool(s.get('filter_trigger_found')),
            'category_label_present':'디지털기기' in labels,
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


async def set_checked_by_label(page,field,label,steps):
    """Use the visible associated label for custom-styled controls.

    A real user clicks labels. Do not force-check hidden inputs or evaluate
    JavaScript to manufacture clicks; verify the actual DOM checked property.
    """
    if await field.is_checked():return
    steps.append('SELECT_'+('CATEGORY' if label=='디지털기기' else 'AVAILABLE'))
    locator=page.locator('label').filter(has_text=re.compile(r'^\s*'+re.escape(label)+r'\s*$'))
    if await locator.count():
        await locator.first.click(timeout=6000)
    else:
        await field.check(timeout=6000)
    if not await field.is_checked():
        raise RuntimeError('FILTER_CONTROL_NOT_CHECKED')


async def set_filter(page,steps):
    steps.append('OPEN_FILTER')
    snapshot=await open_filter(page)
    steps.append('LOCATE_CONTROLS')
    cat,avail,maxp=await controls(page)
    if cat is None or avail is None or maxp is None or not await maxp.count():
        raise RuntimeError('FILTER_INPUT_MISSING')
    await set_checked_by_label(page,cat,'디지털기기',steps)
    await set_checked_by_label(page,avail,'거래 가능만 보기',steps)
    steps.append('FILL_MAX_PRICE')
    await maxp.first.fill('50000',timeout=6000)
    steps.append('COMMIT_MAX_PRICE')
    await maxp.first.press('Tab',timeout=6000)
    steps.append('CONFIRM_SELECTED_STATE')
    state=await ui_state(page)
    if not ui_ok(state):raise RuntimeError('FILTER_INPUT_NOT_CONFIRMED')
    steps.append('LOCATE_APPLY_BUTTON')
    apply=page.get_by_role('button',name='적용하기',exact=True)
    if await apply.count()!=1 or not await apply.is_enabled():raise RuntimeError('APPLY_NOT_AVAILABLE')
    return apply,state


async def check_after(page,steps=None):
    """Independently report UI observability and actual selected state.

    When the control cannot be inspected, NOT_OBSERVABLE is not equivalent to
    OBSERVED_MISMATCH. URL persistence is recorded by the caller separately.
    """
    try:
        if steps is not None:steps.append('REOPEN_FOR_PERSISTENCE')
        opened=await open_filter(page)
        if steps is not None:steps.append('CHECK_PERSISTED_SELECTION')
        state=await ui_state(page)
        state['panel_diagnostic']=panel_diagnostic(opened)
        state['observation_status']=('OBSERVED_MATCH' if ui_ok(state) else
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
                'panel_diagnostic':panel_diagnostic(await filter_snapshot(page))}

async def snap(page):return await page.evaluate(core.JS_SNAPSHOT),await page.evaluate(JS_MODEL)


def stage(name,region,step,dom,model,url,status=200,filter_evidence=None,transport='document'):
    urls=ev.model_urls(model);visible=[u for v in dom.get('dom_visible',[]) if (u:=core.normalized_listing(v))]
    rid=core.BY_KEY[region]['id'];label=core.BY_KEY[region]['term']
    region_ok=bool(model and str(model.get('region_id'))==rid and str(model.get('filter_region_id'))==rid
            and core.region_id_in_url(url)==rid and label in (dom.get('region_button') or ''))
    dom_ok=bool(visible and len(set(visible)&set(urls))/len(set(visible))>=.8)
    # Separate factual search-document integrity from filter applicability.
    # Missing filter proof is UNVERIFIED, not evidence of a corrupted response.
    core_valid=bool(status==200 and region_ok and dom_ok and urls and not dom.get('challenge')
                and not dom.get('login_wall'))
    filter_violated=bool(filter_evidence and str(filter_evidence.get('status','')).startswith('QUARANTINED_'))
    valid=core_valid and not filter_violated
    which='base' if step<=2 else 'filtered';num=1 if step in (1,3) else 2
    return {'id':f'v45_{which}:{name}:{num}:{region}','context':name,'region':region,
            'step':num,'phase':'cold_first' if num==1 else 'same_url_repeat','time':now(),
            'valid':valid,'core_valid':core_valid,
            'filter_proof_approved':bool(filter_evidence and filter_evidence.get('approved')) if filter_evidence is not None else None,
            'http_status':status,'region_ok':region_ok,'dom_ok':dom_ok,'count':len(urls),
            'set_sha256':oldgate.set_hash(oldgate.hashed_listing_ids(urls)),
            'url':ev.public_url(url),'response_filter_fields':ev.public_filters((model or {}).get('filters')),
            'filter_evidence':filter_evidence,'collector':transport,'_urls':urls,'_dom':visible}

async def document(page,args,name,region,step,url=None):
    r=await page.goto(url or core.search_url(args.keyword,core.BY_KEY[region]),wait_until='domcontentloaded',timeout=args.timeout*1000)
    await page.wait_for_timeout(args.settle_ms)
    d,m=await snap(page)
    f=None
    if step==4:
        state=await check_after(page)
        f=ev.validated_predicates(m,page.url,core.BY_KEY[region]['id'],ui_ok(state),
                                  bool(r and r.status==200),
                                  ui_observation_status=state.get('observation_status'))
    s=stage(name,region,step,d,m,page.url,r.status if r else None,f)
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
                        if m:self.events.append({'model':m,'digest':hashlib.sha256(raw).hexdigest(),'status':r.status})
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
        button,selected=await set_filter(page,steps)
        steps.append('CLICK_APPLY')
        await button.click(timeout=6000)
        steps.append('SETTLE_APPLIED_RESULTS')
        await page.wait_for_timeout(args.settle_ms)
        steps.append('READ_SEARCH_NETWORK_RESPONSES')
        await net.drain()
    finally:page.remove_listener('response',net.hook)
    steps.append('CAPTURE_APPLIED_RESULTS')
    dom,boot=await snap(page);url=page.url
    state=await check_after(page,steps)
    # SPA boot loader may be STALE. Never trust it unless a new document-style
    # filter URL was observed and the route fetch is absent.
    new_filter_query=any(k in ev.public_url(url).get('public_params',{}) for k in (*ev.CAT,*ev.MAX,*ev.ON))
    documented=bool(new_filter_query and 200 in net.document_status)
    m=net.events[-1]['model'] if net.events else boot if documented else None
    proof=ev.validated_predicates(m,url,core.BY_KEY[region]['id'],ui_ok(selected) and ui_ok(state),
                                   bool(net.events) or documented,
                                   ui_observation_status=state.get('observation_status'))
    s=stage(name,region,3,dom,m,url,200,proof,'spa_route' if net.events else 'document')
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
        keys=('q','in','category_id','only_on_sale','price')
        persisted=all(first_url.get(k)==repeat_url.get(k) and k in first_url for k in keys)
        p['ui']['url_persistence']={'status':'PERSISTED_IN_URL' if persisted else 'URL_STATE_CHANGED',
            'checked_keys':list(keys),'observed_after_navigation':True}
        core_ok=all(s['valid'] for s in p['stages'])
        proof_ok=all(s.get('filter_evidence',{}).get('approved') for s in p['stages'][2:])
        p['status']='CAPTURED_FOUR_STAGES' if core_ok and proof_ok else (
            'UNVERIFIED_FILTER_PROOF' if core_ok else 'STOP_INVALID_STAGE_EVIDENCE')
    except Exception as e:
        p['status']='STOP_'+safeerr(e);p['error']=safeerr(e)
        p['failure_phase']=p['filter_steps'][-1] if p['filter_steps'] else 'UNDETERMINED'
        p['failure_panel']=panel_diagnostic(await filter_snapshot(page))
    finally:await ctx.close()
    return p

def report(x):
    lines=['# 당근 v4.5.3 가격 파라미터·UI 재확인 진단 보고서','',
      '- 대상: 천안 불당동, `HDD` / 디지털기기 / 최대 50,000원 / 거래 가능만 보기 켜기',
      '- 아산 배방읍은 필터를 똑같이 적용하는 독립 대조군이며 승인 파일에서 제외','',
      f"- 실행: **{x['run_level']['status']}**",f"- 실행 전체 차단: **{x['run_level']['blocked']}**",
      f"- 천안 필터 적용 제한적 승인 표본: **{x['run_level']['accepted_count']}**",'',
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
       '- `price=__50000`은 해당 최대 가격 UI 입력 이후 관측된 **프런트엔드 최대값 단독 인코딩 후보**로 기록하며 서버 필터 준수의 단독 증거로 승인하지 않습니다.',
       '- 필터 증거 누락은 `UNVERIFIED`로 분류하며, URL/HTTP/DOM 오류와 구분합니다.',
       '- UI 버튼/패널 미발견은 `NOT_OBSERVABLE`, 실제 모든 선택 상태가 확인됐는데 불일치하면 `OBSERVED_MISMATCH`입니다.',
       '- 필터 URL의 재방문 유지 여부는 UI 재확인과 별도 필드(`url_persistence`)로 기록합니다.','',
       '## 검증 경계','',
       '- v4.4.1 초기 공통 목록 격리는 무필터/필터 그룹마다 별도로 적용.',
       '- 서버가 실제 필터 메타데이터를 반환하는지 미확인이라면 승인하지 않습니다.',
       '- `run_level.blocked=true`인 경우 승인 파일에 매물 URL을 내보내지 않습니다.',
       '- 가격 미상·50,000원 초과·판매 완료 명시 등은 보류/격리.',
       '- 매물 지역 정확성·전체 수집률·판매 가능 여부·자동 수집 허가는 검증되지 않았습니다.',
       '- 비로그인·무쿠키저장·무우회·제한된 요청 횟수만 사용합니다.','']
    return '\n'.join(lines)

def publish(args,plans,status,history):
    allst=[s for p in plans for s in p['stages']]
    base=[s for s in allst if s['id'].startswith('v45_base:')]
    filt=[s for s in allst if s['id'].startswith('v45_filtered:')]
    complete=(status=='CAPTURED_COMPLETE' and len(plans)==4 and len(base)==8 and len(filt)==8 and
              all(p['status']=='CAPTURED_FOUR_STAGES' for p in plans))
    last_status='CAPTURED_COMPLETE' if complete else status if status!='CAPTURED_COMPLETE' else 'STOP_INCOMPLETE'
    known=prior.historical_collision_signatures(history)
    bg=ev.gate_run(base,'v45_base',known,'CAPTURED_COMPLETE' if complete else 'STOP_INCOMPLETE')
    fg=ev.gate_run(filt,'v45_filtered',known,'CAPTURED_COMPLETE' if complete else 'STOP_INCOMPLETE')
    blocked=not complete or bg['run_level']['blocked'] or fg['run_level']['blocked']
    d={s['id']:s for s in filt}
    accept=[x for x in fg['decisions'] if not blocked and x['sample_level_allowed'] and
            x['region']=='cheonan' and x['phase']=='same_url_repeat']
    allowids={x['sample_id'] for x in accept}
    approvals=[]
    for x in accept:
        s=d[x['sample_id']];hashed=set(oldgate.hashed_listing_ids(s['_urls']))
        urls=sorted({u for u in s['_urls'] if (pid:=oldgate.stable_article_id(u)) and
                 hashlib.sha256(pid.encode('ascii')).hexdigest()[:24] in hashed})
        approvals.append({'sample_id':x['sample_id'],'region':'cheonan','verdict':x['verdict'],
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
    data={'version':'4.5.3','timestamp_utc':now(),
          'configuration':{'keyword':args.keyword,'region':'cheonan','control_region':'asan',
             'category':'디지털기기','max_price_krw':50000,'available_only':True},
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
    approved={'version':'4.5.3','run_level_blocked':blocked,'samples':approvals,'allowed_sample_count':len(approvals),
              'note':'Filtered Cheonan repeat consistency only; real sale/geography/completeness not verified.'}
    quarantine={'version':'4.5.3','run_level_blocked':blocked,'quarantined':qa,'unverified':ua,
       'not_exported_controls':ca,'samples':exclude,
       'blocked_sample_count':len(qa)+len(ua),'excluded_count':len(exclude)}
    ids_a={x['sample_id'] for x in approvals};ids_e={x['sample_id'] for x in exclude}
    ids_all={x['sample_id'] for x in bg['decisions']+fg['decisions']}
    if ids_a&ids_e or ids_a|ids_e!=ids_all or (blocked and approvals):raise ValueError('EXPORT_CONTRACT_INVALID')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    prefix='daangn_browser_v4_5_3_'
    for name,obj in [('results.json',data),('limited_accept.json',approved),('quarantine.json',quarantine)]:
        write(args.output_dir/(prefix+name),obj)
    (args.output_dir/(prefix+'report.md')).write_text(report(data),encoding='utf-8')
    print('v4.5.3:',last_status,'run_level_blocked:',blocked,'approved_cheonan:',len(approvals),
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
                for i,(name,region) in enumerate(PLANS):
                    result=await one(browser,args,name,region)
                    plans.append(result)
                    print('Context',name,result['status'],[s['count'] for s in result['stages']])
                    if result['status']=='UNVERIFIED_FILTER_PROOF':status=result['status']
                    elif result['status']!='CAPTURED_FOUR_STAGES':status=result['status'];break
                    if i<len(PLANS)-1:await asyncio.sleep(args.pause_ms/1000)
            finally:await browser.close()
    except Exception as e:status='STOP_BROWSER_'+safeerr(e)
    return publish(args,plans,status,history)

def main():
    p=argparse.ArgumentParser(description='Daangn v4.5.3 price-query and UI-persistence diagnostic')
    p.add_argument('--headed',action='store_true');p.add_argument('--keyword',default='HDD')
    p.add_argument('--output-dir',type=Path,default=ROOT);p.add_argument('--reference',type=Path,default=ROOT/'evidence/reference_runs.json')
    p.add_argument('--timeout',type=int,default=25);p.add_argument('--settle-ms',type=int,default=1600)
    p.add_argument('--pause-ms',type=int,default=1500);args=p.parse_args()
    if args.keyword!='HDD':p.error('v4.5 fixed test profile only supports HDD')
    args.timeout=max(15,min(45,args.timeout));args.settle_ms=max(800,min(4000,args.settle_ms))
    args.pause_ms=max(1000,min(8000,args.pause_ms));args.output_dir=args.output_dir.resolve()
    return asyncio.run(run(args))
if __name__=='__main__':raise SystemExit(main())
