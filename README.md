# auto-daangn

Public source snapshot of the owner-approved, read-only Daangn listing research and v5 evidence pipeline.

This repository contains source code, synthetic tests, and opt-in GitHub Actions. It does **not** contain an operational database, live listing data, private keys, GitHub tokens, OCI credentials, or Telegram credentials.

## Architecture

- [ARCHITECTURE.md](ARCHITECTURE.md): GitHub Actions / OCI SECOND-INSTANCE / ChatGPT / Telegram responsibility boundaries, reliability gates and rollout priorities.
- [MIGRATION.md](MIGRATION.md): controlled OCI cutover with the original private database and keys preserved.
- [SECURITY.md](SECURITY.md): threat model, secrets handling and public-repository safeguards.
- [PUBLIC_SECURITY_SETUP.md](PUBLIC_SECURITY_SETUP.md): owner-only environment signer Secret, main Ruleset and Actions policy setup.

Current status: **public source and synthetic CI only**. Live signing, OCI cloud-readback restoration, real Telegram messages and ChatGPT–OCI direct access are **not activated**.

## Manual normal-Chrome locality comparison

For a **user-operated** Chrome comparison of the unresolved public
region-selection issue, run `python -m scripts.manual_chrome_region_probe`
on your own PC. The tool starts an ordinary Chrome process with an
isolated temporary profile; you personally select the target district.
It observes only fixed locality/DOM classes and fresh first-party
region response agreement, and never approves listings. No account
cookies, raw listing details or user profile are exported.

See [Manual Chrome region probe](docs/research/MANUAL_CHROME_REGION_PROBE.md)
for Windows PowerShell setup, interactive steps, result interpretation,
loopback CDP security and cleanup requirements.

## Configurable local item districts\n\nAllowed Cheonan/Asan dong/eup/myeon neighborhoods are configured in\n[`config/item_area_allowlist.json`](config/item_area_allowlist.json), not inferred\nfrom the query region or from a Buy Now shipping button. The initial allowlist\ncontains only Buldang-dong and Baebang-eup. Validate edits offline with\n`python -m scripts.check_item_area_config`. Verified per-item locality is\nlinked to the exact Route+detail item, and the owner-only encrypted shortlist\nmay include its configured district label. See\n[Item district allowlist](docs/research/ITEM_DISTRICT_ALLOWLIST.md).\nThe unresolved `REGION_MISMATCH` gate is not bypassed.\n\n## OCI FILL precollection operator gate (no listing capture)

A separately owner-approved, manually launched OCI Chrome Stable precollection
experiment now exists at `python -m ops.oci.precollection`. It verifies the
public FILL region picker and fixed filter UI/Route metadata **without** reading
or storing listing fields, changing `ops/oci/runtime.py`, enabling a daemon,
or starting capture. Review the exact approval and non-root isolated checkout
requirements in [OCI precollection gate](docs/research/OCI_FILL_PRECOLLECTION_GATE.md).
Missing server price/category/availability evidence remains blocked; the
experiment never authorizes listing import or collection.

## Safety and scope

- Public pages only; respect robots.txt and access restrictions; do not bypass authentication or anti-bot controls.
- Live collection is manual and owner-approved. CI and OCI validation are offline and synthetic.
- Signed captures are evidence for review, **not** verified purchase availability.
- OCI must verify producer signatures, commit identity and ciphertext before importing. Offsite backups are currently disabled by owner decision; restoring data after disk loss is not guaranteed.
- Do not place secrets or raw listing contents in Issues, pull requests, logs, or artifacts.

The initial public source snapshot is curated from the private development repository at commit `30b8fa7882023d9dbb18f2348c55839a081222fa` without copying its Git history or Actions logs.

Operational setup is intentionally separate from source publication. See `MIGRATION.md` after import for controlled cutover instructions.

## Current ephemeral-data policy

- Backups are **disabled**. Do not enable the Object Storage backup timer or create remote archives.
- OCI Actions intake no longer requires an offsite backup receipt; producer Ed25519 signature, approved GitHub run provenance, archive boundary and local key checks remain mandatory.
- Directly verified SOLD listings are deleted with their observations, events and source evidence. JSON-LD stock hints, missing search results and inferred availability do **not** prove SOLD.
- The owner can delete an unwanted listing permanently from the live SQLite store using `python -m ops.oci.retention forget --state-dir /var/lib/auto-daangn --listing-url '<exact canonical URL>' --confirm-delete` as the `daangn` user.
- No automated inspection of all previously tracked listings for later SOLD state is implemented yet. Existing archives, OS snapshots and external copies, if any, are not purged by database deletion.

## Legacy research and offline regression coverage

The current source of truth is this public repository. The previous private
`kimalswhd0001/auto-daangn` repository remains an owner-only, read-only
historical reference; public CI requires no permission to it. See
[`docs/research/LEGACY_PRIVATE_HANDOFF.md`](docs/research/LEGACY_PRIVATE_HANDOFF.md)
for the historical evidence, strict interpretation limits, restored v4
synthetic tests, missing live-region proof and migration decisions. Historic
raw run evidence, additional live workflow dispatchers and secrets were
**not** imported. Backup services remain disabled by owner policy.
