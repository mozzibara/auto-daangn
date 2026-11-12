# OCI FILL-only precollection readiness gate

## Purpose and boundary

This one-shot **operator-run** command carries the already proven OCI
`FILL` region-selection method into a separate **precollection** gate.
It is NOT an implementation of live listing capture or a replacement
for `ops/oci/runtime.py`, which continues to perform only signed
artifact import, local key/DB operations and status.

This phase performs, in a single disposable Chrome context:
1. **Explicit exact owner approval** and unprivileged isolated checkout
   (the dedicated `~/code/auto-daangn-region-diagnostic`, NOT any
   `/opt/auto-daangn*` or `/var/lib/auto-daangn` state).
2. **Robots-first** public-search and exact region-keyword endpoint
   checks; stop if absent/denied.
3. **One** Chrome region picker selection using the previously proven
   `FILL` mode, its stringent delivered-once click-timeout proof,
   the exact candidate API ID and **one new search Route** with
   expected server search/filter region plus selected UI.
4. Only if step 3 returns `TARGET_REGION_CONFIRMED_DIAGNOSTIC`,
   set the **visible public filter UI**: HDD / Cheonan Buldang-dong,
   Digital Devices (`category_id=1`), max KRW 50,000, available-only.
5. Make **one visible Apply** interaction, never force or replay a click.
   Observe newly started first-party filtered search Route requests and
   responses. Check the resulting public search URL, reopen the filter
   panel if needed, and independently re-read native selected controls.
6. Parse **only** allowlisted server `searchRegion`/`currentFilters`
   metadata from transient in-memory response bytes. Never iterate,
   return, serialize or save any listing array or product/article field.
7. Report `PRECOLLECTION_EVIDENCE_COMPLETE` **only** if exact region,
   visible filter controls before/after apply, exact filtered URL,
   exactly one fresh first-party route, category/available/max price
   server metadata and region IDs are all present and matching. If
   the current server omits max-price metadata, return
   `BLOCKED_FILTER_ROUTE_METADATA`. Frontend `price=__50000`
   alone is **not authoritative** server price enforcement evidence.

Even if every gate passes, the report always includes:
`collection_started=false`,
`listing_detail_visited=false`,
`listing_data_exported=false`,
`database_written=false`,
`authorizes_listings=false`,
`next_action_requires_separate_owner_approval=true`.

No raw listing URLs/titles/seller identifiers, full HTML/response bodies,
cookies, exact IP, raw request URLs, browser traces or screenshots are
ever printed or saved. We do not run the legacy v4.6 capture entrypoint,
v4.34 encrypted capture, or OCI private import, and do not configure a
new daemon, systemd service, network listener, SSH key, scheduling,
screenshot upload or automated retry.

### Fixed approved profile

| Field | Required |
|---|---|
| Region | Cheonan Buldang-dong, preset ID 2292 |
| Keyword | `HDD` |
| Category | Digital Devices, `category_id=1` |
| Max price | KRW 50,000 |
| Available-only | True |
| Input mode | `FILL` **only** |
| Browser | Chrome Stable via Xvfb, no login/session reuse |
| Number of live attempts | At most **one** approved public search/region context |
| Listing/detail visits | **Zero** |

## OCI operator steps (without touching production state)

Check the new PR's **four offline CI jobs** are successful and the code
has been merged to `main` first. In an existing, unprivileged Ubuntu
shell with the separately installed Chrome and Playwright:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate

# Zero marketplace calls:
python -m unittest discover -s tests -p 'test_oci_precollection_gate.py' -v

