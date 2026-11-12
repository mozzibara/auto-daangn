# -*- coding: utf-8 -*-
"""Offline validator for configured local item districts. Makes no requests."""
from __future__ import annotations
import argparse
import json
from app_v5.item_area_policy import CONFIG, load_allowlist


def main(argv=None):
    parser=argparse.ArgumentParser(
        description="Validate Cheonan/Asan dong/eup/myeon allowlist (offline)")
    parser.add_argument("--config",default=str(CONFIG),
                        help="Path to the versioned allowlist JSON")
    args=parser.parse_args(argv)
    try:
        policy=load_allowlist(args.config)
    except ValueError as exc:
        print(json.dumps({"status":"INVALID","error":str(exc)},
                         ensure_ascii=False))
        return 2
    # This is a user-operated offline inspection of explicitly supplied
    # config, not a public diagnostic of actual sellers/listings.
    report={
        "status":"CONFIG_VALID",
        "schema":"daangn_item_area_allowlist_v1",
        "allowed_count":len(policy),
        "allowed_areas":[{
            "key":a["key"],
            "municipality":a["city"],
            "dong_eup_myeon":a["district"],
            "region_id_pinned":a["region_id"] is not None
        } for a in policy],
        "item_location_data_observed":False,
        "authorizes_listings":False,
    }
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
