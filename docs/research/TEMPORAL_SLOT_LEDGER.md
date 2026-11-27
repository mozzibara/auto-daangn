# Daangn temporal diagnostic slot ledger (S1-08/10/11/12/22)

The old seven-day A/A/FAR experiment has a fixed UTC 00:17/12:17 cadence and
a 75-minute invocation window. It must not be extended or replayed after
expiry. A scheduled workflow's success without an authenticated slot report
is not proof of a browser experiment.

The new offline module app_v5/temporal_slot_ledger.py enumerates the original
fourteen expected slots and labels missing reports, cancellation, future slots
and verified finite outcomes. A separate explicit SQLite diagnostic ledger
binds a single attempt to slot, approval ID, lease start and exact source SHA.
A transaction prevents concurrent claims; outstanding attempts require an
explicit outcome review, with no automatic retry or backfill.

This is a recording primitive only, not an authorization mechanism. It accepts
already verified owner approval/stop and report provenance from a future
adapter. A stale or forged caller object is not proof of authority. Do not
connect claim() directly to a live browser. There is no subprocess or network,
systemd installation, production DB initialization, listing admission,
Telegram or collection. The ledger must be created only inside a trusted
owner-local directory; no public export of approval IDs.

Tests: synthetic RED (missing module) and 13 GREEN tests including concurrent
claims, cross-lease replay, foreign DB protection, expiry, interruption and
clock regression. Local Linux Python 3.13 only at this checkpoint. Full repo
OCI regression and protected GitHub CI are separate gates. Next integrate an
authenticated fresh owner lease/stop adapter, an explicitly approved bounded
diagnostic executor and local timer; retain existing robots and capture gates.

## Historical audit: expired seven-day cohort

Read-only review of the original private scheduling evidence (2026-11-27):
14 expected slots; 14 scheduled workflow runs during the original lease;
zero run creation timestamps within their 75-minute eligibility windows.
All 14 job-step records show authorization success and Chrome experiment /
publication skipped. All 14 decoded gate logs explicitly contain
NOT_APPROVED_SCHEDULE_SLOT. Zero eligible scheduled observations were posted.
This establishes a scheduling failure, not a region-effect result. Do not
extend, backfill or reactivate the expired approval. Raw private logs and
approval IDs remain private. S1-08 historical audit is complete for this cohort.

Initial Windows CI found an unclosed SQLite connection in the foreign-DB
fixture (temporary directory cleanup, WinError 32). Explicit closing fixes
the test; no runtime behavior change. Focused local tests: 13/13 again.
