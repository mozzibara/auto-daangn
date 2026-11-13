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

### OCI filter Apply action stopped before diagnostics (2026-11-13)

Owner updated to PR #60 main `c8fda4d` and verified **13/13**
`test_oci_filter_apply_diagnostics.py` tests. One owner-approved OCI
run returned:

- `region_status=TARGET_REGION_CONFIRMED_DIAGNOSTIC`, header click
  timeout independently verified, one fresh region Route with expected
  server search/filter IDs and UI.
- `precollection.ui_selected_before_apply=true`
- `precollection.filter_apply_returned=false`,
  `precollection.status=BLOCKED_APPLY_ACTION`
- All `filter_transport_diagnostics` counts `-1`, URL
  classification `UNOBSERVABLE`, UI recheck `NOT_RUN`
- No listing collection, no detail visits or database writes.

Unlike the previous `BLOCKED_FILTER_URL` run, this attempt stopped
**while attempting Apply**. Previous code collected the request and
URL diagnostic snapshots only after the Playwright Apply click promise
returned and settled; exceptions skipped that snapshot entirely.
Therefore `-1` means **no snapshot was exported** and does **not**
prove zero requests, nor does it prove the button was not clicked.

The next diagnostics-only revision fixes this instrumentation gap:

- An exact, already verified `적용하기` BUTTON gets a passive
  **trusted** `POINTERDOWN/POINTERUP/MOUSEDOWN/MOUSEUP/CLICK`
  event-count witness, armed before the original `locator.click()`.
  It records at most bounded counts, never button text/HTML or any
  browser private data.
- `apply_action_stage` and `apply_action_exception_kind`
  distinguish a Playwright `TimeoutError` at Apply from errors in
  control setup, postclick settle, network observation or UI recheck.
- A `finally` clause exports **already observed** first-party search
  request/response counters and the redacted filter URL classification
  even if Apply raises; `apply_request_listener_armed` distinguishes
  an armed observer with zero requests from a never armed observer
  with `-1` counts.
- This feature **does not recover from the Apply timeout, repeat the
  click, open a second filter pane, generate extra requests or relax
  the strict URL/Route/price+category+available-only proof**.
  The operator result must still show `STOP_FILTERS_NOT_VERIFIED`
  when Apply is incomplete even if one trusted click is witnessed.

