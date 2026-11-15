# -*- coding: utf-8 -*-
"""Price-only experiment must have distinct consent and never enable collection."""
import unittest
from unittest.mock import patch

from app_v5.precollection_filter_gate import PassiveFilteredRoute
from ops.oci.precollection import (
    run, main, _PRICE_SAMPLE_APPROVAL, _COMBINED_METADATA_APPROVAL,
)


class PriceSampleApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_previous_token_can_start_price_only_mode(self):
        called = []
        async def diagnostic():
            called.append(1)
            return {"status": "INCONCLUSIVE"}
        kwargs = dict(
            live=True, headed=True, no_wait_region_click=True,
            passive_dynamic_loader=True, passive_price_sample=True,
            robots=lambda: True, picker_robots=lambda _: {"allowed": True},
            directory_check=lambda: True, diagnostic=diagnostic,
        )
        for token in ("", _COMBINED_METADATA_APPROVAL,
                      "I_APPROVE_OCI_DYNAMIC_METADATA_ONLY_V2"):
            result = await run(approve=token, **kwargs)
            self.assertEqual(result["status"], "OWNER_APPROVAL_REQUIRED")
        self.assertEqual(called, [])
        result = await run(approve=_PRICE_SAMPLE_APPROVAL, **kwargs)
        self.assertEqual(len(called), 1)
        self.assertFalse(result["authorizes_listings"])
        self.assertFalse(result["database_written"])

    async def test_price_only_cannot_be_combined_with_unsafe_modes(self):
        called = []
        async def diagnostic():
            called.append(1)
        for extra in (
            {"passive_dynamic_loader": False},
            {"no_wait_region_click": False},
            {"passive_changed_loader": True},
        ):
            options = dict(
                approve=_PRICE_SAMPLE_APPROVAL, live=True, headed=True,
                no_wait_region_click=True, passive_dynamic_loader=True,
                passive_price_sample=True,
                robots=lambda: True, picker_robots=lambda _: {"allowed": True},
                directory_check=lambda: True, diagnostic=diagnostic,
            )
            options.update(extra)
            result = await run(**options)
            self.assertEqual(result["status"], "OWNER_APPROVAL_REQUIRED")
        self.assertEqual(called, [])


class PriceSampleCliTests(unittest.TestCase):
    def test_cli_invalid_token_and_missing_flags_do_not_create_loop(self):
        with patch("ops.oci.precollection.asyncio.run") as runloop:
            for args in (
                ["--live", "--headed", "--no-wait-region-click",
                 "--passive-dynamic-loader-metadata",
                 "--passive-bounded-price-sample",
                 "--owner-approval", _COMBINED_METADATA_APPROVAL],
                ["--live", "--headed",
                 "--passive-bounded-price-sample",
                 "--owner-approval", _PRICE_SAMPLE_APPROVAL],
            ):
                self.assertEqual(main(args), 2)
            runloop.assert_not_called()

    def test_default_observer_cannot_access_price_samples(self):
        self.assertFalse(PassiveFilteredRoute().passive_price_sample)
        self.assertFalse(PassiveFilteredRoute(passive_price_sample=True).
                         passive_price_sample)
        self.assertTrue(PassiveFilteredRoute(
            passive_dynamic_loader=True,
            passive_price_sample=True).passive_price_sample)


if __name__ == "__main__":
    unittest.main()
