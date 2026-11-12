# -*- coding: utf-8 -*-
"""Offline-only safety and causality regressions for first-load comparisons."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_v5.region_baseline_contrast import (
    _BROWSER_JS, sanitize_baseline, classify_egress_payload, sanitize_egress,
    optional_egress_context, compare_baselines, safe_machine_class,
    summarize_passive_routes,
)
from scripts.region_baseline_contrast import (
    sanitized_report, comparison, main, _SCHEMA,
)
from scripts.chrome_stable_input_compare import sanitize_attempt


class MockResponse:
    status=200
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return None
    def read(self,n):
        return json.dumps({
            "ip":"218.123.12.77",
            "city":"PRIVATE_CITY","postal":"PRIVATE_POSTAL",
            "latitude":37.1,"longitude":127.1,
            "country_code":"KR","org":"ORACLE Cloud Infra"
        }).encode()


class RegionBaselinePrivacyTests(unittest.TestCase):
    def test_sensitive_browser_content_never_reaches_report(self):
        initial={
            "ui":{"state":"NO_DIALOG","selected_control":"OTHER",
                  "visible_dialogs":0,
                  "private_cookie":"secret"},
            "browser":{"loader_status":"BOOTSTRAP_REGION_PRESENT",
                       "loader_search_region":"OTHER",
                       "loader_filter_region":"OTHER",
                       "language":"KO","timezone":"ASIA_SEOUL",
                       "cookies_present":True,
                       "local_storage_count":2,"session_storage_count":3,
                       "document_visibility":"VISIBLE",
                       "login_text_signal":False,
                       "raw_cookies":"auth=SECRET",
                       "region_name":"PRIVATE_CITY"},
            "passive_route":{"count":1,"status":"ONE_OBSERVED",
                             "search_region":"OTHER",
                             "filter_region":"OTHER",
                             "raw_url":"https://private.invalid","raw_id":"99291"},
            "url_region":"OTHER","private_seller":"seller.example"
        }
        safe=sanitize_baseline(initial)
        self.assertEqual(safe["ui"]["selected_control"],"OTHER")
        self.assertEqual(safe["browser"]["loader_search_region"],"OTHER")
        self.assertEqual(safe["passive_route"]["search_region"],"OTHER")
        self.assertFalse(safe["authorizes_listings"])
        self.assertEqual(sanitize_baseline(safe),safe)
        text=json.dumps(safe,ensure_ascii=False)
        for bad in ("SECRET","PRIVATE","seller.example","auth=","99291"):
            self.assertNotIn(bad,text)

    def test_network_country_provider_but_not_ip_or_city(self):
        response=classify_egress_payload({
            "ip":"203.0.113.11","city":"PRIVATE_TOWN",
            "latitude":3.123,"postal":"PRIVATE_POSTCODE",
            "country_code":"US","org":"Microsoft Azure Cloud",
            "asn":"AS12345"})
        self.assertEqual(response["country"],"NON_KR")
        self.assertEqual(response["network_provider_hint"],"MICROSOFT_AZURE")
        self.assertNotIn("203.0.113",json.dumps(response))
        self.assertNotIn("PRIVATE",json.dumps(response))
        self.assertEqual(sanitize_egress(response),response)
        self.assertFalse(response["authorizes_listings"])

    def test_egress_makes_zero_http_requests_unless_opted_in(self):
        def forbidden(*a,**kw):
            raise AssertionError("NETWORK_WOULD_RUN")
        self.assertEqual(optional_egress_context(
            enabled=False,getter=forbidden)["state"],"DISABLED")
        got=optional_egress_context(enabled=True,getter=lambda *a,**k:MockResponse())
        self.assertEqual(got["country"],"KR")
        self.assertEqual(got["network_provider_hint"],"ORACLE_CLOUD")
        self.assertNotIn("218.123",json.dumps(got))
        self.assertEqual(optional_egress_context(
            enabled=True,getter=forbidden)["state"],"UNAVAILABLE")

    def test_no_unknown_remote_api_key_or_storage_value_in_js(self):
        self.assertNotIn("document.cookie=", _BROWSER_JS)
        self.assertNotIn("localStorage.getItem",_BROWSER_JS)
        self.assertNotIn("sessionStorage.getItem",_BROWSER_JS)
        self.assertNotIn("fetch(",_BROWSER_JS)
        self.assertNotIn("XMLHttpRequest",_BROWSER_JS)

    def test_passive_route_never_conflates_multiple_initial_responses(self):
        self.assertEqual(summarize_passive_routes([])["status"],"NOT_OBSERVED")
        self.assertEqual(summarize_passive_routes([
            {"state":"OBSERVED","model":{
                "search_region":"EXPECTED","filter_region":"EXPECTED"}}])[
                "search_region"],"EXPECTED")
        self.assertEqual(summarize_passive_routes([
            {"state":"OBSERVED","model":{"search_region":"OTHER"}},
            {"state":"OBSERVED","model":{"search_region":"EXPECTED"}}])[
                "status"],"MULTIPLE_OBSERVED")

    def test_hosted_env_discloses_no_environment_variables(self):
        source={"GITHUB_ACTIONS":"true","HTTPS_PROXY":"http://private:topsecret@host"}
        sample=safe_machine_class(environ=source,system="Linux")
        self.assertEqual(sample["runtime"],"GITHUB_HOSTED")
        self.assertTrue(sample["http_proxy_configured"])
        self.assertNotIn("private",str(sample))

    def test_host_comparison_never_proves_network_causation(self):
        initial={"ui":{"selected_control":"EXPECTED"},
                 "browser":{"timezone":"ASIA_SEOUL","language":"KO"}}
        other={"ui":{"selected_control":"OTHER"},
               "browser":{"timezone":"OTHER","language":"KO"}}
        result=compare_baselines(initial,other)
        self.assertEqual(result["baseline_differences"]["ui.selected_control"],
                         "DIFFERENT")
        self.assertFalse(result["proves_network_causation"])
        self.assertFalse(result["proves_host_causation"])

    def test_same_ab_baseline_retains_redaction_and_idempotence(self):
        a=sanitize_attempt({
            "mode":"FILL","status":"REGION_NOT_COMMITTED",
            "initial_baseline":{
                "ui":{"selected_control":"OTHER"},
                "browser":{"raw_cookie":"secret"},
                "passive_route":{"status":"ONE_OBSERVED","count":1,
                                 "search_region":"OTHER",
                                 "filter_region":"OTHER"}},
            "raw_login_token":"a" * 40})
        self.assertEqual(a["initial_baseline"]["ui"]["selected_control"],"OTHER")
        self.assertEqual(sanitize_attempt(a),a)
        self.assertNotIn("secret",json.dumps(a))


class RegionBaselineCLITests(unittest.TestCase):
    def test_live_requires_explicit_approval_even_when_headless(self):
        self.assertEqual(main(["--live"]),2)
        self.assertEqual(main(["--live","--owner-approval","WRONG"]),2)
        self.assertEqual(main(["--egress-context"]),2)

    def test_report_contains_only_known_enums(self):
        raw={"site_visit":"ONE_PUBLIC_SEARCH_PAGE",
             "status":"BASELINE_OBSERVED","http_class":"HTTP_200",
             "machine":{"runtime":"GITHUB_HOSTED","os":"LINUX"},
             "egress":{"country":"NON_KR","network_provider_hint":"MICROSOFT_AZURE",
                       "state":"OBSERVED","ip":"PRIVATE_IP"},
             "snapshots":{"BASELINE_DOM_READY":{"ui":{"selected_control":"OTHER"}}},
             "raw_links":"https://private.invalid"}
        clean=sanitized_report(raw)
        self.assertEqual(clean["schema"],_SCHEMA)
        self.assertEqual(clean["site_visit"],"ONE_PUBLIC_SEARCH_PAGE")
        self.assertNotIn("PRIVATE",json.dumps(clean))

    def test_two_complete_saved_baselines_comparable_without_live_access(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            paths=[]
            for n,region in enumerate(("OTHER","EXPECTED")):
                report=sanitized_report({
                    "site_visit":"ONE_PUBLIC_SEARCH_PAGE","status":"BASELINE_OBSERVED",
                    "http_class":"HTTP_200",
                    "machine":{"runtime":"LOCAL" if not n else "GITHUB_HOSTED",
                               "os":"WINDOWS"},
                    "snapshots":{"BASELINE_SETTLED":{
                        "ui":{"selected_control":region}}},
                })
                path=p/f"{n}.json"
                path.write_text(json.dumps(report),encoding="utf-8")
                paths.append(path)
            result=comparison(*paths)
            self.assertEqual(result["baseline_differences"][
                "ui.selected_control"],"DIFFERENT")
            self.assertFalse(result["causal_hypothesis_proven"])
            self.assertFalse(result["region_selection_tested"])
            self.assertEqual(main(["--compare-local",str(paths[0]),
                                   "--compare-hosted",str(paths[1])]),0)


if __name__=="__main__":
    unittest.main()