After successful offline CI and merge, owner may run at most one fresh
approved precollection experiment when normal site access permits:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_oci_filter_apply_timeout.py' -v
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_apply_action_diagnostic.json"
```

Interpret `apply_activation.one_trusted_click=true` as
**one dispatched browser event only**, not filter success. Compare
`apply_action_exception_kind`, `apply_action_stage`,
`filter_transport_diagnostics` and `filtered_url_diagnostics` to
identify the next failure boundary. Never continue collecting before
the strict filter evidence is independently confirmed.

### Region lost from filter Apply URL — OCI observation 2026-11-13

After PR #61 (`101e359`), the owner ran 8/8 new offline tests and
one approved OCI FILL precollection check:

- Verified target locality as usual: one trusted header click (timeout
  reconciled), unique target keyword API response, one **fresh** expected
  search Route, `server_search=EXPECTED`, `server_filter=EXPECTED`,
  selected UI EXPECTED.
- The visible category=Digital Devices, maximum price KRW 50,000 and
  available-only controls were selected *before* Apply.
- The single Apply click was independently witnessed as **one trusted**
  pointerdown/up, mousedown/up and click; Playwright returned without
  error (`apply_action_stage=AFTER_TRANSPORT_DRAIN`,
  `apply_action_exception_kind=NONE`).
- During Apply exactly **one browser-generated fetch/xhr request** was
  observed, receiving HTTP 200. It did not match the original *all-five*
  query shape (`search_exact_query_requests=0`).
- In the resulting public search URL the four conditions for **keyword,
  category, price maximum and available-only are EXPECTED**; the sole
  missing expected field is **region `in`**. There were zero additional
  query keys.
- Thus `filtered_url_matches=false`, `filtered_route_count=0`,
  `status=BLOCKED_FILTER_URL`. After-Apply filter UI was never
  rechecked (`NOT_RUN`). None of the server filters can be inferred
  from this non-admitted response in the earlier instrumentation.

This proves **the public UI Apply action produced a regionless filtered
search URL**, not that server locality was reset. Conversely, prior
region selection does **not** prove that the *post-Apply* search region
survived. Repeating Apply or injecting a fabricated region query is not
warranted.

A read-only, **non-admitting** targeted observer now additionally
classifies the **single browser-generated first-party Route response**
whose query has precisely the four expected keyword/category/price/
availability fields but **no `in`** and no extra/duplicate keys:
- It may inspect at most 2 MB of the already-observed JSON response
  **in memory**, reduce only `searchRegion.id`,
  `currentFilters.regionId` and the known category/price/availability
  metadata to `EXPECTED/MISSING/OTHER/AMBIGUOUS` values, and discard
  the source body. It deliberately does not traverse `buySellArticles`
  or serialize raw location, URL, listing, seller or other private values.
- It reports `regionless_route_count`,
  `regionless_route_status=NOT_OBSERVED/ONE_PARSED/ONE_UNREADABLE/
  MULTIPLE_OBSERVED`, and `regionless_server_filters`.
- The existing public header control is passively checked after Apply;
  `post_apply_region_header` is one finite family: TARGET,
  CHEONAN_OTHER, ASAN, SEOUL, OTHER or UNOBSERVABLE.
- The original strict `_unique_query`, accepted
  `filtered_route_count`, post-Apply UI recheck and
  `PRECOLLECTION_EVIDENCE_COMPLETE` predicates are **unchanged**.
  Even a regionless response that claims server region EXPECTED
  **cannot authorize listing collection** without a separately
  reviewed and proven URL/Route admission policy.

After passing all offline CI checks, the owner may choose to run
**one** manual, robots-permitted OCI precollection test:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_oci_filter_regionless_route.py' -v
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_regionless_filter_route.json"
```

If `regionless_server_filters.region=OTHER` or MISSING, the
postfilter search locality is not confirmed; keep capture disabled.
If `EXPECTED`, this is useful supporting evidence but still not
authority to waive the mandatory `in` or post-Apply UI checks.
The purpose of this test is **diagnostic attribution**, not success
by relaxing guards.

### OCI regionless page address but no regionless search request — 2026-11-13

After PR #62 (`12aae1f`), the owner ran 10/10 targeted offline
regressions and one approved OCI FILL precollection attempt.

The latest browser evidence is unusually specific:

- FILL region selection: `TARGET_REGION_CONFIRMED_DIAGNOSTIC` with
  `header_click_returned=true` (no Playwright timeout), trusted header
  click 1, keyword resolver HTTP 200, one fresh Route and both target
  server-region IDs EXPECTED.
- Filter UI pre-Apply matching target digital category/max KRW50,000/
  available-only; Apply had exactly one trusted pointer/mouse/click
  sequence, action returned successfully (`apply_action_exception_kind=NONE`).
- Filter Apply produced **exactly one first-party search fetch/xhr**
  request and HTTP 200; browser address afterwards had expected query
  values for keyword/category/price/available but **no `in`**.
- The strict original Route count remained 0, **and** the diagnostic
  exact-four-param regionless Route count was also **0**. The header
  after Apply still displayed the target region.
- The old counters did not record **which of the five fields (or extra
  query keys) were present on the actual network request**. The fact
  that both exact-five and exact-four route counts are zero means
  the sole request did not match either shape; it does **not** mean
  it had no region or that the returned server region is wrong.
- `BLOCKED_FILTER_URL`, `STOP_FILTERS_NOT_VERIFIED`; all listing,
  database, and production-runtime operations stayed disabled.

**New read-only probe:** within the same one-Apply request listener
window, remember only up to three **safe field verdict snapshots**
from first-party public search requests. If exactly one browser
request occurred, `apply_search_request_diagnostics` reports:

