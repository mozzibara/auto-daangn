# -*- coding: utf-8 -*-
"""Synthetic Telegram/outbox fault injection + keyword-profile scoring tests."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app_v5.analysis_profiles import ProductFacts, SearchProfile, analyze, analyze_for_profile
from app_v5.attestation import sign_capture, signing_public_key
from app_v5.history import HistoryStore
from app_v5.sealed_import import import_manifest, import_signed_capture, read_encrypted
from app_v5.telegram_outbox import (
    NotificationOutbox, PermanentSendError, TransientSendError,
    dispatch_mocked_once, enqueue_verified_drop, render_telegram_preview, signed_price_drops
)
from daangn_secure_links_v4_34 import seal_manifest

TIME = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
URL = "https://www.daangn.com/kr/buy-sell/synthetic-alert-abcdefghijkl/"
HMAC = b"generated-only-test-hmac-key-no-prod-secrets"
SHA = "c" * 40
SMART_CLEAN = {5: 0, 187: 0, 188: 0, 197: 0, 198: 0, 199: 0, 9: 12000}


class FakeTransport:
    """No internet, no Telegram bot token, deterministic scripted outcomes."""
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def send_text(self, text):
        self.calls.append(text)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class PriceAnalysisTests(unittest.TestCase):
    def facts(self, **overrides):
        values = dict(keyword="HDD", previous_price_krw=45000,
                      price_krw=35000, capacity_tb=Decimal("4"),
                      capacity_provenance="independent_measurement",
                      smart_raw=SMART_CLEAN,
                      smart_provenance="independent_measurement")
        values.update(overrides)
        return ProductFacts(**values)

    def test_verified_smart_and_capacity_are_high_review_not_buy_guarantee(self):
        result = analyze("hdd", self.facts())
        self.assertEqual(result.priority, "HIGH_REVIEW")
        self.assertEqual(result.price_per_tb_krw, 8750)
        self.assertEqual(result.price_drop_pct, Decimal("22.22"))
        self.assertEqual(result.score, 100)
        self.assertEqual(result.breakdown["category_value"], 30)
        self.assertEqual(result.breakdown["category_condition"], 25)

    def test_seller_reported_capacity_cannot_be_high_priority(self):
        result = analyze("hdd", self.facts(
            capacity_provenance="seller_reported"
        ))
        self.assertEqual(result.priority, "NEEDS_EVIDENCE")
        self.assertIn("HDD_CAPACITY_SELLER_REPORTED_NOT_VERIFIED",
                      result.warnings)

    def test_missing_smart_never_assumed_healthy(self):
        result = analyze("hdd", self.facts(smart_raw=None,
                                            smart_provenance="unknown"))
        self.assertEqual(result.priority, "NEEDS_EVIDENCE")
        self.assertIn("SMART_UNAVAILABLE", result.warnings)
        self.assertEqual(result.breakdown["category_condition"], 0)
        self.assertLessEqual(result.score, 55)

    def test_incomplete_smart_never_assumed_zero_on_missing_attributes(self):
        result = analyze("hdd", self.facts(smart_raw={5: 0, 9: 7000}))
        self.assertEqual(result.priority, "NEEDS_EVIDENCE")
        self.assertIn("SMART_CRITICAL_FIELDS_INCOMPLETE", result.warnings)
        self.assertEqual(result.breakdown["category_condition"], 0)

    def test_pending_and_reallocated_or_uncorrectable_trigger_review(self):
        for attr in (5, 187, 188, 197, 198):
            with self.subTest(attr=attr):
                smart = dict(SMART_CLEAN, **{})  # fresh mapping
                smart[attr] = 1
                result = analyze("hdd", self.facts(smart_raw=smart))
                self.assertEqual(result.priority, "RISK_REVIEW")
                self.assertTrue(any("NONZERO_REVIEW" in w for w in result.warnings))

    def test_crc_warns_about_cable_not_automatic_disk_failure(self):
        smart = {**SMART_CLEAN, 199: 2}
        result = analyze("hdd", self.facts(smart_raw=smart))
        self.assertIn("SMART_UDMA_CRC_REVIEW_CABLE_OR_INTERFACE", result.warnings)
        self.assertNotEqual(result.priority, "RISK_REVIEW")

    def test_seller_reported_clean_smart_is_not_independent_verification(self):
        result = analyze("hdd", self.facts(smart_provenance="seller_reported"))
        self.assertEqual(result.priority, "NEEDS_EVIDENCE")
        self.assertEqual(result.confidence, "UNVERIFIED_SMART")
        self.assertIn("SMART_SELLER_REPORTED_NOT_INDEPENDENTLY_VERIFIED",
                      result.warnings)

    def test_hours_are_caution_not_failure_probability(self):
        hours = {**SMART_CLEAN, 9: 52000}
        result = analyze("hdd", self.facts(smart_raw=hours))
        self.assertIn("SMART_LONG_POWER_ON_HOURS", result.warnings)
        self.assertEqual(result.breakdown["category_condition"], 17)

    def test_unknown_keyword_falls_back_to_generic_no_hdd_assumptions(self):
        result = analyze("unknown-keyword-profile", self.facts(keyword="레드미 워치 6",
                                  smart_raw=None, smart_provenance="unknown",
                                  capacity_tb=None, capacity_provenance="unknown"))
        self.assertEqual(result.profile, "generic")
        self.assertIsNone(result.price_per_tb_krw)
        self.assertEqual(result.priority, "REVIEW")
        self.assertIn("KEYWORD_SPECIFIC_ANALYZER_NOT_CONFIGURED", result.warnings)

    def test_selected_keyword_routes_to_explicit_analyzer(self):
        self.assertEqual(
            analyze_for_profile(SearchProfile("profile-hdd", "HDD", "hdd"),
                                self.facts()).profile, "hdd")
        self.assertEqual(
            analyze_for_profile(
                SearchProfile("profile-watch", "Redmi Watch 6", "generic"),
                self.facts(keyword="Redmi Watch 6", smart_raw=None,
                           smart_provenance="unknown", capacity_tb=None,
                           capacity_provenance="unknown")).profile, "generic")
        with self.assertRaisesRegex(ValueError, "SEARCH_PROFILE_MISMATCH"):
            analyze_for_profile(SearchProfile("hdd", "SSD", "hdd"),
                                self.facts())
        with self.assertRaisesRegex(ValueError, "UNKNOWN_CONFIGURED_ANALYZER"):
            analyze_for_profile(SearchProfile("hdd", "HDD", "nonexistent"),
                                self.facts())

    def test_invalid_prices_capacity_and_smart_encoding_fail_closed(self):
        cases = [
            self.facts(previous_price_krw=35000),
            self.facts(previous_price_krw=0),
            self.facts(price_krw=True),
            self.facts(capacity_tb=Decimal("0")),
            self.facts(smart_raw={5: -1}),
            self.facts(smart_raw={5: 0}, smart_provenance="unknown"),
            self.facts(smart_raw=None, smart_provenance="seller_reported"),
        ]
        for case in cases:
            with self.subTest(case=str(case)[:90]):
                with self.assertRaises(ValueError):
                    analyze("hdd", case)


class TelegramIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = HistoryStore(self.root / "synthetic-history.sqlite3", HMAC)
        self.outbox_path = self.root / "synthetic-outbox.sqlite3"
        self.outbox = NotificationOutbox(self.outbox_path, max_attempts=3)
        receiver = X25519PrivateKey.generate()
        self.receiver_private = receiver.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        self.receiver_public = base64.b64encode(
            receiver.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode("ascii")
        signer = Ed25519PrivateKey.generate()
        self.signer_private = signer.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        self.signer_public = signing_public_key(self.signer_private)

    def signed_capture(self, run_id, price, captured):
        folder = self.root / f"signed-{run_id}"
        folder.mkdir()
        manifest = {
            "version": "4.34", "capture_scoped_only": True,
            "created_utc": captured,
            "clickable_unique_count": 1,
            "unlinked_title_quarantine_count": 0,
            "source_run_unique_candidates": 1,
            "items": [{
                "title": "합성 NAS HDD 4TB", "url": URL,
                "price_krw": price, "category": "디지털기기",
                "availability": "판매 가능 추정", "observation_count": 1,
                "full_recommendation_approved": False,
                "seller_confirmed_available": False,
                "captured_from_current_primary_h1": True
            }],
            "unlinked_groups": [],
            "manual_current_price_and_status_recheck_required": True,
            "full_recommendations_approved": 0
        }
        data = {
            "v434_private_candidate_links.encrypted.json":
                seal_manifest(manifest, self.receiver_public),
            "v434_secure_links_summary.json": {
                "version": "4.34", "status": "SEALED_PRIVATE_CANDIDATES_COMPLETE",
                "unique_candidates": 1, "linked_unique_candidates": 1,
                "quarantined_title_groups": 0, "full_recommendations_approved": 0,
                "key_material_on_github": False,
                "plaintext_urls_or_titles_in_artifacts": False
            },
            "v434_run_status.json": {
                "version": "4.34", "status": "SEALED_CAPTURE_COMPLETE",
                "attempted_live": True, "encrypted_links_written": True,
                "approval_required": True, "strict_listing_approved_count": 0,
                "max_source_visits": 9, "max_control_visits": 6,
                "unique_candidates": 1, "linked_unique_candidates": 1,
                "quarantined_title_groups": 0,
                "ended_utc": "2026-11-14T02:00:00+00:00"
            },
            "v433_unique_candidates.json": {
                "evaluation": {"dedup_complete": True}
            },
            "v429_public_status_results.json": {
                "evaluation": {
                    "survey_complete": True,
                    "status": "PUBLIC_STATUS_SIGNAL_SURVEY_COMPLETE_NO_DIRECT_FOR_SALE_PROOF"
                }
            },
            "v434_robots_decision.json": {"allowed": True}
        }
        for name, content in data.items():
            (folder / name).write_text(json.dumps(content, ensure_ascii=False),
                                       encoding="utf-8")
        signed = sign_capture(folder, self.signer_private,
                              run_id=run_id, run_attempt=1, commit_sha=SHA)
        (folder / "v434_capture_attestation.json").write_text(json.dumps(signed),
                                                              encoding="utf-8")
        return folder

    def import_signed(self, run_id, folder):
        return import_signed_capture(
            self.store,
            encrypted_json=folder / "v434_private_candidate_links.encrypted.json",
            recipient_private_key=self.receiver_private,
            attestation_json=folder / "v434_capture_attestation.json",
            trusted_signer_public_key=self.signer_public,
            summary_json=folder / "v434_secure_links_summary.json",
            run_status_json=folder / "v434_run_status.json",
            unique_json=folder / "v433_unique_candidates.json",
            profile_id="synthetic-hdd",
            job_id=f"v434-gh-{run_id}-a1",
            expected_commit_sha=SHA
        )

    def seeded(self):
        first = self.signed_capture(3601, 45000, "2026-11-11T01:00:00+00:00")
        second = self.signed_capture(3602, 35000, "2026-11-12T01:00:00+00:00")
        self.assertEqual(self.import_signed(3601, first)["events_generated"], 0)
        self.assertEqual(self.import_signed(3602, second)["events_generated"], 1)
        candidates = signed_price_drops(self.store)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        analysis = analyze("hdd", ProductFacts(
            keyword="HDD", previous_price_krw=candidate.previous_price_krw,
            price_krw=candidate.price_krw, capacity_tb=Decimal("4"),
            capacity_provenance="seller_reported",
            smart_raw=None, smart_provenance="unknown"
        ))
        message = render_telegram_preview(candidate, analysis)
        self.assertIn("판매 상태·재고·SMART 원본은 별도 확인 필요", message)
        self.assertIn("8,750원/TB", message)
        return candidate, message

    def test_authenticated_drop_becomes_preview_and_not_a_real_send(self):
        event, text = self.seeded()
        self.assertEqual(event.previous_price_krw, 45000)
        self.assertEqual(event.price_krw, 35000)
        self.assertIn("45,000원 → 35,000원", text)
        self.assertIn("NEEDS_EVIDENCE", text)
        self.assertEqual(len(self.store.get_events()), 1)

    def test_trust_boundary_rejects_forged_or_wrong_price_facts(self):
        event, _ = self.seeded()
        profile = SearchProfile("synthetic-hdd", "HDD", "hdd")
        correct = ProductFacts(
            keyword="HDD", previous_price_krw=45000, price_krw=35000,
            capacity_tb=Decimal("4"), capacity_provenance="seller_reported",
            smart_provenance="unknown")
        delivery_id, inserted = enqueue_verified_drop(
            self.outbox, self.store, event.event_id, "synthetic-recipient",
            profile, correct, now=TIME)
        self.assertTrue(inserted)
        self.assertEqual(self.outbox.status(delivery_id)["state"], "PENDING")
        with self.assertRaisesRegex(ValueError, "UNAUTHENTICATED_PRICE_DROP_EVENT"):
            enqueue_verified_drop(self.outbox, self.store, event.event_id + 9000,
                                  "synthetic-recipient", profile, correct, now=TIME)
        wrong = ProductFacts(
            keyword="HDD", previous_price_krw=45000, price_krw=31000)
        with self.assertRaisesRegex(ValueError, "PRICE_FACTS_MISMATCH_SIGNED_EVENT"):
            enqueue_verified_drop(self.outbox, self.store, event.event_id,
                                  "synthetic-recipient", profile, wrong, now=TIME)

    def test_crash_after_remote_acceptance_can_replay_and_is_documented(self):
        event, text = self.seeded()
        key, _ = self.outbox.enqueue(event, "synthetic-recipient", text, now=TIME)
        accepted_but_unacked = self.outbox.claim(now=TIME, lease_seconds=10)
        # Simulate Telegram accepting the send, then process dying before ACK.
        # The outbox cannot guarantee exactly-once external delivery.
        restarted = NotificationOutbox(self.outbox_path, max_attempts=3)
        claimed_again = restarted.claim(now=TIME + timedelta(seconds=11))
        self.assertEqual(claimed_again.attempt, 2)
        self.assertEqual(claimed_again.text, accepted_but_unacked.text)
        restarted.ack(claimed_again, "simulated-second-remote-accept",
                      now=TIME + timedelta(seconds=12))
        self.assertEqual(restarted.status(key)["attempts"], 2)

    def test_enqueue_duplicate_and_confirm_once_across_restart(self):
        event, text = self.seeded()
        delivery_id, fresh = self.outbox.enqueue(
            event, "synthetic-recipient", text, now=TIME)
        self.assertTrue(fresh)
        self.assertFalse(self.outbox.enqueue(
            event, "synthetic-recipient", text, now=TIME)[1])
        sender = FakeTransport(["synthetic-message-001"])
        self.assertEqual(dispatch_mocked_once(self.outbox, sender, now=TIME), "SENT")
        restarted = NotificationOutbox(self.outbox_path, max_attempts=3)
        self.assertFalse(restarted.enqueue(
            event, "synthetic-recipient", text, now=TIME)[1])
        self.assertEqual(dispatch_mocked_once(
            restarted, sender, now=TIME + timedelta(minutes=10)), "IDLE")
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(restarted.status(delivery_id)["attempts"], 1)

    def test_timeout_then_rate_limit_retry_after_then_success(self):
        event, text = self.seeded()
        key, _ = self.outbox.enqueue(event, "synthetic-recipient", text, now=TIME)
        sender = FakeTransport([
            TransientSendError(),
            TransientSendError(retry_after_seconds=37),
            "synthetic-message-002"
        ])
        self.assertEqual(dispatch_mocked_once(self.outbox, sender, now=TIME), "PENDING")
        self.assertEqual(dispatch_mocked_once(
            self.outbox, sender, now=TIME + timedelta(seconds=9)), "IDLE")
        self.assertEqual(dispatch_mocked_once(
            self.outbox, sender, now=TIME + timedelta(seconds=10)), "PENDING")
        self.assertEqual(dispatch_mocked_once(
            self.outbox, sender, now=TIME + timedelta(seconds=46)), "IDLE")
        self.assertEqual(dispatch_mocked_once(
            self.outbox, sender, now=TIME + timedelta(seconds=47)), "SENT")
        self.assertEqual(self.outbox.status(key)["attempts"], 3)
        self.assertEqual(len(sender.calls), 3)

    def test_permanent_403_and_attempt_exhaustion_dead_letter(self):
        event, text = self.seeded()
        key, _ = self.outbox.enqueue(event, "primary", text, now=TIME)
        self.assertEqual(dispatch_mocked_once(
            self.outbox, FakeTransport([PermanentSendError("403")]),
            now=TIME), "DEAD")
        self.assertEqual(self.outbox.status(key)["state"], "DEAD")
        key2, _ = self.outbox.enqueue(event, "secondary", text, now=TIME)
        sender = FakeTransport([TransientSendError()] * 3)
        self.assertEqual(dispatch_mocked_once(self.outbox, sender, now=TIME), "PENDING")
        self.assertEqual(dispatch_mocked_once(
            self.outbox, sender, now=TIME + timedelta(seconds=10)), "PENDING")
        self.assertEqual(dispatch_mocked_once(
            self.outbox, sender, now=TIME + timedelta(seconds=30)), "DEAD")
        self.assertEqual(self.outbox.status(key2)["attempts"], 3)
        self.assertEqual(dispatch_mocked_once(
            self.outbox, sender, now=TIME + timedelta(days=1)), "IDLE")

    def test_crash_recovery_lease_and_stale_worker_cannot_ack(self):
        event, text = self.seeded()
        key, _ = self.outbox.enqueue(event, "synthetic-recipient", text, now=TIME)
        worker_a = self.outbox.claim(now=TIME, lease_seconds=30)
        self.assertIsNotNone(worker_a)
        self.assertIsNone(self.outbox.claim(now=TIME + timedelta(seconds=29)))
        restarted = NotificationOutbox(self.outbox_path, max_attempts=3)
        worker_b = restarted.claim(now=TIME + timedelta(seconds=31))
        self.assertIsNotNone(worker_b)
        self.assertNotEqual(worker_a.lease_token, worker_b.lease_token)
        with self.assertRaisesRegex(ValueError, "STALE_DELIVERY_LEASE"):
            restarted.ack(worker_a, "late-receipt", now=TIME+timedelta(seconds=31))
        restarted.ack(worker_b, "synthetic-message-after-restart",
                      now=TIME + timedelta(seconds=32))
        self.assertEqual(restarted.status(key)["state"], "SENT")
        self.assertEqual(restarted.status(key)["attempts"], 2)
        self.assertIsNone(restarted.claim(now=TIME+timedelta(days=1)))

    def test_conflicting_message_same_event_is_refused(self):
        event, text = self.seeded()
        self.outbox.enqueue(event, "synthetic-recipient", text, now=TIME)
        with self.assertRaisesRegex(ValueError, "CONFLICTING_ALERT_PAYLOAD"):
            self.outbox.enqueue(event, "synthetic-recipient",
                                text+"alteration", now=TIME)

    def test_unsigned_advisory_is_never_telegram_eligible(self):
        unsigned = self.signed_capture(3701, 45000,
                                       "2026-11-11T01:00:00+00:00")
        manifest = read_encrypted(
            unsigned / "v434_private_candidate_links.encrypted.json",
            self.receiver_private
        )
        import_manifest(self.store, manifest,
                        profile_id="synthetic-hdd", job_id="unsigned-3701")
        signed = self.signed_capture(3702, 35000,
                                     "2026-11-12T01:00:00+00:00")
        self.import_signed(3702, signed)
        self.assertEqual(self.store.get_events(), [])
        self.assertEqual(signed_price_drops(self.store), [])

    def test_no_browser_network_or_real_telegram_token_required(self):
        event, text = self.seeded()
        # All data were generated in tempfile. No Bot API method exists here.
        self.assertNotIn("Bot", text)
        self.assertIn(URL, text)
        self.assertGreater(event.event_id, 0)


if __name__ == "__main__":
    unittest.main()
