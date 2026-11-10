# -*- coding: utf-8 -*-
"""v4.29 owner-approved one-run public DOM/schema survey, robots first."""
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

PROFILE={'region':'cheonan','control_region':'asan','keyword':'HDD',
         'category_id':1,'available_only':True,'max_price':50000,'min_price':0}
SUCCESS=('PUBLIC_STATUS_SIGNAL_SURVEY_COMPLETE_NO_DIRECT_FOR_SALE_PROOF',
         'PUBLIC_DIRECT_FOR_SALE_UI_CONFIRMED')


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',
                    encoding='utf-8')


def run(folder,*,checker=check_robots,runner=None):
    folder.mkdir(parents=True,exist_ok=True)
    save(folder/'v429_profile.json',{'version':'4.29','profile':PROFILE,
        'source_detail_max':9,'control_detail_max':6,
        'one_capture':True,'robots_exact_targets_required':True,
        'no_owner_state_mutations':True,
        'strict_listing_gate_changed':False})
    result={'version':'4.29','started_utc':utc(),'attempted_live':False,
        'status':'STOP_PREFLIGHT','survey_complete':False,'exit_code':2,
        'strict_listing_approved_count':0}
    try:
        robots=checker(PROFILE)
        save(folder/'v429_search_robots_decision.json',robots)
        if robots.get('allowed') is not True:
            result['status']='STOP_SEARCH_ROBOTS_'+str(
                robots.get('reason','UNKNOWN'))
            return 2
        cmd=[sys.executable,str(ROOT/'daangn_status_study_v4_29.py'),
             '--output-dir',str(folder),'--timeout','25','--settle-ms','1600']
        result['attempted_live']=True
        proc=(runner or subprocess.run)(cmd,cwd=str(ROOT),
                                        check=False,timeout=1350)
        result['exit_code']=int(getattr(proc,'returncode',2))
        fn=folder/'v429_public_status_results.json'
        if not fn.is_file():
            result['status']='STOP_MISSING_RESULTS'
            return 2
        data=json.loads(fn.read_text(encoding='utf-8'))
        e=data.get('evaluation') if isinstance(data,dict) else {}
        e=e if isinstance(e,dict) else {}
        result['status']=str(e.get('status','INCONCLUSIVE'))
        result['survey_complete']=e.get('survey_complete') is True
        result['source_visits']=e.get('source_visits',0)
        result['control_visits']=e.get('control_visits',0)
        result['direct_for_sale_count']=e.get('explicit_direct_for_sale_evidence',0)
        return 0 if result['exit_code']==0 and result['survey_complete'] and (
            result['status'] in SUCCESS) else 2
    except subprocess.TimeoutExpired:
        result['status']='STOP_RUNTIME_LIMIT'
        return 2
    except Exception as ex:
        result['status']='STOP_'+type(ex).__name__
        return 2
    finally:
        result['ended_utc']=utc()
        save(folder/'v429_run_status.json',result)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,default=Path('v429_live_output'))
    return run(p.parse_args().output_dir.resolve())


if __name__=='__main__':
    raise SystemExit(main())
