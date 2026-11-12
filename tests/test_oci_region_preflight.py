# -*- coding: utf-8 -*-
"""OCI preflight must be offline, sealed-store-isolated and fail closed."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from scripts import oci_region_preflight as probe


def good(**changes):
    base = {
        "architecture": "x86_64", "os_id": "ubuntu",
        "os_version": "24.04", "python_version": (3, 12),
        "chrome_available": True, "xvfb_available": True,
        "xauth_available": True,
        "package_status": {"playwright": True, "cryptography": True},
        "root": False, "working_copy_isolated": True,
    }
    base.update(changes)
    return probe.classify_environment(**base)


class OciPreflightUnitTests(unittest.TestCase):
    def test_x86_ubuntu_python312_is_ready_for_offline_only(self):
        result = good()
        self.assertEqual(result["architecture"], "x86_64")
        self.assertTrue(result["ready_for_offline_chrome_fixture"])
        self.assertFalse(result["public_site_visited"])
        self.assertFalse(result["region_selection_attempted"])
        self.assertFalse(result["authorizes_listings"])

    def test_not_ready_when_chrome_or_display_missing(self):
        for kwargs in (
            {"chrome_available": False},
            {"xvfb_available": False},
            {"xauth_available": False},
            {"xvfb_available": False, "xauth_available": False},
            {"package_status": {"playwright": False, "cryptography": True}},
            {"root": True},
            {"working_copy_isolated": False},
            {"architecture": "OTHER"},
            {"os_version": "22.04"},
            {"python_version": (3, 11)},
        ):
            with self.subTest(**kwargs):
                self.assertFalse(good(**kwargs)["ready_for_offline_chrome_fixture"])

    def test_xvfb_not_needed_with_existing_display(self):
        result = good(xvfb_available=False, xauth_available=False,
                      display_available=True)
        self.assertTrue(result["ready_for_offline_chrome_fixture"])

    def test_architecture_is_not_guessed_from_kernel_details(self):
        result = good(architecture="PRIVATE_DEVICE_NAME")
        self.assertEqual(result["architecture"], "OTHER")
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_no_secrets_or_environment_values_in_result(self):
        result = good(package_status={"playwright":True,
                                      "cryptography":True,
                                      "SECRET_TOKEN":"VALUE"},
                      root=True)
        s = json.dumps(result)
        self.assertNotIn("SECRET", s)
        self.assertNotIn("VALUE", s)
        self.assertFalse(result["non_root"])

    def test_os_release_never_executes_user_content(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"os-release"
            p.write_text('ID="ubuntu"\nVERSION_ID="24.04"\n'
                         'MY_SECRET="xyz"\n'
                         'ID=ubuntu; SECRET=$(touch /tmp/danger)\n',
                         encoding="utf-8")
            parsed=probe._os_release(p)
            self.assertNotIn("MY_SECRET", parsed)
            self.assertNotIn("xyz",json.dumps(parsed))
            self.assertNotEqual(parsed.get("ID"),"ubuntu")

    def test_no_network_when_no_offline_browser_flag(self):
        sentinel=RuntimeError("THIS_BROWSER_MUST_NOT_START")
        with patch.object(probe,"inspect_environment",return_value=good()), \
             patch.object(probe,"_local_html_fixture",side_effect=sentinel):
            self.assertEqual(probe.main([]), 0)

    def test_offline_browser_requires_ready_environment(self):
        with patch.object(probe,"inspect_environment",return_value=good(
                chrome_available=False)), \
             patch.object(probe,"_local_html_fixture",
                          side_effect=AssertionError("MUST_NOT_LAUNCH")):
            self.assertEqual(probe.main(["--offline-browser"]), 2)

    def test_strict_detects_missing_chrome_before_install(self):
        with patch.object(probe,"inspect_environment",return_value=good(
                chrome_available=False)):
            self.assertEqual(probe.main(["--strict"]), 2)

    def test_unprivileged_checkout_never_reads_existing_runtime_keys(self):
        import inspect
        source=inspect.getsource(probe)
        for forbidden in (
            "recipient-x25519-private.bin",
            "history-hmac-private.bin",
            "os.system(", "os.exec", "subprocess", "urllib",
            "request.urlopen", "browser.goto(", "SSH_PRIVATE",
        ):
            self.assertNotIn(forbidden,source)
        for expected in ("auto-daangn-public-stage", "/var/lib/auto-daangn",
                         "authorizes_listings", "site_visit"):
            if expected=="site_visit":
                self.assertIn("site_visit", inspect.getsource(
                    probe._local_html_fixture))
            else:
                self.assertIn(expected,source)


if __name__ == "__main__":
    unittest.main()