- `observation=ONE_OBSERVED` (else NOT_OBSERVED, MULTIPLE_OBSERVED
  or UNOBSERVABLE), `transport=FETCH_OR_XHR/DOCUMENT`,
  `method=GET/OTHER`, and `outcome=HTTP_200/ACCESS_RESTRICTED/
  OTHER_HTTP/REQUEST_FAILED/NOT_OBSERVED`
- `request_url.shape`, `request_url.fields.keyword/region/category/
  price_max/available` (each EXPECTED/MISSING/OTHER/DUPLICATE/
  UNOBSERVABLE), and only the **bounded count** of unexpected
  parameter names. No raw key name, query, value or request URL emitted.
- `response_url` with exactly the same limited classification, for
  cases where the browser response's URL differed from the initiating
  request.
- `field_verdict_relationship` compares only the **per-field
  classifications** from the network request and final page address.
  SAME is **not** literal URL equality (two OTHER values could differ).
- Neither nonmatching response body nor any listing array is inspected.
  The bounded regionless metadata parser also now requires the actual
  response URL to match the exact safe regionless shape *before*
  reading that response body.

**No authorization change:** The accepted filter Route still requires
the exact five-key query including the correct `in`, one fresh response,
allowlisted server region/category/price/availability metadata and
native visible filter UI recheck. These remain unobserved; even
`apply_search_request_diagnostics` showing request-region EXPECTED
**never authorizes listing collection**. No new browser navigation,
clicks, retries, proxy change or network requests were introduced.

After all four offline CI jobs pass and the update is merged, an
owner-controlled repeat is possible only under the usual
robots/access allowance:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_oci_apply_request_url_verdicts.py' -v
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_network_url_verdicts.json"
```

Use the `precollection.apply_search_request_diagnostics` section
rather than recording HAR/raw URLs. If network request region is
EXPECTED but the final address region is MISSING, next distinguish
network state from visible URL state; if request region MISSING,
explore the search Route behavior and previous locality binding
without inventing a query. If the request has extra keys, compare
known Route metadata shape in an independent controlled fixture
before ever revising acceptance. Continue to fail closed.

### Confirmed extra request key; known Remix search-loader hypothesis (2026-11-13)

After PR #63, the owner ran **12/12** `test_oci_apply_request_url_verdicts.py`
tests and one approved isolated OCI FILL precollection experiment.

- The region selection gate passed with one fresh Route, keyword API HTTP
  200 and expected selected UI/server search/filter region IDs.
- The Apply button returned after one trusted browser pointer/mouse/click
  sequence. The search request was exactly one first-party GET fetch/xhr
  and one HTTP 200 response.
- The network **request and response URLs** each had exactly four
  expected query fields (`q`, `category_id`, `price`,
  `only_on_sale`), missing `in`, plus **exactly one additional
  query parameter**. The post-Apply page URL had the same four expected
  fields, missing `in`, but **no additional parameter**. This explains
  why both existing strict-five and exact-four route observers returned 0.
- The site's rendered header remained TARGET after Apply, but it is
  not independent server-authoritative search-region proof.
- The **identity of the extra key/value was not exposed** by PR #63.
  `regionless_server_filters` and `server_filters` remain MISSING
  because the prior strict matchers refused to inspect the single
  browser-generated query variant. `STOP_FILTERS_NOT_VERIFIED`.

**Source code cross-check:** the existing repository core
`daangn_v4_1_core.py` already recognizes the public Remix search
Route as `_data=routes/kr.search.buy-sell._index`
(`core.ROUTE_ID`). Therefore the single extra key could be this
well-known first-party Remix loader selector; the previous OCI
evidence has **not yet confirmed** its identity.

The new **read-only non-admitting** probe:
- Accepts for *diagnostics only* an **already browser-generated**
  first-party GET fetch/xhr request with the four exact target
  filters, **missing** `in`, and the **one and only** extra query
  key `_data` whose value matches `core.ROUTE_ID`. Unknown keys,
  other route IDs, duplicates, wrong origins/paths and divergent
  response URLs fail closed. Nothing is injected, clicked or fetched
  by the probe itself.
- Distinguishes `request_route_selector` and
  `response_route_selector` into `EXPECTED_SEARCH_LOADER`,
  `NONE`, `OTHER_EXTRA`, `QUERY_MISMATCH` or `UNOBSERVABLE`,
  without printing raw URLs, keys/values or private session data.
- If an exact, known first-party browser route returned HTTP 200
  JSON (<=2 MB), reads it in memory and reduces only the server
  `searchRegion.id`, `currentFilters.regionId`, category, max
  price and availability scalar status. Explicitly skips the
  `buySellArticles` array and never serializes its item contents.
- Adds `remix_regionless_route_count`,
  `remix_regionless_route_status`, and
  `remix_regionless_server_filters` to the **diagnostic only**
  output. For multiple/unparseable/denied responses it reports
  ambiguity/unavailability, not verified server locality.
- **Crucially, unchanged**: a regionless page URL still fails the
  strict original `_unique_query` gate, and the existing accepted
  Route, UI recheck, server price/category/availability/region proofs
  are not bypassed. Even all `EXPECTED` in the new branch cannot
  authorize listing capture/import.

When four offline CI jobs have passed and the PR is merged, the
operator may run one more **explicitly approved** isolated live
diagnostic only if robots/site access continues to permit it:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_oci_remix_loader_filter_metadata.py' -v
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_remix_filter_metadata.json"
```

