# auto-daangn

Public source snapshot of the owner-approved, read-only Daangn listing research and v5 evidence pipeline.

This repository contains source code, synthetic tests, and opt-in GitHub Actions. It does **not** contain an operational database, live listing data, private keys, GitHub tokens, OCI credentials, or Telegram credentials.

## Safety and scope

- Public pages only; respect robots.txt and access restrictions; do not bypass authentication or anti-bot controls.
- Live collection is manual and owner-approved. CI and OCI validation are offline and synthetic.
- Signed captures are evidence for review, **not** verified purchase availability.
- OCI must verify producer signatures, commit identity, ciphertext and independent offsite backup before importing.
- Do not place secrets or raw listing contents in Issues, pull requests, logs, or artifacts.

The initial public source snapshot is curated from the private development repository at commit `30b8fa7882023d9dbb18f2348c55839a081222fa` without copying its Git history or Actions logs.

Operational setup is intentionally separate from source publication. See `MIGRATION.md` after import for controlled cutover instructions.
