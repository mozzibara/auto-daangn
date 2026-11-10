# Public-source migration and controlled cutover

## Source and provenance
- Curated working-tree snapshot of the private development `main` at commit `30b8fa7882023d9dbb18f2348c55839a081222fa`.
- This is a **new Git history**, not a fork, GitHub Transfer, or `git push --mirror`.
- Only source modules, pinned **public** Ed25519 verifier, synthetic v5 tests, opt-in capture and offline CI workflows, minimal configuration examples, and operational service templates were selected.
- Past Git history, Issues, pull requests, Actions logs, download artifacts, SQLite state, actual market observations and all private keys remain outside this repository.
- Code was updated to recognize `mozzibara/auto-daangn` as the authoritative producer, including OCI intake, Ed25519 provenance, and owner approval. Approval Issue is **#1**, not the historical Issue #3.
- The verifier key is deliberately unchanged, with raw Git blob `74707a4d20d3a091dc27d879a2552e746d39991f`. It is a **public key**; never upload the corresponding signing private key.

## Pre-activation checks

1. Review the new repository Actions permissions. Set default workflow token permissions to **Read repository contents**. Require approval for external pull requests and protect `main`.
2. Keep live `secure-links-v434.yml` capture **manual and owner-approved**. The `issue_comment` entrypoint is restricted to owner-authored exact commands on Issue #1.
3. Provision `V434_ATTEST_ED25519_KEY_B64` as a new GitHub Actions Secret through the private owner-controlled channel. It is not copied automatically. Verify the signer using the manual `verify-v434-signer.yml` workflow **before any live capture**.
4. Run the offline CI, synthetic OCI runtime, artifact-intake, cloud backup and AI query/Telegram analysis tests. They must not contact the marketplace or send real messages.
5. Do **not** enable OCI Actions intake merely because CI is green. Obtain a real encrypted OCI Object Storage cloud readback, independently restore it outside OCI using the offline recovery private key, then record the verified baseline.

## OCI SECOND-INSTANCE migration boundary

Existing state must be retained at `/var/lib/auto-daangn`. Its SQLite DB, HMAC keyring, X25519 recipient private key, backups and recovery state **must not be reinitialized or pushed to GitHub**.

The new repository starts with an unrelated Git history. Do not use `git pull --ff-only` against the old clone; that would fail or mix histories.

Recommended operator-controlled cutover:

1. Record existing systemd timer/service status and current commit. Disable `daangn-actions-intake.timer` and `daangn-object-storage-backup.timer` for cutover.
2. Produce and independently test the encrypted offsite restore before cutover.
3. Clone this public repository to a **new** staging directory (for example `/opt/auto-daangn-public-stage`). Verify the expected public commit and installed Python dependencies independently.
4. Review and adapt existing `/opt/auto-daangn` service expectations, then during a maintenance window switch the source checkout path; preserve the old checkout for rollback and **never overwrite** `/var/lib/auto-daangn`.
5. Ensure the local OCI Actions-read credential is issued to read the new public repository if still used. The old Git-over-SSH Deploy Key is no longer necessary for a public HTTPS clone; retire it only after successful rollback-ready cutover.
6. With verified recipient public key and producer key, run exactly one owner-approved capture, validate the Ed25519 source-repository/commit binding, verify sealed ciphertext and import only after the separate backup gate passes.
7. Enable automatic intake/backup timers only after the previous steps and verify service journal summaries. No inbound webhook, browser, Docker or OCI private API key is required by the original OCI intake design.

## Security boundaries
- GitHub does not receive individual signed capture **plaintext** title, listing URL, seller details, local database, tokens or encryption private keys.
- Public Actions artifacts may be visible to others; only authenticated ciphertext plus privacy-bounded metadata may be uploaded.
- Previous signed artifacts contain the old repository identity and are **not** automatically trusted as artifacts from this new repository.
- `gitignore` is defense in depth, not secret scanning. Inspect every commit and artifact before public publication.
- Signed REVIEWABLE observations are not verified current availability or purchase recommendations.

## Limitations
The repository migration itself does not connect to the OCI instance, provision GitHub Secrets, create/validate Object Storage IAM policies, verify offline restores, start regular site collection, or send Telegram notifications. These are separate owner-controlled operational steps.
