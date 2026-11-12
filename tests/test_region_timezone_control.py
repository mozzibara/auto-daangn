# -*- coding: utf-8 -*-
"""Offline-only proof that timezone A/B is bounded, never collection authority."""
from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest

from scripts.region_timezone_contrast import (
    classify_arms, main, SCHEMA, APPROVAL, ARMS,
)
from scripts.chrome_stable_input_compare import one_public_region

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/region-timezone-control.yml"


def attempt(arm, *, status="REGION_NOT_COMMITTED",
            tz="OTHER", starting="SEOUL"):
    return {
        "arm":arm,
        "result":{
            "mode":"FILL", "status":status,
            "initial_baseline":{
                "browser":{"timezone":tz},
                "initial_header_family":starting,
                "ui":{"selected_control":"OTHER"}
            },
            "selected_ui":"OTHER",
            "server_filter":"OTHER",
            "server_search":"OTHER",
            "authorizes_listings":False,
        },
    }


class TimezoneHypothesisTests(unittest.TestCase):
    def test_only_two_exact_timezones_and_same_input_mode(self):
        self.assertEqual(ARMS,(("DEFAULT",None),
                              ("ASIA_SEOUL","Asia/Seoul")))
        src=inspect.getsource(one_public_region)
        self.assertIn("timezone_id not in (None, \"Asia/Seoul\")",src)
        self.assertIn("settings[\"timezone_id\"] = timezone_id",src)
        self.assertIn('locale": "ko-KR"',src)

    def test_two_failures_lower_timezone_only_explanation(self):
        result=classify_arms([
            attempt("DEFAULT",tz="OTHER"),
            attempt("ASIA_SEOUL",tz="ASIA_SEOUL")])
        self.assertEqual(result["status"],"BOTH_REGION_NOT_COMMITTED")
        self.assertFalse(result["causation_proven"])
        self.assertFalse(result["result_authorizes_listings"])

    def test_one_success_does_not_claim_causality(self):
        result=classify_arms([
            attempt("DEFAULT",tz="OTHER"),
            attempt("ASIA_SEOUL",tz="ASIA_SEOUL",
                    status="TARGET_REGION_CONFIRMED_DIAGNOSTIC")])
        self.assertEqual(result["status"],"DEFAULT_FAILED_SEOUL_CONFIRMED")
        self.assertFalse(result["causation_proven"])

    def test_no_real_time_zone_separation_is_inconclusive(self):
        x=classify_arms([attempt("DEFAULT",tz="ASIA_SEOUL"),
                         attempt("ASIA_SEOUL",tz="ASIA_SEOUL")])
        self.assertEqual(x["status"],"TIMEZONE_NOT_SEPARATED")

    def test_starting_region_mismatch_invalidates_comparison(self):
        x=classify_arms([attempt("DEFAULT",tz="OTHER"),
                         attempt("ASIA_SEOUL",tz="ASIA_SEOUL",
                                 starting="OTHER")])
        self.assertEqual(x["status"],"STARTING_REGION_DIFFERENT")

    def test_incomplete_or_wrong_order_is_not_a_result(self):
        for data in (
            [],
            [attempt("DEFAULT",tz="OTHER")],
            [attempt("ASIA_SEOUL",tz="ASIA_SEOUL"),
             attempt("DEFAULT",tz="OTHER")],
        ):
            self.assertEqual(classify_arms(data)["status"],"INCOMPLETE")

    def test_cli_rejects_live_without_exact_owner_approval(self):
        self.assertEqual(main(["--live"]),2)
        self.assertEqual(main(["--live","--owner-approval","WRONG"]),2)
        self.assertEqual(main(["--egress-context"]),2)

    def test_no_raw_ip_cookie_login_or_listing_visitor(self):
        src=inspect.getsource(one_public_region)
        for forbidden in ("storage_state=","geolocation=",
                          "proxy=","user_agent=", "http_credentials="):
            self.assertNotIn(forbidden,src)
        script=(ROOT/"scripts/region_timezone_contrast.py").read_text(
            encoding="utf-8")
        for forbidden in ("listing_links_visited=True","goto(listing",
                          "storage_state=", "add_cookies("):
            self.assertNotIn(forbidden,script)


class TimezoneWorkflowGuards(unittest.TestCase):
    def test_owner_only_job_not_auto_triggers(self):
        doc=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("issue_comment:",doc)
        self.assertIn("github.event.issue.number == 11",doc)
        self.assertIn("github.event.comment.user.login == github.repository_owner",
                      doc)
        self.assertIn("'/run-daangn-timezone-control-v1'",doc)
        self.assertIn("github.actor == github.repository_owner",doc)
        self.assertIn("I_APPROVE_TIMEZONE_REGION_CONTRAST_V1",doc)
        self.assertIn("os: [ubuntu-24.04, windows-2025]",doc)
        self.assertIn("ref: main",doc)
        self.assertIn("persist-credentials: false",doc)
        for item in ("push:", "pull_request:", "schedule:", "upload-artifact",
                     "secrets.", "--proxy-server", "--no-sandbox",
                     "--ignore-certificate-errors","storage-state"):
            self.assertNotIn(item,doc)

    def test_fixture_precedes_live_on_both_platforms(self):
        doc=WORKFLOW.read_text(encoding="utf-8")
        self.assertLess(doc.index(
            "python -m scripts.region_timezone_contrast --headed"),
            doc.index("--live --headed --egress-context"))
        self.assertIn("timezone control (Windows)",doc)
        self.assertIn("time zone",doc.lower().replace("timezone","time zone"))


class RegionTimezoneArgsTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_timezone_is_rejected_before_browser_access(self):
        with self.assertRaises(ValueError):
            await one_public_region(None,"FILL",timezone_id="Asia/Tokyo")


if __name__=="__main__":
    unittest.main()
