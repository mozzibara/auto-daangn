# -*- coding: utf-8 -*-
"""Read-only first-load locality, bootstrap and egress classification.

Never exports unredacted IP, source body, cookies, storage keys, session
tokens, seller fields, raw user-agent or URLs. Initial Remix loader is *not*
proof of a committed region, merely a baseline witness. External egress
geolocation is optional and explicitly opt-in (provider sees the source IP).
"""
from __future__ import annotations

import json
import os
import platform
import re
import urllib.request

from app_v5.region_lifecycle import _JS as LIFECYCLE_JS, _safe_checkpoint
from app_v5.manual_chrome_region import extract_route_summary

STAGES = ("BASELINE_DOM_READY", "BASELINE_SETTLED", "AFTER_REGION_ATTEMPT")
_REGION = frozenset(("EXPECTED", "OTHER", "MISSING", "UNOBSERVABLE"))
_LOADER = frozenset(("BOOTSTRAP_REGION_PRESENT", "BOOTSTRAP_REGION_MISSING",
                     "BOOTSTRAP_UNREADABLE"))
_CONTEXT = frozenset(("LOCAL", "GITHUB_HOSTED", "OTHER_CI"))
_COUNTRY = frozenset(("KR", "NON_KR", "UNAVAILABLE"))
_PROVIDER = frozenset(("MICROSOFT_AZURE", "ORACLE_CLOUD",
                       "AMAZON_AWS", "GOOGLE_CLOUD", "OTHER", "UNAVAILABLE"))
_STATE = frozenset(("OBSERVED", "UNAVAILABLE", "DISABLED"))
_LANGUAGE = frozenset(("KO", "OTHER", "UNAVAILABLE"))
_TIMEZONE = frozenset(("ASIA_SEOUL", "OTHER", "UNAVAILABLE"))
_MAX_ROUTE = 2_000_000

# This is an observer, never a region-selector. All values remain categoric.
_BROWSER_JS = r"""expected => {
  const same=id=>id==null?'MISSING':
    String(id)===String(expected)?'EXPECTED':'OTHER';
  const loader=window.__remixContext?.state?.loaderData;
  let candidates=[];
  if(loader && typeof loader==='object') {
    for(const [key,value] of Object.entries(loader).slice(0,45)) {
      if(!/search.*buy-sell/.test(key) || !value || typeof value!=='object')
        continue;
      candidates.push(value);
    }
  }
  let row=candidates.length===1?candidates[0]:null;
  const loc=(()=>{try{
    const x=Intl.DateTimeFormat().resolvedOptions().timeZone||'';
    return x==='Asia/Seoul'?'ASIA_SEOUL':x?'OTHER':'UNAVAILABLE';
  }catch(_){return 'UNAVAILABLE';}})();
  const lang=(()=>{try{
    const s=(navigator.language||'').toLowerCase();
    return s.startsWith('ko')?'KO':s?'OTHER':'UNAVAILABLE';
  }catch(_){return 'UNAVAILABLE';}})();
  const readable=key=>{try{return key?.length??null;}catch(_){return null;}};
  const count=n=>Number.isInteger(n)&&n>=0&&n<=200? n:-1;
  return {
    loader_status:row?'BOOTSTRAP_REGION_PRESENT':
      candidates.length===0?'BOOTSTRAP_REGION_MISSING':'BOOTSTRAP_UNREADABLE',
    loader_search_region:row?same(row.searchRegion?.id):'UNOBSERVABLE',
    loader_filter_region:row?same(row.currentFilters?.regionId):'UNOBSERVABLE',
    language:lang, timezone:loc,
    cookies_present:(()=>{try{return document.cookie.length>0;}catch(_){return false;}})(),
    local_storage_count:count((()=>{try{return localStorage.length;}catch(_){return null;}})()),
    session_storage_count:count((()=>{try{return sessionStorage.length;}catch(_){return null;}})()),
    document_visibility:document.visibilityState==='visible'?'VISIBLE':'OTHER',
    login_text_signal:/(로그인이 필요합니다|로그인 후 이용|로그인이 필요한)/.test(
       (document.body?.innerText||'').slice(0,1500)),
  };
}"""


