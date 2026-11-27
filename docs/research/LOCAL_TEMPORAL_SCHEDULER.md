# S1 local temporal scheduler — installation boundary

This is the Daangn A/A/FAR diagnostic, not a generic CI runner, production
listing collector, administrator gateway, or permission to visit the site.
S1-09/10/11/12/14/22. The expired GitHub approval is NOT accepted. The local
approval is a separate decision by the owner administering OCI. It cannot
enable listing admission. GitHub approval/stop adapter S1-13 remains separate.

## Preparation (not automatic)

Review the exact merged commit using the existing protected main checks.
Use an independently verified root-owned clean checkout. A separate root-owned
/opt/daangn-temporal-venv with reviewed pinned requirements.txt wheels, Chrome
Stable, xvfb and xauth are prerequisites. Do not use a writable or symlinked
dependency path or reuse the production runtime's venv. Provision packages only
with explicit local administrator approval. No install has been performed by
this PR. The installer checks ownership and mode, not supply-chain provenance;
the operator must verify that separately. Run bash ops/oci/prepare_temporal.sh
ROOT_CHECKOUT EXACT_SHA for a read-only dry-run; --apply is a separate decision.
No automatic enable/start, approval creation, data migration or token changes.
Partial failure is fail-closed: inspect the new paths before resuming; no force
overwrite or automated cleanup.

The installer stages an immutable Git archive under the dedicated account's
root-owned home and initializes a separate private SQLite slot ledger.
The systemd timer is disabled by default. Existing daangn, oci-runner, CI,
Telegram, DB and keys are untouched by the installer. Read-only status is
available from the installed checkout as the dedicated user via
temporal_scheduler status. No GitHub token or inbound listener is created.

## Future local approval (not included in installation)

Only after offline on-host namespace, Chrome fixture, sandbox, resource and
permission smoke tests, and a NEW owner decision, root may atomically publish
/etc/daangn-temporal/approval.json (root-owned regular file, mode 0644 or 0640
with the dedicated group, no symlinks). Exactly five fields:
schema=daangn_local_temporal_approval_v1, purpose=AA_FAR_DIAGNOSTIC_ONLY,
approval_id=positive unique integer, starts_at=aware ISO UTC timestamp,
source_sha=the installed source.sha exact commit. The lease lasts seven days.
No retroactive slots. No old GitHub lease conversion. Before activation check
that the old GitHub research scheduler has no active lease; do not issue
parallel approvals for the same research. Enable the local timer only after
that separate decision. Never disable Chrome sandbox or weaken systemd
isolation to make a smoke test pass.

Root can remove the approval file to stop future launches; the active child
checks the file each poll (best effort, not instantaneous network revocation).
Emergency stop: stop timer AND service; a killed job remains RUNNING with
unknown outcome until reviewed. Missing/changed/invalid approval stops the
child. A non-observed result latches review-hold.json; no automatic retry.
Do not delete the ledger to resume; review the attempt and any aggregate result
before explicit local reconciliation. No automated clearing/recovery CLI yet.

Timer 00:17/12:17 UTC, 75-minute slot window, no catch-up, 690s child maximum
bounded by remaining lease and slot; 720s systemd outer timeout; control-group
cleanup. Separate UID, no capabilities, no production data access by design,
no token, finite child report and private aggregate results; not a hostile-
browser sandbox or guarantee of network restriction. Chromium needs network
for the approved public diagnostic; existing robots checks and one-shot
browser controls remain unchanged. Root owns approval and source. The
dedicated UID owns local ledger/results; browser and scheduler share that UID
and therefore this is not a tamper-proof ledger against compromised Chrome.
No raw report, title, URL, listing identifier or token is intentionally
persisted or printed. Finite aggregate metrics are independently projected;
no causal or locality proof is inferred.

Live compatibility, resource headroom on the ~1 GiB OCI host, executable
dependency provenance, effective systemd settings, local approval creation,
old scheduler conflict check and actual site diagnostic are pending. Stop
and investigate on any failure rather than reducing isolation.

A fixed 512 MiB MemAvailable precheck defers launch before a slot claim if
host headroom is insufficient; this is not a resource reservation or a proof
that the browser fits. No backfill. Read-only status reports unresolved
attempts even when the approval has been removed. Offline CI uses real
synthetic subprocesses to exercise timeout/output limits, never Chrome/live
site access in the scheduler tests.