If the selector is EXPECTED and server region is OTHER, post-Apply
locality is wrong despite the target header; halt. If selector and
server region are EXPECTED, this is valuable independent supporting
evidence, **not automatic collection permission**. Missing price or
availability metadata similarly remains insufficient. Do not repeat,
force, bypass, proxy or collect listing fields to fill evidence gaps.

### After PR #64 — the unknown extra request key is **not** the known Remix loader (2026-11-13)

Owner updated to PR #64 main `3e4b849`, passed 13/13 targeted offline tests, then ran one approved isolated OCI FILL precollection diagnostic. The region gate passed with trusted header click, first-party keyword response 200, one fresh search Route and both server region IDs EXPECTED. Filter Apply delivered one trusted browser click without exception and generated exactly one public GET fetch/xhr HTTP 200.

The **request and response URLs** each contained exactly four expected fixed fields (q, category_id, price, only_on_sale), **no `in` region**, and **one additional parameter**. The final page URL contained the same four filters, no `in`, **no additional parameter**. The new exact known-loader selector reported `request_route_selector=OTHER_EXTRA` and `response_route_selector=OTHER_EXTRA`, so the extra parameter is **not** the exact prior `_data=routes/kr.search.buy-sell._index` hypothesis. This does **not** establish whether the extra key is `_data` with another route ID or a different key. Thus the existing exact 5-field, exact 4-field and known _data loader watchers all count zero; backend locality **after Apply** is still unverified. `post_apply_region_header=TARGET` is UI evidence only.

The next narrowly scoped **no-body-read** discriminator classifies a single extra key in the already browser-observed public search request into a fixed category, without storing the actual key or value:
- `EXACT_REMIX_DATA`: the existing `_data` and exact `core.ROUTE_ID`
- `OTHER_REMIX_DATA_ID`: `_data` with a different value, **not** evidence the other value is safe
- `ROUTES_KEY`: the literal `_routes` key, value intentionally uninspected
- `INDEX_KEY`: the literal `index` key, value intentionally uninspected
- `OTHER_SINGLE_KEY`, `DUPLICATE_EXTRA_VALUE`,
  `MULTIPLE_EXTRA_KEYS`, `FILTER_QUERY_MISMATCH`,
  `NONE`, `UNOBSERVABLE`

Output only `precollection.apply_search_request_diagnostics.request_extra_query_family` and `response_extra_query_family`. No unknown key names, values, raw URLs, HTML, bodies, cookies, token-like text or listing data are exported. This feature never interprets an unknown key as authorization to parse the response, never triggers additional network requests or browser clicks, and **cannot alter the strict no-collection predicate**.