def _enum(value, options, missing):
    return value if type(value) is str and value in options else missing


def _cap(value, maximum=200):
    return value if type(value) is int and 0 <= value <= maximum else -1


def sanitize_browser_environment(value):
    s=value if type(value) is dict else {}
    return {
        "loader_status":_enum(s.get("loader_status"),_LOADER,"BOOTSTRAP_UNREADABLE"),
        "loader_search_region":_enum(s.get("loader_search_region"),_REGION,"UNOBSERVABLE"),
        "loader_filter_region":_enum(s.get("loader_filter_region"),_REGION,"UNOBSERVABLE"),
        "language":_enum(s.get("language"),_LANGUAGE,"UNAVAILABLE"),
        "timezone":_enum(s.get("timezone"),_TIMEZONE,"UNAVAILABLE"),
        "cookies_present":s.get("cookies_present") is True,
        "local_storage_count":_cap(s.get("local_storage_count")),
        "session_storage_count":_cap(s.get("session_storage_count")),
        "document_visibility":("VISIBLE" if s.get("document_visibility")=="VISIBLE"
                               else "OTHER"),
        "login_text_signal":s.get("login_text_signal") is True,
    }


def sanitize_baseline(value):
    s=value if type(value) is dict else {}
    screen=s.get("ui") if type(s.get("ui")) is dict else {}
    env=s.get("browser") if type(s.get("browser")) is dict else {}
    route=s.get("passive_route") if type(s.get("passive_route")) is dict else {}
    return {
        "ui":_safe_checkpoint(screen),
        "initial_header_family":_enum(s.get("initial_header_family"),
                                      _HEADER_FAMILIES,"UNOBSERVABLE"),
        "browser":sanitize_browser_environment(env),
        "passive_route":{
            "count":_cap(route.get("count"),12),
            "status":_enum(route.get("status"),
                frozenset(("ONE_OBSERVED","MULTIPLE_OBSERVED",
                           "NOT_OBSERVED","UNREADABLE")), "UNREADABLE"),
            "search_region":_enum(route.get("search_region"),_REGION,"UNOBSERVABLE"),
            "filter_region":_enum(route.get("filter_region"),_REGION,"UNOBSERVABLE"),
        },
        "url_region":_enum(s.get("url_region"),_REGION,"UNOBSERVABLE"),
        "authorizes_listings":False,
    }


def summarize_passive_routes(events):
    """All input is already bounded/passively observed in volatile RAM."""
    events=events if type(events) is list else []
    found=[e for e in events if type(e) is dict
           and e.get("state")=="OBSERVED" and
           type(e.get("model")) is dict]
    if len(found)==1:
        x=found[0]["model"]
        return {"count":len(events),"status":"ONE_OBSERVED",
                "search_region":x.get("search_region"),
                "filter_region":x.get("filter_region")}
    return {"count":len(events),
            "status":"MULTIPLE_OBSERVED" if len(found)>1 else
                     "UNREADABLE" if events else "NOT_OBSERVED",
            "search_region":"UNOBSERVABLE",
            "filter_region":"UNOBSERVABLE"}


async def capture_first_load(page, region, passive_events=None):
    """Sample already-open first-party page. No navigation or mutation."""
    from app_v5.region_navigation import classify_browser_url
    try:
        ui=await page.evaluate(LIFECYCLE_JS,{
            "term":region["term"],"city":region["label"]})
    except Exception:
        ui={}
    try:
        browser=await page.evaluate(_BROWSER_JS,str(region["id"]))
    except Exception:
        browser={}
    try:
        url_class=classify_browser_url(page.url,region).get("region")
    except Exception:
        url_class="UNOBSERVABLE"
    current_header=await read_region_header_volatile(page)
    hint=classify_region_header_transition(
        current_header,current_header,target_term=region["term"])
    return sanitize_baseline({
        "ui":ui, "browser":browser,
        "initial_header_family":hint["before_header_family"],
        "url_region":url_class,
        "passive_route":summarize_passive_routes(passive_events),
    })


