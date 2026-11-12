# auto-daangn: target architecture and operational optimization (2026-11)

Status: **design + offline-validated foundations**. This document is not a claim of
production deployment, current marketplace access, successful OCI backup, a
ChatGPT connector, or a live Telegram sender.

## Decision

Use four independent execution domains. Do not push SQLite or decrypted
listing data back to a Public GitHub repository:

```text
Approved intent + region/category/price/status filters
         |   (trusted owner approval, bounded rate)
         v
GitHub Actions (public repository, Ubuntu Chromium)
  robots-first public UI -> route/detail evidence -> canonical candidate
  -> X25519 recipient encryption -> Ed25519 producer attestation
         |   only sealed artifact and redacted counts, retention 1 day
         v
OCI SECOND-INSTANCE (E2.1.Micro, ~1 GB RAM)
  15-minute pull timer [enable only after signed dry-run]
  -> validate GitHub actor/repo/workflow/main/commit/run
  -> verify ZIP + Ed25519 signature + pinned producer key
  -> decrypt in local private state -> SQLite WAL price history
  -> bounded candidate/price-change outbox
         |                                  |
         +-> backups disabled by owner       +-> read-only review output
             (future Drive/NAS option)            through future authenticated
                                                   ChatGPT connector / user upload
         |
         +-> future outbound Telegram sendMessage / getUpdates
             notification + allowlisted feedback only
```

### Responsibility boundaries

| Component | Does | Must not |
|---|---|---|
| GitHub Actions | Manual owner-approved browser, robots check, bounded evidence capture, encryption and Ed25519 attestation, *synthetic* tests | Keep seller/user raw data in public logs, artifacts or source; run unrestricted scheduled scraping |
| OCI SECOND-INSTANCE | Small Python runtime, pull sealed artifacts, validate identity and signature, SQLite ephemeral history, outgoing notifications | Run Chromium, a local LLM, GPU inference, or an unauthenticated HTTP listener |
| ChatGPT | On-demand analysis of carefully scoped, authorized review records and user-provided context | Be treated as a durable database or a direct authenticated OCI client before an explicit connector is installed |
| Telegram | Notifications and narrowly scoped user responses | Act as the authoritative state database or publish bot credentials |
| Deferred backup | Google Drive / NAS are future options; no automatic backup currently runs | Enable cloud uploads without a new owner decision |

### Explicit exception: isolated OCI operator-run precollection experiment

A separate **manual, unprivileged, owner-approved** FILL-only Chrome diagnostic
can run in an isolated home-directory source checkout on the OCI x86_64 host.
It checks a single public region selection and visible public filter controls
plus first-party Route metadata, then stops before any listing field export,
article/detail visit, capture signing or SQLite import. This is **not** a new
feature of the `ops/oci/runtime.py` production import daemon and is never
started by its systemd services/timers. No production state or credentials are
loaded. See [OCI FILL precollection gate](docs/research/OCI_FILL_PRECOLLECTION_GATE.md).
Promoting browser work into the production OCI role requires a separate
resource/security/scheduling decision. The import-only baseline remains
unchanged.

## P0: public repository / trust plane (current work)

- Repository: `mozzibara/auto-daangn` Public. Private development history retained
  separately in `kimalswhd0001/auto-daangn`; **do not run Actions there**.
- Provenance identity is now the public repository; public issue approval is #1.
- `main` must be protected with a public GitHub Free ruleset: block force pushes and
  deletion, require pull requests (solo owner: **0 required external approvals**),
  pass Ubuntu/Windows offline CI and enforce least privilege. Use the exact
  API body in `ops/github/main-ruleset.json`. Configuration instructions are
  in `PUBLIC_SECURITY_SETUP.md`.
  This cannot be represented by a committed YAML file alone.
- Default Actions `GITHUB_TOKEN`: read only. No secrets exposed to PR jobs.
  Consider pinning GitHub Actions dependencies to verified immutable SHAs.
- No scheduled live capture. Manual `workflow_dispatch` or exact owner comment.
- `V434_ATTEST_ED25519_KEY_B64` must be configured as **Environment Secret**
  under `daangn-producer`, with Selected deployment branch **main only**.
  Never use a repository-wide signer Secret. Offline-verify the original
  private seed against the pinned public key before uploading directly through
  the trusted owner's GitHub UI/CLI. The pin remains unchanged until an
  explicit independently verified key rotation.
- Offline CI: do not install Chromium binaries or retain public unittest log
  artifacts; live capture job alone installs Chromium. Stale CI for superseded
  commits may be cancelled without affecting the live approval concurrency.
- Add source contract tests for owner, repository, Issue #1, token permissions,
  absence of automated live triggers, and absence of local private state.

## P1: reliable encrypted-artifact ingestion

**Current code** already verifies exact owner, repository, branch, event, SHA,
trusted Ed25519 producer, exact ZIP members and at-most-one import
per polling operation. All of these checks must stay fail-closed.

- Legacy design queried *all* successful live run history with
  `per_page=100&page=1`: after 101 successful runs, OCI would reject every
  poll forever. Query a recent UTC date window instead (at least 48 hours,
  up to 72 hours by calendar-day filtering). Reject incomplete pages rather
  than silently skipping records.
- The capture artifact expires after **one day**. The 48-hour API lookback
  does **not** extend artifact lifetime. Alert if a polling failure approaches
  the retention horizon. A 15-minute timer does not guarantee delivery during
  outages.
