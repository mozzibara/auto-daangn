# -*- coding: utf-8 -*-
"""v4.34 one-shot, owner-approved public capture with encrypted URL/title output.

No login, no hidden API, no more than the existing 9+6 robots-approved page
visits. Never materialize plaintext titles/URLs on GitHub runner disk.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_live_checked import check_robots
from scripts.run_status_study_v429_checked import PROFILE,SUCCESS
from daangn_secure_links_v4_34 import validate_public_key


def _save(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',
                    encoding='utf-8')


def run(output_dir,recipient_key,*,checker=check_robots,runner=None):
    output_dir=Path(output_dir).resolve()
    output_dir.mkdir(parents=True,exist_ok=True)
    state={'version':'4.34','attempted_live':False,
           'status':'STOP_PREFLIGHT',
           'encrypted_links_written':False,
           'approval_required':True,
           'max_source_visits':9,'max_control_visits':6,
           'raw_listing_urls_or_titles_written':False,
           'strict_listing_approved_count':0,
           'started_utc':datetime.now(timezone.utc).isoformat(timespec='seconds')}
    try:
        validate_public_key(recipient_key)
        robots=checker(PROFILE)
        _save(output_dir/'v434_robots_decision.json',robots)
        if robots.get('allowed') is not True:
            state['status']='STOP_ROBOTS_'+str(robots.get('reason','UNKNOWN'))
            return 2
        cmd=[sys.executable,str(ROOT/'daangn_status_study_v4_29.py'),
             '--output-dir',str(output_dir),'--timeout','25',
             '--settle-ms','1600','--sealed-public-key',recipient_key]
        state['attempted_live']=True
        proc=(runner or subprocess.run)(cmd,cwd=str(ROOT),
                                        check=False,timeout=1350)
        study=output_dir/'v429_public_status_results.json'
        unique=output_dir/'v433_unique_candidates.json'
        secure=output_dir/'v434_private_candidate_links.encrypted.json'
        public=output_dir/'v434_secure_links_summary.json'
        if not all(p.is_file() for p in (study,unique,secure,public)):
            state['status']='INCONCLUSIVE_INCOMPLETE_SECURE_CAPTURE'
            return 2
        survey=json.loads(study.read_text(encoding='utf-8'))
        dedup=json.loads(unique.read_text(encoding='utf-8'))
        summary=json.loads(public.read_text(encoding='utf-8'))
        envelope=json.loads(secure.read_text(encoding='utf-8'))
        verified=(getattr(proc,'returncode',2)==0
            and survey.get('evaluation',{}).get('status') in SUCCESS
            and survey.get('evaluation',{}).get('survey_complete') is True
            and dedup.get('evaluation',{}).get('dedup_complete') is True
            and summary.get('status')=='SEALED_PRIVATE_CANDIDATES_COMPLETE'
            and envelope.get('plaintext_not_archived') is True)
        state['status']=('SEALED_CAPTURE_COMPLETE'
                         if verified else 'INCONCLUSIVE_SECURE_CAPTURE')
        state['encrypted_links_written']=verified
        state['unique_candidates']=summary.get('unique_candidates',0)
        state['linked_unique_candidates']=summary.get('linked_unique_candidates',0)
        state['quarantined_title_groups']=summary.get('quarantined_title_groups',0)
        return 0 if verified else 2
    except subprocess.TimeoutExpired:
        state['status']='STOP_RUNTIME_LIMIT'
        return 2
    except Exception as ex:
        state['status']='STOP_'+type(ex).__name__
        return 2
    finally:
        state['ended_utc']=datetime.now(timezone.utc).isoformat(timespec='seconds')
        _save(output_dir/'v434_run_status.json',state)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--public-key',required=True)
    args=parser.parse_args()
    return run(args.output_dir,args.public_key)


if __name__=='__main__':
    raise SystemExit(main())