After green offline CI and merge, run the following once only if the site's public robots/access controls permit:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_oci_search_extra_param_family.py' -v
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_extra_query_family.json"
```

**Stop** if an unknown/unsupported key is encountered; do not infer a new route, inject `in`, bypass the UI, fetch unknown response bodies, or activate listing collection. A separate owner review is required to expand any source-verified transport semantics. The current experiment is dedicated to diagnosis only, while the production OCI importer remains unchanged.

### OCI 2026-11-13 — changed Remix _data route ID and Playwright timeout after trusted Apply click

Owner advanced to PR #65 `f4cb4af` in the isolated Ubuntu checkout,
ran **12/12** `test_oci_search_extra_param_family.py` offline tests,
then performed one approved `FILL` precollection test:

- Region gate passed: `TARGET_REGION_CONFIRMED_DIAGNOSTIC`,
  region header click returned normally, one fresh Route with both
  target search/filter region IDs EXPECTED, resolver HTTP 200 and
  selected region UI EXPECTED.
- All fixed filter controls were selected before Apply.
- Playwright Apply `click(timeout=6000)` raised
  `PLAYWRIGHT_TIMEOUT`, stage `BEFORE_APPLY_CLICK`,
  **despite exactly one trusted** pointer/mouse/click event. No second
  Apply click was issued.
- Before the exception **one** first-party GET fetch/xhr request
  started whose **four non-region filters** were EXPECTED,
  `in` MISSING, one extra key. The new key-family diagnostic found
  **`request_extra_query_family=OTHER_REMIX_DATA_ID`**. Thus the
  extra key really **is `_data`**, but its value differs from the
  hardcoded `core.ROUTE_ID`. This is browser-observed evidence that
  the old exact Remix search-loader ID cannot be assumed correct.
- At the instant diagnostics ended, no response was observed
  (`search_requests=1`, `search_responses=0`,
  `outcome=NOT_OBSERVED`). The final page URL was still the
  earlier q-only search, with price/category/available MISSING.
  **This is an intermediate snapshot, not proof of missing filters
  after eventual completion.**
- `BLOCKED_APPLY_ACTION`, `STOP_FILTERS_NOT_VERIFIED`,
  `authorizes_listings=false`; no database, listing/detail or
  production runtime activity.

The next **read-only, non-admitting** instrumentation closes a
diagnostic race: a Playwright action promise may time out even after
its trusted click caused one valid public search request.

When and **only when** a timeout occurred at
`BEFORE_APPLY_CLICK`, the Apply witness proves **one trusted**
pointer/mouse/click sequence, the already armed observer counted
**exactly one** public search request, **zero** failed/restricted
requests and **zero** responses, the operator passively waits
**at most 2 seconds** on the existing browser event-loop.
It does not navigate, click again, issue a fetch, change the Route
validator, or read any unknown Remix response body.

`posttimeout_passive_observation` is one fixed sanitized enum:
`OBSERVED_LATE_RESPONSE`, `NO_RESPONSE_IN_WINDOW`,
`SKIPPED_CLICK_NOT_PROVEN`, `SKIPPED_REQUEST_NOT_UNIQUE`,
`SKIPPED_ALREADY_RESPONDED`, `SKIPPED_RESTRICTED`,
`OBSERVER_ERROR`, `NOT_APPLICABLE`. Existing
`apply_search_request_diagnostics.response_extra_query_family`,
HTTP counters, and final URL field verdicts are then snapshot with
the passive listeners still installed. A late 403/429 is recorded
as restricted, not retried or bypassed. A late HTTP 200 **does not**
change the overall `BLOCKED_APPLY_ACTION` on Playwright timeout;
no subsequent UI recheck is attempted and no listing collection
can be enabled.

This improves evidence quality, **not** the server filter proof
or completeness. A changed `_data` Route ID is not automatically
accepted; the current regionless URL and server-side locality remain
unverified. Exact allowlisted source-level Route authorization would
require a separate, evidenced policy change.

After successful offline CI and merge, only if normal robots/access
rules allow one explicitly approved isolated diagnostic:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_oci_apply_timeout_late_response.py' -v
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_late_apply_response.json"
```

