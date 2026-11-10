# -*- coding: utf-8 -*-
"""v4.29 redacted schema and item-status survey summary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def summarize(folder):
    try:
        raw=json.loads((folder/'v429_public_status_results.json')
                       .read_text(encoding='utf-8'))
        e=raw.get('evaluation') or {}
        text=(folder/'v429_public_status_report.md').read_text(encoding='utf-8')
        if e.get('survey_complete') is not True:
            text+='\n- Incomplete or quarantined; no direct FOR_SALE proof.\n'
    except (OSError,ValueError,TypeError,KeyError):
        try:
            x=json.loads((folder/'v429_run_status.json')
                         .read_text(encoding='utf-8'))
        except (OSError,ValueError,TypeError):x={}
        status=x.get('status')
        if not isinstance(status,str) or not status.startswith((
            'STOP_','QUARANTINED_','INCONCLUSIVE_')):
            status='INCONCLUSIVE_RESULTS_UNAVAILABLE'
        text='# v4.29 public status/scheme research\n\n'
        text+=f'- Verdict: {status}\n- Complete: False\n'
        text+='- Direct FOR_SALE proof: 0\n- Strict listings approved: 0\n'
    # The separate presentation-only hypothesis must never be mistaken for
    # confirmed FOR_SALE or incorporated into the canonical transaction model.
    try:
        overlay=json.loads((folder/'v430_availability_estimates.json')
                           .read_text(encoding='utf-8'))
        estimate=overlay.get('evaluation') or {}
        if estimate.get('projection_complete') is True:
            text+='\n## v4.30 표시용 판매 가능성 추정 (직접 입증 아님)\n\n'
            text+=('- 판매 가능 추정: '+
                str(estimate.get('inferred_possible_for_sale_count',0))+'회\n')
            text+=('- 직접 검증된 FOR_SALE: '+
                str(estimate.get('verified_for_sale_count',0))+'회\n')
            text+='- 엄격 승인: 0건. 원본 거래 상태는 그대로 유지.\n'
        else:
            text+='\n- v4.30 display-only estimate: INCONCLUSIVE; no inferred admission.\n'
    except (OSError,ValueError,TypeError,KeyError):
        pass
    # Distinguish the policy-level sale filter from fully approved listings.
    try:
        policy=json.loads((folder/'v431_sale_filter_results.json')
                          .read_text(encoding='utf-8'))
        e=policy.get('evaluation') or {}
        if e.get('evaluation_complete') is True:
            text+='\n## v4.31 실제 탐색용 판매 가능 조건\n\n'
            text+=('- 판매 가능 조건 통과: '+
                   str(e.get('sale_filter_passed',0))+'회\n')
            text+=('- 직접 FOR_SALE 배지 필수: 아니요\n')
            text+=('- 가격·카테고리 등 별도 검증 필요; 최종 승인: 0건\n')
        else:
            text+='\n- v4.31 sale filter: INCONCLUSIVE (no listing admission).\n'
    except (OSError,ValueError,TypeError,KeyError):
        pass
    try:
        doc=json.loads((folder/'v432_recommendation_candidates.json')
                       .read_text(encoding='utf-8'))
        e=doc.get('evaluation') or {}
        if e.get('join_complete') is True:
            text+='\n## v4.32 판매 가능·가격·카테고리 추천 후보 결합\n\n'
            text+=('- 조건별 후보: '+
                str(e.get('candidate_rows_ready',0))+'회\n')
            text+=('- 개별 가격 증거 확인: '+
                str(e.get('item_price_known',0))+'회\n')
            text+='- 링크는 GitHub 공개/보관 아티팩트에 기록하지 않음.\n'
            text+='- 전체 추천 승인: 0 (독립 필터 증거 및 링크 재확인 별도).\n'
        else:
            text+='\n- v4.32 recommendation candidate join: INCONCLUSIVE.\n'
    except (OSError,ValueError,TypeError,KeyError):
        pass
    try:
        unique=json.loads((folder/'v433_unique_candidates.json')
                          .read_text(encoding='utf-8'))
        e=unique.get('evaluation') or {}
        if e.get('dedup_complete') is True:
            text+='\n## v4.33 매물 단위 중복 제거\n\n'
            text+=('- 고유 추천 검토 후보: '+
                   str(e.get('unique_candidate_count',0))+'개\n')
            text+=('- 제거된 중복 관측: '+
                   str(e.get('duplicate_observations_removed',0))+'회\n')
            text+=('- 불일치로 격리한 그룹: '+
                   str(e.get('quarantined_unique_groups',0))+'개\n')
            text+='- 식별자: 실행별 HMAC, 원본 URL/ID/판매자 정보 제외.\n'
            text+='- 최종 추천 자동 승인: 0건.\n'
        else:
            text+='\n- v4.33 unique candidates: INCONCLUSIVE (no dedup claim).\n'
    except (OSError,ValueError,TypeError,KeyError):
        pass
    (folder/'v429_evidence_summary.md').write_text(text,encoding='utf-8')
    return text


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v429_live_output'))
    path=p.parse_args().output_dir.resolve()
    path.mkdir(parents=True,exist_ok=True)
    print(summarize(path))


if __name__=='__main__':
    main()
