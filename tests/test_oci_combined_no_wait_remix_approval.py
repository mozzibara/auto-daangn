# -*- coding: utf-8 -*-
"""Synthetic combined native region click and Remix V2 metadata consent gate."""
import json
import unittest
from unittest.mock import patch

from ops.oci.precollection import (
    _NAV_WAIT_APPROVAL, _DYNAMIC_METADATA_APPROVAL,
    _COMBINED_METADATA_APPROVAL, run, main,
)


class CombinedApprovalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        async def diagnostic():
            self.calls.append(True)
            return {
                "status": "TARGET_REGION_CONFIRMED_DIAGNOSTIC",
                "precollection": {
                    "status": "BLOCKED_FILTER_URL",
                    "dynamic_loader_metadata_mode": True,
                    "dynamic_loader_metadata_count": 1,
                    "dynamic_loader_metadata_status": "ONE_PARSED",
                    "dynamic_loader_server_filters": {
                        "region": "EXPECTED",
                        "category": "EXPECTED",
                        "available": "EXPECTED",
                        "price_max": "MISSING",
                    },
                    "dynamic_loader_price_shape": "UNTRUSTED_PRICE_ONLY",
                    "dynamic_loader_price_echo": "ENCODED_MAX_MATCH",
                    "secret_title": "PRIVATE_SELLER",
                },
            }
        self.diagnostic = diagnostic
        self.kw = dict(
            live=True, headed=True,
            no_wait_region_click=True, passive_dynamic_loader=True,
            robots=lambda: True,
            picker_robots=lambda _: {"allowed": True},
            directory_check=lambda: True, diagnostic=diagnostic,
        )

    async def test_combined_exact_token_required_and_existing_tokens_rejected(self):
        for invalid in ("", _NAV_WAIT_APPROVAL,
                        _DYNAMIC_METADATA_APPROVAL,
                        "I_APPROVE_OCI_PRECOLLECTION_FILL_V1"):
            with self.subTest(invalid=invalid):
                result = await run(approve=invalid, **self.kw)
                self.assertEqual(result["status"], "OWNER_APPROVAL_REQUIRED")
                self.assertFalse(result["collection_started"])
                self.assertEqual(len(self.calls), 0)
        valid = await run(approve=_COMBINED_METADATA_APPROVAL, **self.kw)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(valid["status"], "STOP_FILTERS_NOT_VERIFIED")
        self.assertEqual(valid["region_click_navigation_wait"], "NO_WAIT_AFTER")
        self.assertFalse(valid["collection_started"])
        self.assertFalse(valid["authorizes_listings"])
        self.assertNotIn("PRIVATE_SELLER", json.dumps(valid))

    async def test_three_modes_combined_never_authorized(self):
        result = await run(
            approve=_COMBINED_METADATA_APPROVAL,
            passive_changed_loader=True, **self.kw)
        self.assertEqual(result["status"], "OWNER_APPROVAL_REQUIRED")
        self.assertEqual(len(self.calls), 0)

    async def test_wrong_flag_mode_cannot_use_combined_token(self):
        options = dict(self.kw)
        options["passive_dynamic_loader"] = False
        result = await run(approve=_COMBINED_METADATA_APPROVAL, **options)
        self.assertEqual(result["status"], "OWNER_APPROVAL_REQUIRED")
        self.assertEqual(len(self.calls), 0)

    async def test_live_flag_and_headed_mandatory(self):
        opts = dict(self.kw)
        opts["live"] = False
        result = await run(approve=_COMBINED_METADATA_APPROVAL, **opts)
        self.assertEqual(result["status"], "OWNER_APPROVAL_REQUIRED")
        self.assertEqual(len(self.calls), 0)

    async def test_cli_rejects_combination_without_owner_before_network(self):
        with patch("ops.oci.precollection.asyncio.run") as coroutine:
            self.assertEqual(main([
                "--live", "--headed", "--no-wait-region-click",
                "--passive-dynamic-loader-metadata",
                "--owner-approval", _NAV_WAIT_APPROVAL,
            ]), 2)
            coroutine.assert_not_called()
            self.assertEqual(main([
                "--live", "--headed",
                "--passive-new-loader-metadata", "--no-wait-region-click",
                "--passive-dynamic-loader-metadata",
                "--owner-approval", _COMBINED_METADATA_APPROVAL,
            ]), 2)
            coroutine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
