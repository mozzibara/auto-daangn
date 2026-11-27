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