Interpret late HTTP status and `response_extra_query_family` without
outputting private data. **Do not** continue to collect, inject `in`,
guess the new loader ID, issue direct Route requests, bypass site
controls or write to the production importer.

### Region header clicked zero times — OCI precollection run after PR #66 (2026-11-13)

The owner upgraded the isolated OCI checkout to main `5411e2c`,
passed **9/9** `test_oci_apply_timeout_late_response.py`
regressions, and ran one owner-approved FILL precollection diagnostic.

**The failure occurred earlier than the new Apply observer:**
- `status=STOP_REGION_NOT_VERIFIED`,
  `region_status=REGION_HEADER_ACTION_EXCEPTION`,
  `core_progress_stage=BEFORE_REGION_BUTTON_CLICK`
- Playwright region header `locator.click(timeout=5000)` raised
  `PLAYWRIGHT_TIMEOUT`. The pre-existing document event witness
  saw **0 trusted and 0 total clicks**, with button candidates,
  visible and enabled counts each 1.
- `header_timeout_gate_reason=EVENTS_NOT_UNIQUE_TRUSTED`,
  `header_click_verified_after_timeout=false`, no region dialog
  input, no target keyword API request, no fresh region search Route.
- The filter Apply function and the new PR #66 passive timeout
  observer were **never entered**; `precollection=null`.
  No listing reading, export, DB writes or production-state changes.

**Diagnosis boundary:** a button being unique, visible and enabled
does *not* prove that Playwright can send a pointer event. It may
be covered by an overlay, outside the viewport, or fail actionability
for another reason. Prior successful OCI region clicks do not prove
the cause of this **zero-event** attempt.

The next read-only experiment adds two **finite actionability
snapshots** on the existing disposable public Chrome page:
- Immediately before the **same single native** region-header click
  using an optional `ui_select_region` callback (existing callers
  unaffected).
- Immediately after a Playwright header click timeout, before
  evaluating the existing strict one-trusted-click reconciliation gate.

Snapshots include only an allowlisted `document_visibility`,
`document_ready`, known region button count, button
visible/enabled state, coarse rectangle geometry
(IN_VIEWPORT/PARTIAL_VIEWPORT/OUTSIDE_VIEWPORT/EMPTY), one
`elementFromPoint` center-hit category
(TARGET/OTHER_ELEMENT/NO_ELEMENT/OUTSIDE_VIEWPORT), and coarse
pointer-events state (ENABLED/NONE/UNOBSERVABLE). **Never export**
coordinates, hit element identity, button name/label, page HTML, raw
DOM, overlays, locale, URLs, cookies, screenshots, request data or
Playwright exception messages.

The existing trusted event witness, `EVENTS_NOT_UNIQUE_TRUSTED`
hard stop, region API/Route proof and all collection gates remain
unchanged. No retries, force clicks, keyboard substitute, scrolling,
synthetic browser events, stealth or proxy changes. In particular,
one center-hit of TARGET is **only a diagnostic** and never sufficient
to infer a dispatched click.