- Backups and the offsite import gate are **disabled by explicit owner decision**.
  Retain source/owner/Ed25519/ciphertext verification. Do not enable the
  Object Storage timer. A later Google Drive/NAS backup requires new design/tests.
- Verified current SOLD listings are removed transactionally together with
  listing-specific observations, events and evidence. Explicitly unwanted
  listings are deleted by the owner using the retention CLI. Missing search
  results, JSON-LD stock hints and an inferred sale state never trigger deletion.
- Exactly one new signed bundle per invocation caps SQLite/CPU peak usage on a
  one-gigabyte OCI instance. Intake, offsite backup and health systemd services
  now take the same bounded `flock` on a private local path, so they never
  run simultaneously even if their calendar timers coincide. If lock
  contention exceeds 20 seconds, the failed oneshot is visible in journal
  and the next timer invocation can retry; do not hide it as success.
- A catalog with more than 100 eligible recent runs is an **operational alarm**,
  not a reason to silently drop older runs. To scale beyond that, build an
  explicitly tested page-and-checkpoint algorithm with separate freshness,
  retention and failure semantics.
- Old private-repository signed attestations do not authenticate the new
  public producer; never remap their old repository field.

## P2: user-facing alert pipeline (not live yet)

- Use the existing `app_v5.telegram_outbox` as the state machine:
  `NEW -> LEASED -> ACK / RETRY / DEAD`. Keep send operations separate from
  SQLite commit transactions. Telegram does **not** offer an API-level
  idempotency key; duplicates are possible if OCI crashes after remote accept.
- Implement a *future* outbound-only sender with local 0600 token/chat config,
  bounded HTTP timeouts, 429 `retry_after`, backoff and dead-letter visibility.
  Do not embed tokens in Actions or public Issues. Prefer no inbound webhook:
  `getUpdates` long polling if feedback is later enabled.
- Trigger messages only from verified price drops or narrowly defined advisory
  events. Attach the current status **uncertainty** (reviewable ≠ for sale).
- First provide Telegram controls: `interested`, `ignore`, `hide seller`,
  `watch keyword`, `snooze`, then save feedback events to private SQLite.
- Do not let Telegram feedback directly expand live crawling or change approved
  region/price/category without a separate owner allowlist.

## P3: ChatGPT-assisted analysis / data access (not live yet)

- Keep high-volume data capture deterministic in Python. Use AI selectively
  for item identity, NAS suitability, SMART interpretation, pricing context,
  relevance and explanations. AI-generated keywords are **proposals only**;
  `app_v5/query_expansion.py` already requires a separate approved allowlist
  and caps source visits.
- Do not expose port 80/443/SSH on OCI solely for a chatbot. Initial review
  can use user-selected, locally produced minimal reports. For on-demand
  ChatGPT access, provision an explicitly authenticated read-only connector or
  tool: TLS, per-user scope, short-lived tokens, rate limits, audit logs,
  response-size bounds and redacted-by-default fields. No generic unauthenticated
  public OCI REST endpoint.
- The assistant cannot automatically discover or call an arbitrary private
  OCI service just because its URL appears in an instruction.
- AI output is advisory and must include evidence grade, observation time and
  independently unverified sale status. Do not convert `InStock`/missing UI
  badge to a confirmed seller transaction state.

## P4: automation controls and SLOs

1. **Source**: manual capture approvals remain explicit until the site's
   restrictions and robots policy have been rechecked and the user separately
   chooses a scheduling policy.
2. **CI**: offline test pass on Ubuntu/Windows; no browsers launched in tests.
3. **Storage**: SQLite `integrity_check` and signer/HMAC continuity; WAL
   snapshot must survive independent restore before ingestion activation.
4. **Freshness**: alert on expired/missing artifacts, GitHub API 403/429, backup
   gate denial, or no verified intake after a known successful capture.
5. **Resource use**: bound archive size, per-file extracted size, payload size,
   SQLite transaction time, simultaneous timers, API retries and message size.
6. **Cost**: Public GitHub standard runners are free; OCI Object Storage usage,
   internet traffic, and any external AI API or messaging limits are separate.
7. **Operability**: every live task must have a bounded timeout, classified
   failure, readable redacted status, explicit retry policy and no silent
   degradation from verification to inferred availability.

## Release gates and rollbacks

- **G0 (code)**: public repo contract tests and synthetic CI pass; protect
  `main`, review workflow changes. No live secrets needed for G0.
- **G1 (signer)**: independent signing-key match, owner-only manual workflow,
  correct new repository identity. No real capture before this.
- **G2 (backup)**: deferred by owner. No Object Storage upload or backup gate
  is enabled; data can be lost on an instance failure.
- **G3 (ingest)**: one exact approved capture, signed artifact, verified OCI
  decryption and one idempotent SQLite import; no backup receipt required.
- **G4 (alerts)**: synthetic Telegram adapter and feedback authorization tests
  before any real send; release alerts separately from ingestion.
- **G5 (AI bridge)**: authenticated minimal read-only review access, privacy
  boundary tests and user-owned token rotation before unattended use.

Rollback is source-only while state remains untouched: disable intake
timers, revert code to the verified checkout and preserve private SQLite,
HMAC and recipient keys. Never reset `/var/lib/auto-daangn` to roll back code.
