# -*- coding: utf-8 -*-
"""Passive, privacy-bounded public UI stage witness after region option click.

Only fixed semantic categories and capped counts leave Playwright. Not
evidence of listing authority, not a selector for any additional click.
"""
from __future__ import annotations

_STAGES = ("AFTER_FIRST", "AFTER_FOLLOWUP_GATE",
           "AFTER_CORE_SETTLE", "AFTER_SETTLE",
           "AFTER_DELAYED_SETTLE")
_STATE = frozenset((
    "TARGET_DIALOG_CHOICE", "OTHER_DIALOG_CHOICES", "REGION_INPUT_ONLY",
    "POSSIBLE_LOGIN_GATE", "DIALOG_WITHOUT_CONTROLS", "NO_DIALOG",
    "UNOBSERVABLE",
))
_CONTROL = frozenset(("EXPECTED", "OTHER", "MISSING", "UNOBSERVABLE"))
_COUNTS = (
    "visible_dialogs", "visible_dialog_buttons", "target_dialog_buttons",
    "target_city_dialog_buttons", "target_outside_buttons",
    "other_region_dialog_buttons", "confirm_dialog_buttons",
    "login_dialog_signals", "region_dialog_inputs", "busy_signals",
)

_JS = r"""meta => {
  const seen=e=>{
    if(!e?.isConnected)return false;
    try {
      const s=getComputedStyle(e);
      return !!e.getClientRects().length &&
        s.visibility!=='hidden'&&s.display!=='none';
    }catch(_){return false;}
  };
  const cap=n=>Math.min(60,n);
  const buttonQuery='button,[role="button"],[role="option"]';
  const allButtons=[...document.querySelectorAll(buttonQuery)]
    .filter(seen).slice(0,250);
  const allDialogs=[...document.querySelectorAll('[role="dialog"]')]
    .slice(0,60);
  const liveDialogs=allDialogs.filter(d=>
    seen(d)||[...d.querySelectorAll(buttonQuery+',input')].slice(0,250)
      .some(seen));
  const inside=el=>!!el.closest('[role="dialog"]') &&
    liveDialogs.includes(el.closest('[role="dialog"]'));
  const dialogButtons=allButtons.filter(inside);
  const term=meta.term,city=meta.city;
  const name=e=>((e.textContent||'')+' '+(e.getAttribute('aria-label')||''))
    .replace(/\s+/g,' ').trim().slice(0,200);
  const matches=e=>name(e).includes(term);
  const target=dialogButtons.filter(matches);
  const targetCity=target.filter(e=>name(e).includes(city));
  const otherRegion=dialogButtons.filter(e=>{
    const x=name(e);
    return !x.includes(term) &&
      /(?:[가-힣0-9]{1,14}(?:동|읍|면|리))(?:\s|$|[,\-·])/u.test(x);
  });
  const confirmation=dialogButtons.filter(e=>
    /^(확인|완료|적용|선택하기|이 동네로 설정|설정|다음|계속)$/.test(name(e)));
  const login=dialogButtons.filter(e=>
    /^(로그인|휴대폰 인증|본인 인증|전화번호 인증|회원가입)$/.test(name(e)));
  const inputs=[...document.querySelectorAll(
    '[role="dialog"] input,[role="dialog"] [role="combobox"]')]
    .filter(e=>seen(e)&&inside(e)).slice(0,100);
  const regionInputs=inputs.filter(e=>{
    const p=e.getAttribute('placeholder')||'';
    return /지역|동네|검색/.test(p)||e.type==='search';
  });
  const busy=[...document.querySelectorAll(
    '[role="dialog"] [role="progressbar"],[role="dialog"] [aria-busy="true"]')]
    .filter(seen).length;
  const headerControls=[...document.querySelectorAll('button[aria-label]')]
    .filter(seen).map(b=>b.getAttribute('aria-label')||'')
    .filter(x=>x.startsWith('지역 선택:'));
  const selected=headerControls.length!==1?'MISSING':
    headerControls[0].includes(term)?'EXPECTED':'OTHER';
  const loginInputs=inputs.filter(e=>{
    const p=e.getAttribute('placeholder')||'';
    return /휴대폰|전화번호|비밀번호|인증/.test(p);
  });
  const state=!liveDialogs.length?'NO_DIALOG':
    login.length>0||loginInputs.length>0?'POSSIBLE_LOGIN_GATE':
    target.length>0?'TARGET_DIALOG_CHOICE':
    otherRegion.length>0?'OTHER_DIALOG_CHOICES':
    regionInputs.length>0?'REGION_INPUT_ONLY':
    'DIALOG_WITHOUT_CONTROLS';
  return {
    state,selected_control:selected,
    visible_dialogs:cap(liveDialogs.length),
    visible_dialog_buttons:cap(dialogButtons.length),
    target_dialog_buttons:cap(target.length),
    target_city_dialog_buttons:cap(targetCity.length),
    target_outside_buttons:cap(allButtons.filter(e=>!inside(e)&&matches(e)).length),
    other_region_dialog_buttons:cap(otherRegion.length),
    confirm_dialog_buttons:cap(confirmation.length),
    login_dialog_signals:cap(login.length+loginInputs.length),
    region_dialog_inputs:cap(regionInputs.length),
    busy_signals:cap(busy)
  };
}"""


def _safe_checkpoint(value):
    src = value if type(value) is dict else {}
    state = src.get("state")
    selected = src.get("selected_control")
    return {
        "state": state if type(state) is str and state in _STATE
                 else "UNOBSERVABLE",
        "selected_control": selected if type(selected) is str
                            and selected in _CONTROL else "UNOBSERVABLE",
        **{k: (src[k] if type(src.get(k)) is int and
               0 <= src[k] <= 60 else -1) for k in _COUNTS},
    }


def sanitize_region_lifecycle(value):
    src = value if type(value) is dict else {}
    checkpoints = src.get("checkpoints")
    checkpoints = checkpoints if type(checkpoints) is dict else {}
    return {
        "checkpoints": {
            stage: _safe_checkpoint(checkpoints.get(stage))
            for stage in _STAGES},
        "authorizes_listings": False,
    }


class RegionLifecycleWitness:
    """Four passive snapshots; no new requests or UI actions."""

    def __init__(self, region: dict):
        self.region = region
        self.checkpoints = {}

    async def checkpoint(self, page, stage: str):
        if stage not in _STAGES:
            return
        try:
            value = await page.evaluate(
                _JS, {"term": self.region["term"], "city": self.region["label"]})
        except Exception:
            value = None
        self.checkpoints[stage] = _safe_checkpoint(value)

    def export(self):
        return sanitize_region_lifecycle({"checkpoints": self.checkpoints})
