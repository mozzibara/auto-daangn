# Legacy private-repository research: implementation handoff

Last reviewed: 2026-11-11. Primary development repository: `mozzibara/auto-daangn` (public).
Historical read-only reference: `kimalswhd0001/auto-daangn` (private; owner-only access).
Reference snapshot: private `main` `30b8fa7882023d9dbb18f2348c55839a081222fa`.
This document is a curated summary of software behavior and experimental limits,
**not** a reproduction of historical raw data or secrets. The private repository
is not a deployment dependency.

## 1. Migration facts and decision

At snapshot comparison there were 291 tracked private files versus 123 in
public `main` (before this handoff); 92 files matched byte-for-byte by
Git blob SHA, 20 shared filenames had divergent contents, and 179 were only
in private. Most working v4 collectors, state/price/category processors, v5
SQLite/analysis/Telegram modules, cryptographic importers and OCI runtime
modules were already in public and should **not** be copied backward from the
private snapshot. The public versions include newer trust checks, the
owner-approved backup-disabled policy, deletion semantics and updated region
diagnostics. The missing files were predominantly old research documentation,
per-version diagnostic Actions, legacy harness scripts and synthetic tests.

**Chosen architecture:** One self-contained, reviewed public application repo
for live producer and CI, plus the original private repo as a historical
owner-only archive. Import only sanitized, independently useful docs and
offline tests after review. Do not create a third synchronized reference repo
or grant public CI broad access to the private repository.

## 2. Historical experimental evidence worth preserving

These are *historical observations*, not promises about today's site shape.

| Research version | Evidence / useful design requirement | Explicit limitation |
| --- | --- | --- |
| v4.1-v4.6 | Public search region, keyword, category, price and availability controls must be observed; exact region IDs used in historical Cheonan/Asan test presets were 2292/2333 | URL query alone is not positive server enforcement evidence |
| v4.8-v4.10 | Distinct UI-selected price intervals and Route structures were compared; pagination/cursor not proven | Do not invent a second page or search endpoint |
| v4.12-v4.14 | About 269-271 items appeared in a correlated first-party Route response while the rendered DOM exposed about 32 | One Route body is not exhaustive coverage of all marketplace listings |
| v4.15-v4.19 | Recheck selected filter state after reload and distinguish raw server response fields, parser-supported fields, UI evidence and behavioral price-cap evidence | Behavioral correlation is an advisory grade, not server-declared max-price proof |
| v4.20-v4.27 | Verify individual listing identity, category, primary item UI and stock as independent sources; require canonical orthogonal state projections | Related-card badge and stock fields do not directly establish current-item trade state |
| v4.28-v4.31 | User-approved practical candidate policy: exact Product/Offer InStock and no primary SOLD/RESERVED indicator can be considered **possibly available** without requiring a visible FOR_SALE badge | This is inference only; retain NOT_OBSERVABLE canonical transaction state |
| v4.32-v4.33 | Join sale-inference, **same listing** numeric Route price and confirmed detail category. Deduplicate with same-run identity binding | Cross-run HMAC identifiers cannot be safely equated; a recommendation candidate is not a confirmed purchase opportunity |
| v4.34-v5 | X25519/HKDF/AES-GCM sealed title/URL payload and independent Ed25519 producer attestation bound to the expected repo, branch, commit, workflow run and artifact | Encryption by itself does not authenticate the producer |

Historical source document names include `V4_14_FULL_ROUTE.md`,
`V4_15_UI_FILTER_RECHECK.md`, `V4_19_FILTER_SCHEMA.md`,
`V4_23_PUBLIC_STATE_CONTROLS.md`, `V4_26_CANONICAL_ONLY_PIPELINE.md`,
`V4_31_PRACTICAL_SALE_AVAILABILITY_POLICY.md`,
`V4_32_RECOMMENDATION_CANDIDATE_JOIN.md`,
`V4_34_ENCRYPTED_CLICKABLE_UNIQUE_RECOMMENDATIONS.md`,
and `V5_0_V434_SIGNED_PROVENANCE.md` in the owner-only archive.

## 3. Current blocker: verifiable locality, not missing historical code

Approved v4.34 live runs #3-#6 in the public repo established that the
HTTP response strips the search URL's `in` parameter from a Cheonan
`q=HDD` request. The original URL had the historical expected region ID
2292; the resulting page did not. A bounded robots-approved public UI
region choice clicked the button and selected a suggestion, but neither
the selected region ID in the final URL nor the legacy visible-region
button was proven. No detail visits, sealed artifact or production import
resulted. See public issue #11.

