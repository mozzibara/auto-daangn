# -*- coding: utf-8 -*-
"""v4.34 exact-item primary title + URL as a PRIVATE, encrypted shortlist.

Public study outputs NEVER contain listing URLs, titles or stable article IDs.
Private data lives only in capture process memory until sealed for the intended
recipient's one-time X25519 public key. The private key never reaches GitHub.

Same-run HMAC + exact URL + same Route price is mandatory. No client-side title
lookup from suggested-card DOM, and no unauthenticated or guessed article URLs.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from daangn_v4_1_core import normalized_listing
from daangn_v4_4_gate import stable_article_id
from app_v5.item_area_policy import (
    ALLOWED as ITEM_AREA_ALLOWED, configured_label,
)

VERSION='4.34'
CONTEXTS=frozenset({'cheonan_a','cheonan_b'})
HMAC_PATTERN=re.compile(r'^[a-f0-9]{20}$')
AAD=b'auto-daangn/v4.34/encrypted-private-links/v1'
HKDF_INFO=b'auto-daangn-v434-x25519-aes256-gcm'
MAX_TITLE=140
TITLE_JS=r"""() => {
  const own=document.querySelector('main article')||document.querySelector('main');
  if (!own) return {status:'NO_PRIMARY_ARTICLE',matches:0};
  const visible=e=>{
    const r=e.getBoundingClientRect(),s=getComputedStyle(e);
    return r.width>0&&r.height>0&&e.getClientRects().length>0&&
      s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0';
  };
  const h=[...own.querySelectorAll('h1')]
    .filter(e=>visible(e)&&!e.closest('[data-testid*="recommend"],[class*="recommend"]'));
  if(h.length!==1)return {status:'AMBIGUOUS_PRIMARY_H1',matches:h.length};
  return {status:'PRIMARY_VISIBLE_H1',matches:1,
          text:String(h[0].innerText||h[0].textContent||'').slice(0,600)};
}"""


def clean_title(value):
    """Normalize human-visible primary heading; do not accept HTML/JS."""
    if not isinstance(value,str) or not value:
        return None
    s=unicodedata.normalize('NFC',value)
    if any(ord(c)<32 and c not in ('\n','\r','\t') for c in s):
        return None
    s=re.sub(r'\s+',' ',s).strip()
    if not (2<=len(s)<=MAX_TITLE) or any(c in s for c in ('<','>','\x00')):
        return None
    # This is untrusted seller-authored display text, never an instruction.
    return s


async def capture_primary_title(page,expected_url):
    """Only read a unique visible H1 inside the CURRENT exact detail page."""
    if normalized_listing(getattr(page,'url',None))!=expected_url:
        return {'status':'WRONG_LISTING_URL','title':None}
    try:
        x=await page.evaluate(TITLE_JS)
        if normalized_listing(getattr(page,'url',None))!=expected_url:
            return {'status':'IDENTITY_CHANGED_DURING_TITLE_PROBE','title':None}
        if not isinstance(x,dict) or x.get('status')!='PRIMARY_VISIBLE_H1' or (
            x.get('matches')!=1):
            return {'status':'PRIMARY_H1_NOT_UNIQUE','title':None}
        title=clean_title(x.get('text'))
        return {'status':'PRIMARY_H1_VERIFIED' if title else 'TITLE_INVALID',
                'title':title}
    except Exception:
        return {'status':'PRIMARY_H1_PROBE_ERROR','title':None}


def _base64(data):
    return base64.b64encode(data).decode('ascii')


def validate_public_key(encoded):
    if not isinstance(encoded,str) or len(encoded)>80:
        raise ValueError('INVALID_RECIPIENT_PUBLIC_KEY')
    try:
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)!=32:
            raise ValueError('INVALID_RECIPIENT_PUBLIC_KEY_LENGTH')
        public=X25519PublicKey.from_public_bytes(raw)
        return public
    except (ValueError,TypeError,binascii.Error) as e:
        raise ValueError('INVALID_RECIPIENT_PUBLIC_KEY') from e


def _source_key(x):
    if not isinstance(x,dict):
        raise ValueError('INVALID_PRIVATE_SOURCE_RECORD')
    context=x.get('context')
    rank=x.get('source_rank')
    if context not in CONTEXTS or type(rank) is not int or not 0<=rank<=650:
        raise ValueError('INVALID_PRIVATE_CONTEXT_OR_RANK')
    token=x.get('listing_run_hmac')
    if not isinstance(token,str) or HMAC_PATTERN.fullmatch(token) is None:
        raise ValueError('MISSING_EXACT_LISTING_HMAC')
    price=x.get('price_krw')
    if type(price) is not int or not 0<=price<=50000:
        raise ValueError('INVALID_PRIVATE_ROUTE_PRICE')
    raw=x.get('url')
    if not isinstance(raw,str) or normalized_listing(raw)!=raw or not (
        stable_article_id(raw)):
        raise ValueError('INVALID_PRIVATE_CANONICAL_URL')
    return (context,rank)


def make_private_shortlist(evaluation,sink):
    """One title/URL per v4.33 unique HMAC, never by price or search rank.

    A malformed source aborts. Missing or conflicting title for an otherwise
    valid candidate quarantines that group rather than fabricating a title.
    """
    if not isinstance(evaluation,dict) or evaluation.get('dedup_complete') is not True:
        raise ValueError('V433_UNIQUE_EVIDENCE_NOT_COMPLETE')
    uniques=evaluation.get('unique_candidates')
    if not isinstance(uniques,list) or evaluation.get('unique_candidate_count')!=len(uniques):
        raise ValueError('V433_UNIQUE_COUNT_MISMATCH')
    if not isinstance(sink,list):
        raise ValueError('NO_SAME_RUN_CAPTURED_PRIVATE_SOURCES')
    by_source={}
    for x in sink:
        key=_source_key(x)
        if key in by_source:
            raise ValueError('DUPLICATE_PRIVATE_SOURCE_ROW')
        by_source[key]=x
    approved=[]
    quarantined=[]
    seen_ids=set()
    assigned=set()
    for item in uniques:
        if not isinstance(item,dict):
            raise ValueError('INVALID_UNIQUE_RECORD')
        tag=item.get('listing_run_hmac')
        group=item.get('observations')
        if (not isinstance(tag,str) or HMAC_PATTERN.fullmatch(tag) is None or
            not isinstance(group,list) or
            type(item.get('price_krw')) is not int or
            item.get('status')!='UNIQUE_RECOMMENDATION_CANDIDATE_READY_FOR_REVIEW'
            or len(group)!=item.get('observation_count') or not group):
            raise ValueError('INVALID_UNIQUE_GROUP')
        area_key=item.get('item_area_key')
        area_label=(configured_label(area_key) if area_key is not None else None)
        if area_key is not None and area_label is None:
            raise ValueError('INVALID_ALLOWLIST_ITEM_AREA')
        titles=set()
        ids=set()
        urls=set()
        reason_codes=set()
        for obs in group:
            key=(obs.get('context'),obs.get('source_rank'))
            if key in assigned:
                raise ValueError('OBSERVATION_ASSIGNED_MORE_THAN_ONCE')
            assigned.add(key)
            x=by_source.get(key)
            if (x is None or x.get('listing_run_hmac')!=tag or
                x.get('price_krw')!=item['price_krw']):
                raise ValueError('PRIVATE_IDENTITY_PRICE_HMAC_MISMATCH')
            if area_key is not None and (
                    x.get('item_area_key')!=area_key or
                    x.get('item_area_status')!=ITEM_AREA_ALLOWED):
                raise ValueError('PRIVATE_ITEM_AREA_IDENTITY_CONFLICT')
            if area_key is None and x.get('item_area_key') is not None:
                raise ValueError('PRIVATE_ITEM_AREA_UNMATCHED')
            ids.add(stable_article_id(x['url']))
            urls.add(x['url'])
            title=clean_title(x.get('title'))
            if x.get('title_status')!='PRIMARY_H1_VERIFIED' or not title:
                reason_codes.add('MISSING_VERIFIED_VISIBLE_PRIMARY_TITLE')
            else:
                titles.add(title)
        if len(ids)!=1 or len(urls)!=1:
            raise ValueError('CROSS_CONTEXT_CANONICAL_LISTING_ID_MISMATCH')
        if len(titles)!=1:
            reason_codes.add('TITLE_UNAVAILABLE_OR_CONFLICTING_REPEATED_TITLE')
        article_id=next(iter(ids))
        if article_id in seen_ids:
            raise ValueError('SAME_CANONICAL_ITEM_SPLIT_ACROSS_HMAC_GROUPS')
        seen_ids.add(article_id)
        if reason_codes:
            quarantined.append({'observation_count':len(group),
                                'reason_codes':sorted(reason_codes)})
        else:
            entry={
                'title':next(iter(titles)),
                'url':next(iter(urls)),
                'price_krw':item['price_krw'],
                'category':item['category'],
                'availability':item['display_sale_status'],
                'observation_count':len(group),
                'full_recommendation_approved':False,
                'seller_confirmed_available':False,
                'captured_from_current_primary_h1':True}
            if area_label is not None:
                # Only ciphertext carries this per-item district label.
                entry.update(item_area_key=area_key,
                             item_area_display=area_label)
            approved.append(entry)
    if len(approved)+len(quarantined)!=len(uniques):
        raise ValueError('MISSING_UNIQUE_CANDIDATE_GROUP')
    approved.sort(key=lambda x:(x['price_krw'],x['url']))
    return {
        'version':VERSION,'capture_scoped_only':True,
        'created_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'clickable_unique_count':len(approved),
        'unlinked_title_quarantine_count':len(quarantined),
        'source_run_unique_candidates':len(uniques),
        'items':approved,'unlinked_groups':quarantined,
        'manual_current_price_and_status_recheck_required':True,
        'full_recommendations_approved':0}


def seal_manifest(manifest,recipient_key_base64):
    """Ephemeral X25519 DH -> HKDF -> AES-256-GCM authenticated envelope."""
    recipient=validate_public_key(recipient_key_base64)
    ephemeral=X25519PrivateKey.generate()
    shared=ephemeral.exchange(recipient)
    aes_key=HKDF(algorithm=hashes.SHA256(),length=32,salt=None,
                 info=HKDF_INFO).derive(shared)
    nonce=os.urandom(12)
    plaintext=json.dumps(manifest,ensure_ascii=False,
                         separators=(',',':')).encode('utf-8')
    ciphertext=AESGCM(aes_key).encrypt(nonce,plaintext,AAD)
    return {'version':VERSION,
        'envelope':'X25519-HKDF-SHA256-AES256-GCM',
        'ephemeral_public_key':_base64(ephemeral.public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)),
        'nonce':_base64(nonce),'ciphertext':_base64(ciphertext),
        'plaintext_not_archived':True}


def unseal_manifest(envelope,recipient_private_raw):
    """Local-only decrypt helper for user-owned receiver key."""
    if not isinstance(envelope,dict) or envelope.get('version')!=VERSION:
        raise ValueError('INVALID_ENVELOPE')
    if not isinstance(recipient_private_raw,bytes) or len(recipient_private_raw)!=32:
        raise ValueError('INVALID_RECIPIENT_PRIVATE_KEY')
    try:
        eph_raw=base64.b64decode(envelope['ephemeral_public_key'],validate=True)
        nonce=base64.b64decode(envelope['nonce'],validate=True)
        encrypted=base64.b64decode(envelope['ciphertext'],validate=True)
        shared=X25519PrivateKey.from_private_bytes(
            recipient_private_raw).exchange(X25519PublicKey.from_public_bytes(eph_raw))
        aes_key=HKDF(algorithm=hashes.SHA256(),length=32,
                     salt=None,info=HKDF_INFO).derive(shared)
        plain=AESGCM(aes_key).decrypt(nonce,encrypted,AAD)
        data=json.loads(plain)
        if data.get('version')!=VERSION:
            raise ValueError('DECRYPTED_MANIFEST_VERSION_MISMATCH')
        return data
    except (KeyError,TypeError,ValueError,binascii.Error,InvalidTag) as e:
        raise ValueError('INVALID_OR_UNAUTHENTICATED_SEALED_MANIFEST') from e


def write_sealed(evaluation,sink,recipient_key_base64,outdir):
    """Write ONLY authenticated ciphertext and non-identifying counts to disk."""
    manifest=make_private_shortlist(evaluation,sink)
    envelope=seal_manifest(manifest,recipient_key_base64)
    outdir=Path(outdir).resolve()
    outdir.mkdir(parents=True,exist_ok=True)
    secure=outdir/'v434_private_candidate_links.encrypted.json'
    with secure.open('x',encoding='utf-8') as stream:
        json.dump(envelope,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    summary={'version':VERSION,'status':'SEALED_PRIVATE_CANDIDATES_COMPLETE',
        'capture_scoped_only':True,
        'unique_candidates':manifest['source_run_unique_candidates'],
        'linked_unique_candidates':manifest['clickable_unique_count'],
        'quarantined_title_groups':manifest['unlinked_title_quarantine_count'],
        'plaintext_urls_or_titles_in_artifacts':False,
        'key_material_on_github':False,'manual_current_recheck_required':True,
        'full_recommendations_approved':0}
    (outdir/'v434_secure_links_summary.json').write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+'\n',
        encoding='utf-8')
    return summary


def write_local_clickable(evaluation,sink,target,public_dir):
    """Explicit local opt-in: private JSON + Markdown outside shared outputs.

    This is NEVER available within GitHub Actions or CI.
    """
    if os.environ.get('GITHUB_ACTIONS') or os.environ.get('CI'):
        raise ValueError('PLAINTEXT_PRIVATE_EXPORT_FORBIDDEN_IN_CI')
    target=Path(target).resolve()
    public_dir=Path(public_dir).resolve()
    report=target.with_suffix('.md')
    if (target==public_dir or public_dir in target.parents
        or report==public_dir or public_dir in report.parents):
        raise ValueError('PRIVATE_OUTPUT_MUST_BE_OUTSIDE_PUBLIC_ARTIFACTS')
    if target.exists() or report.exists():
        raise FileExistsError('LOCAL_PRIVATE_OUTPUT_ALREADY_EXISTS')
    manifest=make_private_shortlist(evaluation,sink)
    report_data=markdown_manifest(manifest)
    target.parent.mkdir(parents=True,exist_ok=True)
    for path,body in ((target,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n'),
                      (report,report_data)):
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as output:
            output.write(body)
    return manifest['clickable_unique_count']


def markdown_manifest(manifest):
    """Offline rendering only; NEVER write this within a GitHub Actions run."""
    def esc(s):
        s=s.replace('\\','\\\\')
        for ch in ('[',']','|','*','_','`','<','>','!'):
            s=s.replace(ch,'\\'+ch)
        return s
    rows=[
        '# v4.34 — 가격순 클릭 가능한 당근 매물',
        '',
        f"검증된 고유 매물: **{manifest['clickable_unique_count']}개**",
        f"제목 검증 불충분으로 보류: **{manifest['unlinked_title_quarantine_count']}개**",
        '',
        '| 순위 | 실제 매물 제목·링크 | 관측 가격 | 등록 동·읍·면 | 관측 횟수 | 판매 상태 |',
        '|---:|---|---:|---|---:|---|']
    for i,item in enumerate(manifest.get('items',[]),1):
        url=item['url']
        if normalized_listing(url)!=url:
            raise ValueError('UNSAFE_URL_IN_DECRYPTED_MANIFEST')
        area_label=item.get('item_area_display','지역 미확인')
        if item.get('item_area_key') is not None and (
                configured_label(item['item_area_key']) != area_label):
            raise ValueError('ITEM_AREA_DISPLAY_CONFLICT')
        rows.append(f"| {i} | [{esc(item['title'])}]({url}) | "
            f"{item['price_krw']:,}원 | {esc(area_label)} | {item['observation_count']}회 | "
            f"{esc(item['availability'])} |")
    rows.extend(['',
        '관측 당시 가격·상품 제목이며 판매자가 현재 거래 가능한지는 별도 확인이 필요합니다.',
        '상품 검색어와 정확히 일치한다는 제품별 검증은 별도의 단계입니다.',
        '원본 URLs와 제목을 GitHub Actions 평문 아티팩트에 게시하지 않았습니다.',
        ''])
    return '\n'.join(rows)