After four green offline CI jobs and merge, **if robots/access
conditions continue to allow a new owner-approved single run**:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_oci_region_header_actionability.py' -v
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_region_header_actionability.json"
```

Read `region_diagnostics.header_actionability_pre` and
`header_actionability_timeout`; if `center_hit=OTHER_ELEMENT`,
an obstruction is supported without leaking its identity. If
`center_hit=TARGET` but trusted click remains zero, investigate
Playwright actionability/wait behavior with this explicit limitation,
not by retrying or force-clicking. An UNOBSERVABLE snapshot proves
nothing. PR #66's Apply observer remains untested in OCI unless a
later run again reaches that phase.

### OCI region and filter click both succeed, but `in` remains missing — owner observation after PR #67 (2026-11-13)

Owner updated isolated `~/code/auto-daangn-region-diagnostic` to main
`f791d9f`, passed **10/10** new header-actionability regressions, then
ran one approved Chrome FILL precollection attempt.

- The header button was observed BEFORE the click as one unique,
  visible, enabled, in-viewport target with pointer events enabled.
  Playwright click returned normally, and exactly one trusted
  pointer/mouse/click sequence was witnessed. No timeout post-check
  was needed (`header_actionability_timeout=UNOBSERVABLE`).
- Region selection then produced the expected keyword suggestion API 200,
  one fresh public search Route with expected **server search-region ID
  and server filter-region ID**, and the visible header TARGET.
  `TARGET_REGION_CONFIRMED_DIAGNOSTIC`.
- The filter controls were selected before native Apply; one trusted
  Apply click returned successfully without exception. One first-party
  browser-generated GET fetch/xhr search request and its HTTP 200
  response had q/category_id/price/only_on_sale EXPECTED but **`in`
  MISSING** and one extra `_data` with **a different Route ID** from
  the old `core.ROUTE_ID`.
- The final page address also had q/category_id/price/only_on_sale
  EXPECTED and **`in` MISSING**, no extra keys. The existing region
  header still rendered TARGET. Strict exact-five Route, diagnostic
  exact-four Route and old known-loader Route all counted zero.
  `BLOCKED_FILTER_URL` / `STOP_FILTERS_NOT_VERIFIED`. Post-Apply
  persisted filter UI was NOT rechecked, and server-side locality and
  four filter metadata fields remain UNVERIFIED.
- No listing-detail access, listing field extraction, storage,
  production runtime edits or collection authorization.

**New causality hypothesis to test:** the previous reports only
compared the post-region first-party Route/visible header with the
**post-Apply URL**, but did not record when the URL region param
`in` disappeared. The region API/Route is a separate authority from
the browser address: it is possible the URL was already regionless
*before* opening the filter. Conversely, React/Remix filter open,
category selection, availability selection, price fill/blur or Apply
may alter the URL.

A new **passive, no-added-action** fixed-stage URL-region witness
records only allowlisted `EXPECTED/MISSING/OTHER/DUPLICATE/
UNOBSERVABLE` verdicts of the `in` parameter at:
`BEFORE_OPEN_FILTER`, `AFTER_OPEN_FILTER`, `AFTER_CATEGORY`,
`AFTER_AVAILABLE`, `AFTER_MAX_FILL`, `AFTER_MAX_TAB`,
`BEFORE_APPLY`, `AFTER_CLICK_RETURN`, `AFTER_SETTLE` and
`AT_REPORT_SNAPSHOT`.

`precollection.region_url_timeline.stage_region` is fixed-schema,
with `first_missing_stage` indicating the first **observed**
missing `in` when stage evidence was sufficient. A stage marked
UNOBSERVABLE does not prove the region state. If the very first
stage is MISSING, do **not** attribute the loss to the Apply click.
When a Playwright Apply timeout occurs, the final snapshot is an
intermediate observation, not proof of a completed search.

The original `v46.set_filter` call sequence (opening the public
panel, native category/available controls, price input and Tab, then
one ordinary Apply) is unchanged; each optional hook only reads
`page.url` and reduces it to fixed, sanitized verdicts. No URL or
query value exported; no additional click, navigation, injected
request, direct API, response-body read, listing access, retry, or
permission relaxation. Historical and production callers omit the
optional hook. Existing `_unique_query`, backend first-party Route
proof, matching region and server filter metadata, after-Apply UI
recheck and all collection/DB hard stops remain intact.

After all four offline CI jobs pass and PR is merged, optional one
manual operator-approved live precollection diagnostic **only when**
normal robots/access controls still permit it:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_oci_region_url_stage_timeline.py' -v
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_region_url_timeline.json"
```

Interpret the first missing stage together with the region gate,
after-Apply `filtered_url_diagnostics`, and actual network request
fields. Do not rewrite the URL, add `in` manually, trust the new
unknown `_data` body, or start listing capture to compensate for
missing server locality proof.

### OCI URL region absent before opening filter — 2026-11-13 owner verification

Owner upgraded the isolated OCI checkout to PR #68 main
`1c414515e229ec11a5779ae5dc46891c0f40ad73`, passed
`test_oci_region_url_stage_timeline.py` **12/12**, then performed
one owner-approved FILL precollection run.