Do **not** treat a successful UI click, original request URL, stale
`window.__remixContext`, filtered search membership or a plausible
marketplace card as proof of Cheonan locality.

**Proposed next implementation:** separately classify a fresh post-selection
visible region UI witness and a **fresh UI-generated first-party search Route
response**. Require the response's actual `searchRegion.id` and
`currentFilters.regionId` to match the expected region, and the expected
keyword. Preserve UI/Route response-body correlation, category, availability,
price and per-item identity verification. If fresh response metadata does not
declare a trustworthy region, fail closed. Never bypass access restrictions,
CAPTCHA, robots.txt or login. Do not construct undocumented Route requests.

## 4. Current operational scope and retention

- GitHub Actions is an explicitly owner-approved producer, not an unattended
  crawler. The public repo and GitHub Actions signer identity are pinned.
- OCI SECOND-INSTANCE imports only authenticated and bounded sealed artifacts.
  A dry-run and successful actual run are prerequisites to enabling intake.
- Owner explicitly deferred offsite backup to possible future Google Drive
  or NAS design. Keep the Object Storage timer and old mandatory backup gate off.
- SQLite is short-lived shopping state. Directly verified current-item SOLD
  and owner-explicitly discarded listings are deleted with linked evidence.
  Never infer a sale solely from a missing search result, JSON-LD OutOfStock,
  a linked card or another item's status.
- Pre-OCI AI query expansion, multi-query dedup, scoring and Telegram outbox
  are **offline-validated building blocks**, not proof that production
  multi-query capture, automatic alerts or delivery are active.
- Do not add public CI access to the private repository. All production source
  dependencies and required regression fixtures must be in public main.

## 5. Reference material intentionally not copied

| Historical asset | Disposition | Reason |
| --- | --- | --- |
| `evidence/reference_runs.json` (~379 KB) | Remain private | Historical run-scoped anonymized listing identifiers and timestamps; unnecessary for public CI and could facilitate correlation |
| 24 legacy live-diagnostic workflow YAMLs | Remain private | Avoid accidental, duplicate owner-approval paths and unreviewed live site visits |
| Old OCI backup instructions and systemd units | Remain private as history; public current policy wins | Owner disabled backups; restoring old gates would block intake |
| Key material, GitHub Secrets, private logs, databases | Never import | Credential/data exposure and long-term data-retention risk |
| Old Windows `.cmd` harnesses and summary scripts | Remain private unless individually needed | Platform-specific historical wrappers do not belong in minimal cloud runtime |
| Legacy full research docs | Source archive retained, curated findings summarized above | Avoid publishing owner-only run metadata or stale instructions |
| Six high-value synthetic v4 test files | Restored to public `tests/` | Protect region, search config, filter-gate, canonical state semantics |

## 6. Implementation priorities

1. **P0** Region proof based on **fresh** visible UI and UI-triggered Route
   response, preserving all existing fail-closed filters. Synthetic tests
   should cover HTTP 302 query stripping, UI-only changes, contradictory or
   absent response regions, stale loader, wrong item and access restrictions.
2. **P1** Add source-bound synthetic regression suites for price-cap
   behavioral versus declared metadata, exact detail identity/category,
   practical `InStock + no SOLD/RESERVED UI` interpretation, and duplicate
   item conflation. Port only tests whose dependencies exist in the public repo.
3. **P1** Owner-authorized short-term exclusion state / non-recommendation,
   SOLD recheck on a bounded verified public page, and deterministic deletion
   of obsolete SQLite-linked records. Do not retain dead listings indefinitely.
4. **P2** Wire the already-available offline `app_v5/query_expansion.py`,
   `app_v5/multi_query_dedup.py`, `app_v5/analysis_profiles.py` and
   `app_v5/telegram_outbox.py` to a tested, manually approved production
   pipeline with strict rate/retention controls.
5. **Deferred** Optional encrypted Google Drive / NAS backup after a separate
   owner decision. Do not silently reactivate OCI Object Storage backups.

## 7. Developer verification

Run from the public repository root:

```bash
python -m compileall -q .
python -m scripts.audit_state_conversions_v425 --output v426_canonical_conversion_audit.json
python -m unittest discover -s tests -p 'test_*.py' -q
```

Tests must be synthetic and offline. The actual live workflow remains
restricted to the trusted owner and must never run on ordinary push/PR.
For archival research, consult the private repository with owner access;
there is no GitHub Actions credential linking the two repositories.
