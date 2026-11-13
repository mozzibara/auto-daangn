# -*- coding: utf-8 -*-
"""Offline-only historical price evidence reuse audit regressions."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from app_v5.historical_price_reuse_audit import (
    EXPECTED, audit_archived_price_reports,
)
from scripts.audit_legacy_price_reuse import main


def fixture():
    records18, records19 = [], []
    for (context, profile), cap in EXPECTED.items():
        records18.append({
            "context": context, "profile": profile,
            "max_price_krw": cap,
            "region": "asan" if context == "asan_control" else "cheonan",
            "status": "CAPTURED_ROUTE_AND_UI",
            "route_correlated": True,
            "observed_url_shape": True,
            "matched_ui_route_count": 1,
            "raw_route_rows": 150,
            "price_shape": {
                "raw_array_rows": 150, "unknown_price_rows": 0,
                "above_requested_cap": 0,
                "PRIVATE_LISTING_TOKEN": "DO_NOT_EXPORT",
            },
            "ui": {
                "verified_both": True,
                "spa_maximum_krw": cap, "reload_maximum_krw": cap,
            },
            "seller": "PRIVATE_SELLER_NAME",
            "access_restricted": False,
        })
        records19.append({
            "context": context, "profile": profile,
            "max_price_krw": cap, "status": "OBSERVED",
            "verdict": "CURRENT_FILTERS_ENCODED_PRICE_ECHO_PRESENT",
            "structure": {
                "status": "OBSERVED",
                "item_rows_not_inspected": True,
                "response_body_persisted": False,
                "traversal_truncated": False,
                "raw_secret": "PRIVATE_SELLER_NAME",
            },
            "title": "PRIVATE_TITLE",
        })
    v418 = {
        "version": "4.18",
        "design": {
            "first_party_route_sha_correlated": True,
            "target_caps_krw": [20000, 50000, 100000],
        },
        "evaluation": {
            "capture_complete": True,
            "behavioral_server_price_cap_supported": True,
            "price_cap_violations": [],
            "private_secret": "PRIVATE_TOKEN",
        },
        "observations": records18,
    }
    v419 = {
        "version": "4.19",
        "crosscheck": {
            "capture_complete": True,
            "behavioral_server_price_cap_supported": True,
            "price_cap_violations": [],
        },
        "independent_evidence_grade": {
            "tier": "BEHAVIORAL_ROUTE_CORROBORATED",
        },
        "observations": records19,
    }
    return v418, v419


class EvidenceClassifierTests(unittest.TestCase):
    def test_missing_archives_cannot_claim_historical_success(self):
        result = audit_archived_price_reports()
        self.assertEqual(result["archival_record_status"], "NOT_PROVIDED")
        self.assertEqual(result["current_oci_price_enforcement"], "NOT_PROVEN")
        self.assertFalse(result["authorizes_listings"])

    def test_one_archive_is_insufficient(self):
        a,b = fixture()
        for args in ((a,None),(None,b)):
            result = audit_archived_price_reports(*args)
            self.assertEqual(result["archival_record_status"], "PAIR_MISSING")
            self.assertFalse(result["authorizes_listings"])

    def test_complete_self_report_still_not_independently_verifiable(self):
        a,b = fixture()
        result = audit_archived_price_reports(a,b)
        self.assertEqual(result["archival_record_status"], "SELF_REPORTED_COMPLETE")
        self.assertEqual(result["archival_claim"],
                         "ARCHIVED_BEHAVIORAL_CLAIM_UNVERIFIABLE")
        self.assertEqual(result["historical_v419_tier"],
                         "BEHAVIORAL_ROUTE_CORROBORATED")
        self.assertEqual(result["archival_provenance"], "UNVERIFIED")
        self.assertFalse(result["jaccard_independently_recomputable"])
        self.assertEqual(result["current_oci_regionless_transfer"],
                         "NOT_VALIDATED")
        self.assertEqual(result["current_oci_price_enforcement"], "NOT_PROVEN")
        self.assertFalse(result["authorizes_listings"])
        self.assertFalse(result["collection_started"])
        self.assertFalse(result["database_written"])
        self.assertNotIn("PRIVATE",json.dumps(result))

    def test_source_proven_7_profiles_are_required(self):
        a,b = fixture()
        a["observations"].pop()
        self.assertEqual(audit_archived_price_reports(a,b)["archival_record_status"],
                         "INVALID_STRUCTURE")

    def test_duplicate_context_does_not_pass(self):
        a,b = fixture()
        a["observations"][-1]=a["observations"][0]
        self.assertEqual(audit_archived_price_reports(a,b)["archival_record_status"],
                         "INVALID_STRUCTURE")

    def test_wrong_region_and_price_cap_cannot_report_complete(self):
        for key,value in (("region","asan"),("max_price_krw",49999)):
            a,b=fixture()
            a["observations"][0][key]=value
            self.assertEqual(audit_archived_price_reports(a,b)[
                "archival_record_status"],"INVALID_STRUCTURE")

    def test_unknown_prices_and_missing_ui_prevent_positive_claim(self):
        for path,value in ((("price_shape","unknown_price_rows"),1),
                           (("ui","verified_both"),False),
                           (("price_shape","raw_array_rows"),0),
                           (("status",),"CAPTURED_ROUTE_UI_UNVERIFIED"),
                           (("route_correlated",),False)):
            a,b=fixture()
            target=a["observations"][0]
            for k in path[:-1]:target=target[k]
            target[path[-1]]=value
            self.assertEqual(audit_archived_price_reports(a,b)[
                "archival_record_status"],"SELF_REPORTED_PARTIAL")

    def test_over_cap_price_is_explicit_contradiction(self):
        a,b=fixture()
        a["observations"][0]["price_shape"]["above_requested_cap"]=1
        result=audit_archived_price_reports(a,b)
        self.assertEqual(result["archival_record_status"],"CONTRADICTED")
        self.assertEqual(result["archival_claim"],
                         "ARCHIVED_BEHAVIORAL_CLAIM_CONTRADICTED")
        self.assertFalse(result["authorizes_listings"])

    def test_access_restriction_is_explicit_contradiction(self):
        a,b=fixture()
        a["observations"][2]["access_restricted"]=True
        self.assertEqual(audit_archived_price_reports(a,b)[
            "archival_record_status"],"CONTRADICTED")

    def test_mismatched_legacy_v419_echo_is_not_supported(self):
        a,b=fixture()
        b["observations"][3]["verdict"]="CURRENT_FILTERS_ENCODED_PRICE_ECHO_MISMATCH"
        self.assertEqual(audit_archived_price_reports(a,b)[
            "archival_record_status"],"CONTRADICTED")

    def test_claimed_positive_but_missing_support_remains_partial(self):
        a,b=fixture()
        b["crosscheck"]["behavioral_server_price_cap_supported"]=False
        self.assertEqual(audit_archived_price_reports(a,b)[
            "archival_record_status"],"SELF_REPORTED_PARTIAL")

    def test_incompatible_v419_tier_is_not_promoted(self):
        a,b=fixture()
        b["independent_evidence_grade"]["tier"]="INSUFFICIENT"
        result=audit_archived_price_reports(a,b)
        self.assertEqual(result["archival_record_status"],"SELF_REPORTED_PARTIAL")
        self.assertFalse(result["authorizes_listings"])

    def test_untrusted_jaccard_claim_does_not_waive_recompute(self):
        a,b=fixture()
        a["evaluation"]["repeat_by_cap"]={"cap_50000":{"jaccard":1.0}}
        result=audit_archived_price_reports(a,b)
        self.assertFalse(result["jaccard_independently_recomputable"])
        self.assertFalse(result["authorizes_listings"])


class OfflineCLITests(unittest.TestCase):
    def test_no_args_uses_no_files_or_network(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            code=main([])
        self.assertEqual(code,2)
        result=json.loads(output.getvalue())
        self.assertEqual(result["archival_record_status"],"NOT_PROVIDED")
        self.assertFalse(result["authorizes_listings"])

    def test_existing_pair_is_only_self_reported_and_no_raw_export(self):
        a,b=fixture()
        with tempfile.TemporaryDirectory() as folder:
            one=Path(folder)/"v418.json"
            two=Path(folder)/"v419.json"
            one.write_text(json.dumps(a),encoding="utf-8")
            two.write_text(json.dumps(b),encoding="utf-8")
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                code=main(["--v418",str(one),"--v419",str(two)])
            self.assertEqual(code,0)
            result=json.loads(output.getvalue())
            self.assertEqual(result["archival_record_status"],
                             "SELF_REPORTED_COMPLETE")
            self.assertEqual(result["current_oci_price_enforcement"],"NOT_PROVEN")
            self.assertNotIn("PRIVATE",output.getvalue())
            self.assertFalse(result["authorizes_listings"])

    def test_invalid_files_are_not_mistaken_for_no_records(self):
        a,b=fixture()
        with tempfile.TemporaryDirectory() as folder:
            one=Path(folder)/"bad.json"
            two=Path(folder)/"good.json"
            one.write_text("NOT_JSON",encoding="utf-8")
            two.write_text(json.dumps(b),encoding="utf-8")
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                code=main(["--v418",str(one),"--v419",str(two)])
            self.assertEqual(code,2)
            self.assertEqual(json.loads(output.getvalue())[
                "archival_record_status"],"INVALID_STRUCTURE")

    def test_malformed_large_file_never_echoed(self):
        a,b=fixture()
        with tempfile.TemporaryDirectory() as folder:
            one=Path(folder)/"too-big.json"
            two=Path(folder)/"valid.json"
            one.write_bytes(b"PRIVATE_SECRET" * 200000)
            two.write_text(json.dumps(b),encoding="utf-8")
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                code=main(["--v418",str(one),"--v419",str(two)])
            self.assertEqual(code,2)
            self.assertNotIn("PRIVATE",output.getvalue())


if __name__ == "__main__":
    unittest.main()