# Only if current robots/site access rules permit, manual one-shot approval:
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_precollection_gate.json"
```

This command **does interact with the public search filter UI**, but
does not start listing capture. The shell may exit with status 2
because the gate correctly fails closed (for example if the server
does not expose the max-price field). Treat `status` and
`precollection.server_filters` as evidence, not permission to import
listing data.

### OCI live `REGION_HEADER_ACTION_EXCEPTION` regression and diagnostic update

Owner ran this exact Phase-1 precollection command on the isolated OCI
Ubuntu host after PR #58. All **19 dedicated offline tests passed**.
The real one-shot result was:

- `status=STOP_REGION_NOT_VERIFIED`
- `region_status=REGION_HEADER_ACTION_EXCEPTION`
- `region_header_timeout_reconciled=false`
- `precollection=null`
- `authorizes_listings=false`, `collection_started=false`,
  `database_written=false`

This means **filter Apply was never reached**. It does not disprove
the preceding, independently observed FILL success; the new single-arm
precollection test did not reproduce it. The operator's output omitted
the previously available bounded `picker_phase_diagnostics`, so a
header `locator.click()` timeout cannot yet be attributed to a missing
real browser click, duplicated event, remounted header, unready input,
or unexpected exception.

The following revision surfaces only **fixed classes and counts**
as `region_diagnostics`, even on failure:
- `core_progress_stage`, `step_error`, `readiness_state`
- `header_click_exception_kind` (`PLAYWRIGHT_TIMEOUT` /
  `OTHER_EXCEPTION` / `NONE`)
- `header_timeout_gate_reason`:
  `NOT_INVOKED` (no timeout callback), `PAGE_NOT_PUBLIC_SEARCH`,
  `WITNESS_NOT_ARMED`, `WITNESS_UNAVAILABLE`,
  `HEADER_CONTROL_NOT_UNIQUE`, `EVENTS_NOT_UNIQUE_TRUSTED`,
  `INPUT_PROBE_ERROR`, `INPUT_NOT_UNIQUE_VISIBLE`,
  `INPUT_NOT_EMPTY_ENABLED_DIALOG`, `VERIFIED`,
  `UNOBSERVABLE`
- bounded `header_trusted_click_count`, `header_total_click_count`,
  `header_candidates`, `header_visible`, `header_enabled`,
  two visible input counts, focus class, and region keyword API/Route
  states

A value of `-1` means **not observed**, not zero; no raw URLs,
region strings, exception messages, cookies, DOM, listing/price
content or IP data are written to the report.

**Do not loosen any precollection or region admission predicate** in
response to a single failed live attempt. Keep the exact existing
single-click condition and no-collection restriction; use the
categorized failure to choose the next minimal code correction.

### OCI first successful locality + filter URL gate failure (2026-11-13 KST)

After PR #59, the owner ran ten diagnostic unit tests (10/10 pass) then a
single approved FILL precollection test in an isolated Ubuntu session.
**The region gate passed** (trusted header click timeout reconciled,
first-party keyword API 200, exact region option, one fresh first-party
search Route, both server region IDs and UI selected state EXPECTED).

The subsequent filter UI setup observed `ui_selected_before_apply=true`
for Digital Devices / maximum KRW 50,000 / available-only. The Apply
button's Playwright action returned successfully. The gate then yielded:

- `status=STOP_FILTERS_NOT_VERIFIED`
- nested `precollection.status=BLOCKED_FILTER_URL`
- `filtered_url_matches=false`; `filtered_route_count=0`
- `ui_selected_after_apply=false` because the verifier returned **before
  calling** the UI recheck, not because a mismatch was observed
- no item collection, detail visits or DB writes

**Neither a wrong resulting URL nor an absent network response can be
concluded from these coarse fields alone.** The existing observer
accepted only browser-generated GET fetch/xhr responses whose URL matched
*all five exact expected query parameters*, so a legitimate browser
request with an extra benign query parameter, a different URL encoding,
a document navigation, a missing/mismatched filter parameter, or no
request at all could yield a zero accepted-response count. This does NOT
justify weakening `_unique_query` or authorizing listing collection.

The diagnostic-only follow-up records these fixed, private-data-free
fields:

- `filtered_url_diagnostics.shape`: first-party search path vs other
  origin/path vs unobservable.
- `filtered_url_diagnostics.fields`: keyword, region, category,
  price_max and available separately as `EXPECTED`, `MISSING`,
  `OTHER`, `DUPLICATE` or `UNOBSERVABLE`.
- `filtered_url_diagnostics.unexpected_keys`: small bounded number
  of other query parameter **names** (neither names nor values exported).
- `filter_transport_diagnostics`: bounded counts of **browser-generated,
  first-party search requests** seen during this single filter Apply;
  fetch/xhr vs document, exact vs different URL, 200/restricted/other
  responses and request failures. It never reads the body of nonmatching
  URLs and never generates its own requests.
- `ui_after_apply_recheck_state=NOT_RUN` when the strict URL mismatch
  prevents the existing UI recheck, instead of suggesting a false
  observed UI mismatch.

**No existing admission rule changes.** The strict URL still has to
match all five expected parameters, the exact newly started Route and
its server metadata must be verified, and native filter UI must be
rechecked before reporting readiness. The result always has
`authorizes_listings=false`.

After the update is merged and offline CI passes, in the original
non-root, isolated OCI checkout:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_oci_filter_apply_diagnostics.py' -v
# Only if the public robots/access gates permit one approved test:
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_precollection_filter_diag.json"
```

Do **not** use generic Playwright HAR, screenshots, raw URL logs or
response-body dumps for this investigation; the new fixed enums and
counters suffice to decide the next scoped change. Do not rerun if
access is restricted.

### Outcome interpretation

| Status | Operational interpretation |
|---|---|
| `PRECOLLECTION_EVIDENCE_COMPLETE` | All fixed filter metadata and UI corroborated; still no collection permission |
| `STOP_REGION_NOT_VERIFIED` | FILL region failed the fresh Route/selected UI proof; no filter actions executed |
| `STOP_FILTERS_NOT_VERIFIED` | Locality succeeded but some filter evidence failed or was omitted |
| nested `BLOCKED_FILTER_CONTROL` | Filter controls missing/ambiguous or selected UI does not match |
| nested `BLOCKED_APPLY_ACTION` | Apply click failed; no duplicate click/retry |
| nested `BLOCKED_FILTER_URL` | Resulting URL missing/wrong/ambiguous target fields |
| nested `BLOCKED_FILTER_ROUTE_MISSING` | No fresh exact filtered response observed |
| nested `BLOCKED_FILTER_ROUTE_AMBIGUOUS` | Multiple candidate responses, cannot attribute |
| nested `BLOCKED_FILTER_ROUTE_METADATA` | Server filter category, region, price or availability fields absent/different |
| nested `BLOCKED_UI_RECHECK` | Native visible controls could not be verified after Apply |
| `ROBOTS_NOT_ALLOWED` | Do not continue; site's public access gate rejected/unavailable |

### Evidence limits

Precollection proof does NOT demonstrate actual listing prices, category
or sold/reserved state by item, complete pagination, deduplication,
listing locality in the item itself, security of seller URLs or the
v4.34 signing/encryption pipeline. Those require independent,
separately approved tests and must not be inferred from a successful
filter UI or URL.

The `currentFilters` server metadata may have missing price fields.
In that case the gate intentionally blocks rather than weaken the
historically required consistency proof.

The old `ARCHITECTURE.md` assigns OCI an import-only role. This
owner-run experimental precollection Chrome checkout is an
**explicitly separate research lane**. It is not installed as an
OCI service or enabled by the production intake timer. A production
role/architecture change would require a separate decision.