def safe_machine_class(*, environ=None, system=None):
    env=environ if environ is not None else os.environ
    system=system or platform.system()
    return {
        "runtime":("GITHUB_HOSTED" if env.get("GITHUB_ACTIONS")=="true"
                   else "OTHER_CI" if env.get("CI")=="true" else "LOCAL"),
        "os":("WINDOWS" if system=="Windows" else "LINUX"
              if system=="Linux" else "OTHER"),
        "http_proxy_configured":any(bool(env.get(k)) for k in (
            "HTTPS_PROXY","https_proxy","HTTP_PROXY","http_proxy","ALL_PROXY","all_proxy")),
        "authorizes_listings":False,
    }


def classify_egress_payload(payload):
    """Never print/retain the source IP or geolocated city/coordinates."""
    item=payload if type(payload) is dict else {}
    code=item.get("country_code",item.get("country"))
    country=("KR" if code=="KR" else "NON_KR"
             if type(code) is str and re.fullmatch("[A-Z]{2}",code)
             else "UNAVAILABLE")
    org=item.get("org")
    org=org.lower()[:160] if type(org) is str else ""
    provider=("MICROSOFT_AZURE" if any(k in org for k in
                ("microsoft","azure")) else
              "ORACLE_CLOUD" if "oracle" in org else
              "AMAZON_AWS" if any(k in org for k in
                ("amazon","aws")) else
              "GOOGLE_CLOUD" if "google" in org else
              "OTHER" if org else "UNAVAILABLE")
    return {"state":"OBSERVED" if country!="UNAVAILABLE" else "UNAVAILABLE",
            "country":country,"network_provider_hint":provider,
            "third_party_ip_geolocation_not_authoritative":True,
            "raw_ip_exported":False,"authorizes_listings":False}


def sanitize_egress(value):
    s=value if type(value) is dict else {}
    return {
        "state":_enum(s.get("state"),_STATE,"UNAVAILABLE"),
        "country":_enum(s.get("country"),_COUNTRY,"UNAVAILABLE"),
        "network_provider_hint":_enum(s.get("network_provider_hint"),_PROVIDER,"UNAVAILABLE"),
        "third_party_ip_geolocation_not_authoritative":True,
        "raw_ip_exported":False,"authorizes_listings":False,
    }


def optional_egress_context(*, enabled=False, getter=None):
    """An explicit one-off HTTPS request to ipapi.co, separate from Chrome.

    The third-party site necessarily sees the runner's actual outbound IP.
    Its city/postal/coordinates/raw address/ASN NEVER reach stdout/artifacts.
    """
    if not enabled:
        return sanitize_egress({"state":"DISABLED"})
    getter=getter or urllib.request.urlopen
    try:
        req=urllib.request.Request("https://ipapi.co/json/",
            headers={"User-Agent":"DaangnResearchBaseline/1.0"})
        with getter(req,timeout=8) as response:
            if response.status!=200:
                raise ValueError("EGRESS_NON200")
            blob=response.read(12_001)
        if len(blob)>12_000:
            raise ValueError("EGRESS_OVERSIZE")
        return sanitize_egress(classify_egress_payload(json.loads(blob)))
    except Exception:
        return sanitize_egress({"state":"UNAVAILABLE"})