**Conclusive scope:** the public search page URL already lacked
`in` at `BEFORE_OPEN_FILTER`, and every later filter checkpoint
(OPEN/CATEGORY/AVAILABLE/MAX_FILL/MAX_TAB/BEFORE_APPLY/
AFTER_CLICK_RETURN/AFTER_SETTLE/AT_REPORT_SNAPSHOT) also lacked
`in`. Filter Apply did **not newly remove** the `in` parameter
within the observed sequence. Region-picker browser UI, first-party
keyword resolver and one fresh postclick search Route independently
reported target region; both server search and currentFilter region
IDs EXPECTED. Selected header TARGET. A trusted, normally returned
Apply clicked once; one browser-generated GET fetch/xhr HTTP 200,
four requested non-region filters EXPECTED, `in` MISSING, changed
`_data` ID. Server locality and price/availability/category after
Apply were **not** proven. `BLOCKED_FILTER_URL` and
`STOP_FILTERS_NOT_VERIFIED` remain appropriate. No item/DB/production
activity.

The next root-cause question is whether the selected-region query
`in` was **ever** present during the region-picker workflow and
whether the *correlated fresh post-option-click Route request URL*
contained `in`. The existing region UI/Route validation is
substantive **server evidence** after region selection; it does not
imply the page's URL was updated.

**New non-admitting passive URL provenance observer:**
- Reuses the **existing** region-picker callbacks to classify
  `page.url` immediately BEFORE the single target region-option
  click, AFTER that click returns (or uniquely witnessed timeout),
  AFTER the existing region-selection core function returns,
  AFTER the existing 4.2s settle and BEFORE the existing optional
  filter precollection callback.
- The existing `ManualSearchResponses.after_click()` already ties
  a Route to a request **started after** the trusted option click.
  It already classifies `request_region` from that exact
  response URL without exporting query contents. The new field
  `fresh_route_request_region` exposes **only** that existing
  `EXPECTED/MISSING/OTHER/INVALID` verdict and **only** if
  `route_status=ONE_FRESH`; otherwise UNOBSERVABLE.
- Output:
  `region_diagnostics.region_url_provenance.checkpoints`
  (`BEFORE_OPTION_CLICK`, `AFTER_OPTION_CLICK`,
  `AFTER_CORE_RETURN`, `AFTER_SETTLE`, `BEFORE_FILTER`),
  `first_observed_missing_stage` and
  `fresh_route_request_region`. Values are fixed enums, no
  raw URL/path/query/slug/region ID stored or exported. The
  first observed missing checkpoint is a **temporal observation**
  not proof of its causal mutation step; gaps → INCONCLUSIVE.
- In particular a fresh Route request with `in=MISSING` whose
  **response** contains both region IDs EXPECTED would support
  the hypothesis that the site can return a region-specific
  server result without encoding locality in the request URL.
  It still would **not** prove that a later *filtered* Route has
  the same locality.
- No new clicks, request registrations, navigation, timers,
  force actions, cookie/storage inspection, new response-body
  parsing or collector permission. Existing region API/Route
  authentication, exact filtered `in` URL requirement, price
  metadata and post-Apply filter UI gates remain unchanged.

After all four offline CI tasks are green and the PR merged,
the owner may run **one** isolated approved observation only if
current public robots/access controls permit:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_oci_region_route_url_provenance.py' -v
set -o pipefail
xvfb-run -a python -m ops.oci.precollection --live --headed --owner-approval I_APPROVE_OCI_PRECOLLECTION_FILL_V1 | tee "$HOME/daangn_oci_region_route_url_provenance.json"
```

Inspect only `region_diagnostics.region_url_provenance`, existing
`region_route_status`, `region_server_search`,
`region_server_filter` and
`precollection.region_url_timeline.BEFORE_OPEN_FILTER`.
If `fresh_route_request_region=MISSING` alongside server EXPECTED,
do **not** simply remove the later exact-region URL requirement or
interpret a filtered 200 as region proof. Redesign requires separate
postfilter proof independent of legacy request form and explicit
owner approval; no listing read/import is permitted in this probe.

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
