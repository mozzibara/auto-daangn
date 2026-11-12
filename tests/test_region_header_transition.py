# -*- coding: utf-8 -*-
"""No raw region headers leak from observed baseline or click comparison."""
import json
from pathlib import Path
import unittest

from app_v5.region_baseline_contrast import (
    classify_region_header_transition, sanitize_header_transition,
    sanitize_baseline,
)
from scripts.chrome_stable_input_compare import sanitize_attempt

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/region-header-transition-compare.yml"


class HeaderTransitionWitnessTests(unittest.TestCase):
    def test_exact_unmodified_header_is_observable_without_exposure(self):
        before="지역 선택: 서울특별시 강남구"
        x=classify_region_header_transition(before,before)
        self.assertEqual(x["status"],"UNCHANGED")
        self.assertEqual(x["before_header_family"],"SEOUL")
        self.assertEqual(x["after_header_family"],"SEOUL")
        self.assertFalse(x["proves_server_region_changed"])
        self.assertNotIn("강남",json.dumps(x,ensure_ascii=False))

    def test_clicked_header_changed_to_target_not_accepted_as_server_proof(self):
        x=classify_region_header_transition(
            "지역 선택: 서울특별시 강남구","지역 선택: 천안시 불당동")
        self.assertEqual(x["status"],"CHANGED")
        self.assertEqual(x["after_header_family"],"TARGET")
        self.assertFalse(x["authorizes_listings"])
        self.assertFalse(x["proves_server_region_changed"])

    def test_different_non_target_city_is_different_category(self):
        x=classify_region_header_transition(
            "지역 선택: 아산시 배방읍","지역 선택: 천안시 두정동")
        self.assertEqual(x["before_header_family"],"ASAN")
        self.assertEqual(x["after_header_family"],"CHEONAN_OTHER")
        self.assertEqual(x["status"],"CHANGED")

    def test_missing_or_invalid_header_cannot_claim_unchanged(self):
        for before,after in (
            (None,None),("PRIVATE_ADDRESS","PRIVATE_ADDRESS"),
            ("지역 선택:","지역 선택: 서울"),
            (3,"지역 선택: 서울")):
            self.assertEqual(classify_region_header_transition(
                before,after)["status"],"UNOBSERVABLE")

    def test_malicious_raw_values_never_published(self):
        bad={"status":"CHANGED",
             "before_header_family":"PRIVATE_HOME_STREET",
             "after_header_family":"TARGET",
             "raw_region_name":"SECRET_HOME_STREET",
             "local_storage":"SECRET_COOKIE"}
        clean=sanitize_header_transition(bad)
        self.assertEqual(clean["before_header_family"],"UNOBSERVABLE")
        self.assertNotIn("SECRET",json.dumps(clean))
        self.assertEqual(sanitize_header_transition(clean),clean)

    def test_baseline_and_ab_consistent(self):
        first=sanitize_baseline({"initial_header_family":"SEOUL"})
        self.assertEqual(first["initial_header_family"],"SEOUL")
        self.assertEqual(sanitize_baseline(first),first)
        attempt=sanitize_attempt({"initial_baseline":first,
            "header_transition":{
                "status":"UNCHANGED","before_header_family":"SEOUL",
                "after_header_family":"SEOUL",
                "raw_header":"지역 선택: 서울특별시 강남구"}})
        self.assertEqual(attempt["header_transition"]["status"],"UNCHANGED")
        self.assertEqual(sanitize_attempt(attempt),attempt)
        self.assertNotIn("강남",json.dumps(attempt,ensure_ascii=False))


class HeaderTransitionWorkflowGuards(unittest.TestCase):
    def test_owner_only_static_main_and_no_artifacts_or_secrets(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("github.event.issue.number == 11",text)
        self.assertIn("github.event.comment.user.login == github.repository_owner",text)
        self.assertIn("github.event.comment.body == '/run-daangn-region-transition-v1'",text)
        self.assertIn("github.actor == github.repository_owner",text)
        self.assertIn("inputs.approval == 'I_APPROVE_REGION_TRANSITION_V1'",text)
        self.assertIn("ref: main",text)
        self.assertIn("persist-credentials: false",text)
        self.assertIn("os: [ubuntu-24.04, windows-2025]",text)
        for forbidden in ("pull_request:","push:","schedule:","upload-artifact",
                          "secrets.","--no-sandbox","--proxy-server",
                          "--disable-blink-features","--ignore-certificate-errors"):
            self.assertNotIn(forbidden,text)
        self.assertLess(text.index(
            "python -m scripts.chrome_stable_input_compare --headed"),
            text.index("--live --headed --egress-context"))


if __name__=="__main__":
    unittest.main()