def compare_baselines(local, hosted):
    """Pure hypothesis matrix; correlation is NOT causal attribution."""
    a=sanitize_baseline(local)
    b=sanitize_baseline(hosted)
    keys=(("ui","selected_control"),
          ("initial_header_family",None),
          ("browser","loader_search_region"),
          ("browser","loader_filter_region"),
          ("browser","timezone"),("browser","language"),
          ("browser","cookies_present"),
          ("browser","local_storage_count"),
          ("passive_route","search_region"),
          ("passive_route","filter_region"),
          ("url_region",None))
    diffs={}
    for section,key in keys:
        name=section if key is None else section+"."+key
        x=a[section] if key is None else a[section][key]
        y=b[section] if key is None else b[section][key]
        diffs[name]="SAME" if x==y else "DIFFERENT"
    return {
        "baseline_differences":diffs,
        "all_observed_initial_states_identical":all(v=="SAME" for v in diffs.values()),
        "proves_network_causation":False,
        "proves_host_causation":False,
        "authorizes_listings":False,
    }


_HEADER_JS = r"""() => {
  const visible=e=>{try{const s=getComputedStyle(e);
    return e.getClientRects().length>0 && s.display!=='none' &&
           s.visibility!=='hidden';}catch(_){return false;}};
  const headers=[...document.querySelectorAll('button[aria-label]')]
    .filter(e=>visible(e) &&
       (e.getAttribute('aria-label')||'').startsWith('지역 선택:'))
    .slice(0,20);
  if(headers.length!==1)return null;
  const label=headers[0].getAttribute('aria-label');
  // Read only the region selector, not article titles/sellers or body text.
  return typeof label==='string'?label.slice(0,180):null;
}"""


async def read_region_header_volatile(page):
    """Only Python RAM; caller must not log/serialize returned raw header."""
    try:
        value=await page.evaluate(_HEADER_JS)
        if (type(value) is str and 0<len(value)<=180 and
                value.startswith("지역 선택:")):
            return value
    except Exception:
        pass
    return None


def classify_region_header_transition(before, after, *, target_term="불당동"):
    """Sanitize raw header values into comparison flags and city buckets.

    Raw label is deliberately discarded. City-like substrings may be a UI
    hint only and cannot prove the server's actual search or seller location.
    """
    def family(value):
        if type(value) is not str or not value.startswith("지역 선택:"):
            return "UNOBSERVABLE"
        suffix=value.split(":",1)[-1].strip()
        if not suffix:
            return "UNOBSERVABLE"
        if type(target_term) is str and target_term and target_term in suffix:
            return "TARGET"
        if "천안" in suffix:
            return "CHEONAN_OTHER"
        if "아산" in suffix:
            return "ASAN"
        if "서울" in suffix:
            return "SEOUL"
        return "OTHER"
    same=(type(before) is str and type(after) is str and
          before.startswith("지역 선택:") and after.startswith("지역 선택:")
          and bool(before.split(":",1)[-1].strip())
          and bool(after.split(":",1)[-1].strip()))
    status=("UNOBSERVABLE" if not same else
            "UNCHANGED" if before==after else "CHANGED")
    return {
        "status":status,
        "before_header_family":family(before),
        "after_header_family":family(after),
        "reveals_raw_region":False,
        "proves_server_region_changed":False,
        "authorizes_listings":False,
    }


_HEADER_FAMILIES=frozenset((
    "TARGET","CHEONAN_OTHER","ASAN","SEOUL","OTHER","UNOBSERVABLE"))
_HEADER_DELTA=frozenset(("CHANGED","UNCHANGED","UNOBSERVABLE"))


def sanitize_header_transition(value):
    src=value if type(value) is dict else {}
    return {
        "status":_enum(src.get("status"),_HEADER_DELTA,"UNOBSERVABLE"),
        "before_header_family":_enum(
            src.get("before_header_family"),_HEADER_FAMILIES,"UNOBSERVABLE"),
        "after_header_family":_enum(
            src.get("after_header_family"),_HEADER_FAMILIES,"UNOBSERVABLE"),
        "reveals_raw_region":False,
        "proves_server_region_changed":False,
        "authorizes_listings":False,
    }
