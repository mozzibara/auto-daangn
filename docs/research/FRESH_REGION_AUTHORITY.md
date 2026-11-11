# Fresh UI + Route locality authority

## Problem and historical evidence

The owner-approved v4.34 captures #3-#6 (2026-11-11) showed that a
`q=HDD&in=불당동-2292` first-party search URL was redirected to a URL
without `in`. A public UI region picker could be clicked and the suggestion
selected, but the browser still did not contain an `in` parameter. The legacy
v4.14 baseline and v4.8 filter-Route correlator required an encoded URL region,
so all live captures failed with `REGION_MISMATCH`.

Historical owner-only v4.1 and v4.14 research required an independently
visible region UI, an actual fresh first-party Route `searchRegion.id` and
`currentFilters.regionId`, and exact UI-generated response correlation.
The boot-time `window.__remixContext` can be stale after SPA transitions.
This policy adopts those constraints; it does **not** infer a region from
the listing set or a previously requested URL.

## Current implementation

- `daangn_full_route_v4_14.capture` accepts a missing `in` after exactly
  one robots-approved public UI selection as **provisional** only. Wrong
  explicit region, wrong host, wrong path, changed keyword or access restriction
  still stop immediately.
- `daangn_price_bands_v4_8.capture_apply` observes a fresh XHR/fetch Route
  produced by the actual Filter → Apply UI action, under a bounded listener.
  No manually generated Route URLs or arbitrary query attempts are used.
- `app_v5.region_proof.verified_region` requires all of:
  1. A visible, scoped selected-region control **or** an actual, uniquely identified visible public region suggestion clicked during this capture. A generic success flag or ambiguous matching option is insufficient;
  2. A single current XHR/fetch result with first-party HTTPS search URL,
     HTTP 200, SHA-256 digest, correct `q=HDD`;
  3. Both `searchRegion.id` and `currentFilters.regionId` equal the
     expected Cheonan `2292` (or Asan `2333`);
  4. No conflicting `in` parameter in either observed rendered URL or
     first-party Route request, and explicit region-picker action when omitted;
  5. Existing observed category, availability, price cap, per-item
     verification and response SHA correlation gates remain in force.
- `daangn_browser_v4_6.stage` allows the previously missing URL region
  **only** with the above independent verified authority. Its legacy
  URL-plus-visible-region path stays unchanged for older diagnostics.
- `RouteBodies.matched` still requires the exact same response digest from
  the independent passive observer. It no longer silently substitutes boot
  data for a missing filter-Apply response.
- Current UI-generated search JSON on the exact HTTPS first-party search path
  is considered even if its URL no longer carries the historical Remix `_data`
  route marker. The response still must contain a bounded, structurally valid
  search model and both locality IDs, meet current user-observed filters,
  and match the original passive response SHA byte-for-byte. No URL is
  constructed or manually fetched by this change.
- A public-safe failed-run summary includes bounded route response counters
  and fixed booleans for observed query/category/price/availability and
  server region matches. It cannot expose raw titles, links or seller data.

## Diagnosing current server metadata without changing the gate

The approved 2026-11-11 capture #9 received one UI-generated alternate
first-party search JSON response for the expected keyword and filters, but
the parsed model did not contain both expected Cheonan region IDs. The public
failure log at the time could only show two negative Boolean comparisons.

The diagnostics now distinguish `EXPECTED`, `MISSING`, and `OTHER` for
both `searchRegion.id` and `currentFilters.regionId`, separately. A
missing field cannot be treated as a known mismatched region, but **neither
permits promotion**. Only fixed enums are emitted; no numeric non-target
region IDs, raw JSON, seller data, listing URL or credentials leave the
private runner.

This classifier provides the next discriminating evidence:
- `MISSING/MISSING`: investigate a changed response schema or loss of
  locality metadata; do not infer geography from query or content.
- `OTHER/*` or `*/OTHER`: the selected region was not authoritatively
  applied, or a different region is being returned; stop.
- `EXPECTED/EXPECTED`: the remaining blocker is response correlation,
  transport, UI filter persistence or DOM evidence; inspect the matching
  stage rather than loosening locality proof.

The classifications are an offline-tested diagnostic change, not an
unverified inference that site-side region state was actually changed.

## Owner-approved capture #10: server locality differs from preset

The one-shot [capture #10](https://github.com/mozzibara/auto-daangn/actions/runs/42987173182)
confirmed `OTHER` for *both present* server locality IDs, not `MISSING`.
Its UI-generated search JSON matched the search keyword, category, availability
and price query while omitting the `in` parameter. This does not prove whether
the historical `2292` preset is stale or whether the UI selection failed.

A new strictly diagnostic `searchRegion.name` correspondence check now emits
`EXACT`, `CONTAINS`, `OTHER` or `MISSING` against the configured region
term, plus `YES`/`NO`/`MISSING` for agreement of the two returned server
IDs. A `historical_id_drift_candidate` flag means only that the region
name appears to match while both server IDs agree with *each other* but not
the legacy preset. It is **not** a valid proof of region identity or grounds
for automatically changing the preset. No raw region name or unknown numeric
region IDs appear in public diagnostics. Subsequent user-approved code review
must establish full administrative locality and source integrity before
migrating any region preset.

## Investigation after approved capture #12: picker-to-Apply transition

Owner-approved [capture #12](https://github.com/mozzibara/auto-daangn/actions/runs/42988365267)
showed a uniquely clicked visible locality option, but the subsequent
filter-Apply Route's `searchRegion.name` is `OTHER`; both server region IDs
agree with each other yet are `OTHER` relative to historic Cheonan 2292.
This does **not** establish ID drift. It suggests the region selection was
not reflected in the subsequent query.

The new investigation is diagnostic-only; it changes **no authority gate**:

1. Immediately before the *unique visible locality option's actual click*,
   arm the existing first-party read-only response listener. The listener is
   not armed for mere selector opening, typing or ambiguous/hidden results.
2. Inspect only option semantic predicates: whether its bounded visible label
   contains the configured city name, whether it exactly equals the locality
   term, whether a `data-region-id` (if present) matches the known ID, and
   whether that same option remains visible after click. The option's raw
   text, markup, href, data attributes and unknown IDs are **not** persisted.
3. Observe only real UI-emitted search `fetch`/`xhr` JSON responses after
   click. Classify zero, one or multiple candidate Route models and their
   already-established searchRegion/currentFilters ID, name and keyword
   predicates. Do not synthesize requests or trust boot-time loader state.
4. Compare the immediate post-click Route with the independently observed
   filter-Apply Route:
   - `REGION_NOT_VERIFIED_AFTER_CLICK`: selected click did not yield an
     authoritative matching server locality (or conflicts immediately).
   - `REGION_LOST_AT_FILTER_APPLY`: one fresh matching post-click server
     region existed but was replaced at filter Apply.
   - `POST_CLICK_ROUTE_NOT_OBSERVABLE`: no unique fresh post-click model;
     no conclusion about whether UI selection persisted.
   - `EXPECTED_REGION_PERSISTED`: diagnostics agree at both stages but the
     preexisting strict independent UI/Route SHA/price/category/stock checks
     are still required for any candidate promotion.
5. All transition output passes a fixed-value allowlist; no private runner
   log, raw server region ID, listing, seller or query token becomes public.

Do not run the same capture unchanged. After Linux and Windows offline CI
pass, request a new owner-approved, robots-first *single live capture*. CI and
this diagnostic itself cannot justify editing the historical region preset.

## Approved capture #14: wrong locality already after the picker click

Owner-approved [capture #14](https://github.com/mozzibara/auto-daangn/actions/runs/42992274891)
after PR #18 found a unique, visible region candidate with a Cheonan city
hint. The click completed, the candidate disappeared, and **one actual
first-party search JSON response immediately after the click** was parsed.
Its two region IDs agreed with each other but were both `OTHER` relative to
historic Cheonan 2292, and its region name was `OTHER` rather than 불당동.
The later Filter Apply response had the same categorical mismatch.
Therefore this failure predates Filter Apply; do not classify it as
`REGION_LOST_AT_FILTER_APPLY`. Detail visits and OCI writes were zero.

A third-party public notifier reports that invalid region codes can lead to
a default locality. This is a **hypothesis**, not verified current service
behavior. The next independent test observes the *real UI-emitted* bounded
region suggestion API JSON while the operator types the locality in the
already robots-approved picker. It classifies only candidates whose
administrative city and exact dong name match, comparing the candidate ID
in RAM with the historical preset and with both current server search IDs.
No unknown ID, response JSON or locality free text is ever exported. Zero,
multiple or malformed API responses remain inconclusive, and the result
does not bypass `verified_region` or justify automatic ID migration.

## Important limits

The original v4.15 post-reload strict filter persistence check is *not*
relaxed. If a full reload removes the region or filter selection, a candidate
must remain unverified; a one-time SPA success is not proof of persistence.
An unobservable UI locality label requires the stricter unique-option click plus fresh matching Route; an ambiguous option still blocks promotion. A successful
offline CI test is **not** evidence that the current website exposes the
needed field values in an actual GitHub-runner session.

Live capture remains one-shot, owner approved, robots-first, without login,
challenge bypass, bulk browsing or automated collection. Titles/URLs are
encrypted for the owner's OCI public key; no plaintext listing identifiers
are placed in public artifacts. OCI backup and intake timers remain disabled
until an explicitly tested cutover.

## Offline regression

```bash
python -m unittest discover -s tests -p 'test_v434_fresh_region_proof.py' -v
python -m unittest discover -s tests -p 'test_*.py' -q
```

Synthetic negative cases include mismatched server IDs, missing UI and absent unique action, stale
loader data, absent/altered SHA, different or ambiguous `in` values, wrong
host/query, and missing owner-selected region action.

## Three-source compatibility experiment (diagnostic only)

The independent code patterns studied in Nov 2026 are:

- [leemgs/used-notifier](https://github.com/leemgs/used-notifier/blob/main/scripts/daangn.js):
  old `/kr/buy-sell/` SSR HTML plus an explicit, separate listing-region
  cross-check; its historical default-location fallback must not authorize results.
- [NomaDamas/k-skill](https://github.com/NomaDamas/k-skill/blob/main/daangn-used-goods-search/scripts/daangn_used_goods.py):
  a resolved `in=<term>-<id>` on the old
  `/kr/buy-sell/all/?_data=routes/kr.buy-sell._index` JSON route.
- [hanmyeonglee/daangn-crawler](https://github.com/hanmyeonglee/daangn-crawler/blob/main/search.py):
  a browser navigation to `/kr/buy-sell/s/` with passive observation of
  first-party `/kr/api/v1/fleamarket/search` responses.

`app_v5.search_surface_probe` independently implements those **read-only
diagnostics**, without importing other repositories' code or requiring new
dependencies. It is invoked once, only when the first target Cheonan capture
fails with `REGION_MISMATCH` or `FRESH_REGION_PROOF_MISSING`, and
no access restriction was detected.

For each of three exact, fixed URLs, a fresh guest browser context performs
at most one request after a fail-closed, per-path robots.txt check. The old
SSR and modern search use browser navigation; the legacy `_data` JSON surface
uses the same ordinary public GET as k-skill, with `max_redirects=0` so an
unapproved redirected path is never followed. No scrolling, authentication,
cookie reuse, hidden API call, challenge bypass, detail page visit,
notification or retry is allowed. Observed
`fleamarket/search` responses are **passive**; they are never synthesized.
The first access restriction aborts all remaining surface probes.

Each result contains only fixed status/URL enums, bounded aggregate response
counts, and any explicit `searchRegion.id` and `currentFilters.regionId`
agreement with the pre-established region, with numeric IDs discarded.
An SSR `ItemList` signal, a successful old `_data` response, and a matching
request `in` are **not** evidence that a locality was applied: none can
authorize candidate collection or listing recommendations.

The probe adds a maximum of three **search-document** navigations to the
existing one-shot, owner-approved job after the current strict capture fails,
and does not change the maximum 9 source + 6 control **detail** visits. The
existing signed/encrypted artifact and OCI transfer paths are unchanged. A
public failed-run log exposes only allowlisted `SURFACE_*` classifications;
a full capture is still required to satisfy the original fresh UI+Route
locality, category, maximum price, availability and SHA gates.

Follow-up investigation is determined by the observed result: if all three
surfaces redirect to missing locality, investigate local UI commit/session
semantics; if one retains the intended region and carries matching server
metadata, investigate a **separately authorized** integration of that route
without replacing the strict filter proof. A missing server region field or
mere listing geography is never enough.

Owner-approved capture [#17](https://github.com/mozzibara/auto-daangn/actions/runs/43000868603)
showed: SSR `HTTP_OK` + `SSR_ITEMLIST` but a redirected URL without `in`;
the legacy `_data` direct-document navigation failed with `REQUEST_ERROR`
(the browser cannot reliably render JSON documents); and the `modern_s`
path was denied by robots.txt. Only the `_data` transport is corrected in
the follow-up; previously denied paths must remain unvisited. This finding
does not authorize using the old SSR result for listing admission.

## Approved capture #18: nonredirecting legacy JSON GET confirms redirect

The follow-up [capture #18](https://github.com/mozzibara/auto-daangn/actions/runs/43001567600)
ran after PR #21 corrected the legacy data probe to match the original
k-skill **HTTP GET**, not a browser document navigation. The public
`/kr/buy-sell/all/?...&_data=...` response was **HTTP_REDIRECT**,
not JSON. The redirect Location still contained the expected configured
region slug and keyword, but pointed to a **different path**. The probe
deliberately set `max_redirects=0` and did not follow it, so it cannot
make claims about that target's eventual server locality.

Independently, the old SSR browser page still returned HTTP 200 with
`ItemList` HTML after the final URL lost `in` and changed path. The
new `/kr/buy-sell/s/` surface remained **robots-denied**; zero requests
were issued to that path. The actual public UI picker continued to
receive an exact candidate for the historical ID but produced
a post-click search response with `OTHER` IDs and region name.

Outcome:
- The three known third-party patterns are integrated as bounded
  compatibility diagnostics; **none** is a verified replacement for
  the current canonical search collector.
- The older route cannot be trusted just because it returns an
  `ItemList` or preserves `in` on an intermediate redirect.
- The first failure remains `FRESH_REGION_PROOF_MISSING`;
  no listing details were visited and OCI intake remained unchanged.
- Do not repeat the same tests without a new discriminating change.
  Next assess the actual region-picker **commit state**, URL/navigation
  sequence, and visible selected control, preferably comparing a
  domestic owner-controlled browser with the GitHub runner. Any new
  test remains read-only, robots-first, categorical-only and owner-approved.

See [issue #11](https://github.com/mozzibara/auto-daangn/issues/11)
for the two live-run outcome summaries.

## Region option click -> visible UI -> navigation commitment trace

After the two legacy surface probes [#17](https://github.com/mozzibara/auto-daangn/actions/runs/43000868603)
and [#18](https://github.com/mozzibara/auto-daangn/actions/runs/43001567600)
confirmed redirects/default region, the next discriminating evidence is
the browser's **actual region-picker commitment**, not another request to
the legacy URLs.

`app_v5.region_navigation.RegionNavigationTrace` observes **only** the
already robots-approved picker action, from immediately before the unique
visible option is clicked through settlement. It reads the following
categorical checkpoints:

1. `BEFORE_CLICK`: target region-option dialog state, scoped region-control
   visibility, typed target-term state, actual browser URL category.
2. `AFTER_CLICK`: the same state **immediately after the actual option click**,
   before the existing 300 ms UI wait.
3. `AFTER_SETTLE`: the same state after the existing public capture settle
   delay, before Filter Apply.

During the same window, Playwright passively observes **only** the existing
first-party `/kr/search/buy-sell/` XHR/fetch requests, document requests and
main-frame navigation events. All URLs are transformed immediately to
fixed `EXPECTED/OTHER/MISSING/INVALID` host/path/query/region indicators;
at most 12 event categories are kept, with a separate overflow flag.
No raw URL, cookies, history.state, localStorage, React state, headers,
HTML or listing content is read/exported; no additional network request is
sent. Listeners are detached in a `finally` block.

A diagnostic comparison classifies e.g.:
- `NO_VISIBLE_COMMIT_SERVER_OTHER`: post-settle UI has no visible
  selected-region control, while the fresh post-click server Region ID
  was OTHER; neither click success nor a suggestion response promoted it.
- `UI_OTHER_AND_SERVER_OTHER`: a visible region control still points
  elsewhere and the server did too.
- `UI_TARGET_SERVER_OTHER`: UI displays requested term, but the
  independent server Route still reports another region; look for a
  state propagation/redirect problem rather than blindly retrying clicks.
- `VISIBLE_TARGET_REVERTED_TO_OTHER` / `VISIBLE_TARGET_LOST`:
  immediately after the click the target was visible, but disappeared
  after settling; investigate SPA navigation or state reset.

These are **hypotheses**, not a direct assertion of root cause.
The pre-existing `verified_region()` and the strict Route digest,
category/price/availability and status gates remain untouched. Every
snapshot and event is re-allowlisted at the v4.23 public report boundary
and the v4.34 failure log boundary, including a fixed-enum event sequence.
If no unique visible option exists, the click is not attempted and the
trace cannot be used as locality proof.

The only permitted live test is the existing one-shot owner-approved
robots-first GitHub workflow. Do not repeat unchanged runs or attempt the
robots-denied `/kr/buy-sell/s/` route. No direct OCI access, login,
session cookies or detail-page visits are required.

## Approved capture #20: visible UI never committed target

The first click-specific live trace, [capture #20](https://github.com/mozzibara/auto-daangn/actions/runs/43012229055),
confirmed all of the following:
- `BEFORE_CLICK`: picker overlay OPEN, region input EXACT TARGET,
  main region button displayed OTHER, URL `in` MISSING.
- `AFTER_CLICK`: main region button still OTHER, overlay OPEN,
  input no longer EXACT, URL `in` MISSING.
- `AFTER_SETTLE`: main region button still OTHER, overlay OPEN,
  input MISSING, URL `in` MISSING.
- Exactly one first-party search fetch request, with URL region MISSING
  and expected keyword/path; **no navigation or document request**
  observed in that bounded click interval.
- The real post-click search Route had both locality IDs OTHER and
  server region name OTHER. The resolver independently returned the
  unique correct historical Cheonan target ID.
- Classification: `UI_OTHER_AND_SERVER_OTHER`. The original
  `FRESH_REGION_PROOF_MISSING` stopped the capture. Source detail visits
  zero and no item, secret, or OCI data was exported.

This proves the click does **not** commit the target locality to the
selected visible region control or its immediate search request. It
does **not yet** distinguish a multi-step UI needing confirmation,
a click on a noncommitting suggestion, or a frontend state propagation
error.

The next safe refinement separates real `[role=dialog]` from
`[role=listbox]` visibility (previously aggregated as a single OPEN
state), and observes only categorical option role/tag/ancestor/
`aria-selected` and exact-label confirmation affordances inside the
dialog. No additional click is automated and no arbitrary page text,
HTML, or values are exported. A new owner-approved run after offline
CI can discriminate a still-open confirmation dialog from a lingering
listbox or an uncommitted autocomplete suggestion.

## Approved capture #21: clicked choice is dialog button, not committed option

After PR #24 separated the dialog and listbox, [owner-approved capture #21](https://github.com/mozzibara/auto-daangn/actions/runs/43013233966)
gave stronger, independent categorical evidence:

| Evidence | Before exact click | Immediate after click | After settle |
|---|---|---|---|
| Main region-selection control | OTHER_VISIBLE | OTHER_VISIBLE | OTHER_VISIBLE |
| Real `[role=dialog]` | OPEN | OPEN | OPEN |
| `[role=listbox]` | CLOSED | CLOSED | CLOSED |
| Exact-label confirmation control | NOT_VISIBLE | NOT_VISIBLE | NOT_VISIBLE |
| Dialog's observed region input | EXPECTED | OTHER | MISSING |
| Actual search URL region `in` | MISSING | MISSING | MISSING |

The exact element clicked was a generic **BUTTON** inside a
**DIALOG**; it had no explicit `role`, `aria-selected` or
`data-region-id`. Its label still contained the desired administrative
city hint. Immediately afterward the matching candidate was no longer
visible, but the main region control never displayed the requested
district. Exactly one new first-party search fetch was observed with
correct keyword/path and no `in`, and its fresh server
`searchRegion.id`, `currentFilters.regionId` and region name were all
OTHER relative to the expected district. There was no main-frame
navigation event during the bounded click window. The independent
region keyword resolver continued to return the unique expected
administrative-locality ID.

**Strong conclusion:** a successful Playwright click on the currently
chosen suggestion is **not** a region commit. The observable failure
occurs between picking that dialog button and applying locality to
the top-level UI/search request, *before* the later Filter Apply.
Because no exact-label confirmation button was observed, one cannot
presume that an additional confirmation step exists; hidden or
differently labeled UI actions and SPA state mechanics remain
unclassified. The exact underlying reason (noncommitting suggestion
action vs unauthenticated session limitation vs app state bug)
is **not yet proven**.

The strict authority gate correctly stopped with
`FRESH_REGION_PROOF_MISSING`; source detail visits, listing admission
and OCI imports remained zero. Further repeated unchanged live
captures are unhelpful. Investigation should compare this exact
interaction to an owner-visible browser and only add a *new*
robots-approved, privacy-safe observation or UI action justified by
specific evidence. Never adopt an unrelated locality, derive
authority from SSR ItemList, or weaken the filter/SHA/region gates.

## Exact candidate button event/ARIA witness (next discriminating experiment)

Approved live [#21](https://github.com/mozzibara/auto-daangn/actions/runs/43013233966)
proved that the clicked locality candidate was a generic `BUTTON` nested
in an open dialog, with no `role=option`, `aria-selected`, or data-region-id.
The target region never reached the visible region button nor the fresh
search response. **This does not, by itself, reveal whether the button
was an intermediate step or a failed final action.**

`app_v5.region_option_events.RegionOptionEventWitness` now instruments
**only that same unique, visible, robots-approved option**, immediately
before its single existing Playwright click. It adds and removes
passive, short-lived DOM listeners (`pointerdown`, `pointerup`,
`click` on the button; a filtered document bubbling witness), plus a
bounded MutationObserver of the existing dialog. The observer never
calls `click`, `dispatchEvent`, `preventDefault`, or `stopPropagation`.
It makes no new requests. All resources are detached in a `finally`
block, even after a failed click.

The initial ARIA witness classifies, without exporting raw attribute
values: `role`, `aria-haspopup`, `aria-expanded`,
`aria-disabled`, `aria-controls` presence, `aria-describedby`
presence, HTML button `type`, `data-state`, `tabIndex`,
form membership, disabled state and whether an accessible label
matches the configured target/city. The subsequent two checkpoints
(`AFTER_CLICK`, `AFTER_SETTLE`) contain only event-kind sequence,
`event.isTrusted`, `defaultPrevented`, event propagation to
document, target connection/visibility, focus relationship, button
expansion state and capped dialog DOM mutation counts (added
dialogs/buttons/inputs). There are no event timestamps, selectors,
seller/item strings, raw HTML, element attributes, URLs, numeric unknown
region IDs, cookies, storage or React internal state in the public log.

Interpretation must remain conservative:

- `CLICK_EVENT_NOT_SEEN`: a successful Playwright call does **not**
  establish that instrumentation saw an actual target click.
- `CLICK_DELIVERED_NO_COMMIT`: target click was observed, but the
  independent selected region control and fresh server Route were still
  `OTHER`. This indicates **non-commitment**, not a definite front-end
  defect or definite intermediate-step semantics.
- `SECOND_STAGE_SIGNAL`: a new dialog appeared, or the clicked option's
  accessible `aria-expanded` transitioned to true. It indicates
  a **potential** additional step, never permission to click unknown UI.
- `COMMIT_CORROBORATED_DIAGNOSTIC`: both visible region control and
  current server locality matched, but the original independent
  `verified_region`, SHA, filters, stock and candidate gates still
  apply.

The capture remains an owner-approved, robots-first, one-shot diagnostic.
No new live traffic beyond the existing workflow, login, cookie handling,
challenge bypass or detail visits is permitted. A live event witness must
be checked after cross-platform offline tests; site-side event outcomes
are not established by synthetic mocks.

## Approved live capture #23: actual trusted click; original dialog replaced

One owner-approved robots-first run [#23](https://github.com/mozzibara/auto-daangn/actions/runs/43021744779)
captured an actual trusted pointerdown/pointerup/target click, followed by
document-level bubbling. `defaultPrevented=NO`, button HTML
`type=button`, no `aria-haspopup`, `aria-expanded`,
`aria-controls`, or `aria-label`, and the button was focusable.
The clicked button disconnected from the DOM immediately. The **original
dialog** remained visible immediately after clicking, then itself
disconnected by settle time. At settle time, however, the independent
whole-document UI observer still saw a *visible dialog* and a non-target
top-level region control. Exactly one public search FETCH still omitted
`in` and its fresh server locality fields remained OTHER.

This establishes that **Playwright click-dispatch failure is ruled out**;
the page performed a DOM transition after that button's actual click.
It does not prove that the surviving dialog is a distinct selection
stage, since a SPA could replace the original dialog node while
re-rendering the same stage. A capped 20+ count of newly inserted
buttons similarly cannot establish an additional selection step.

The next distinct one-shot experiment compares categorical dialog
*structure* at BEFORE_CLICK, AFTER_CLICK and AFTER_SETTLE: visible
search inputs, target-matching buttons, selectables, selected-state
controls, back-navigation affordance, button totals, focus, `aria-modal`,
accessibility heading category and whether the original dialog was
replaced. Raw headings, button labels, DOM, unknown identifiers and
addresses are never exported. A replacement plus altered controls is
reported as `NEW_DIALOG_WITH_CHANGED_CONTROLS`, **not** automatically
a final/confirmed target or a safe follow-up click.

This instrument performs no new UI actions or network requests and
retains existing region, SHA, filter, stock, privacy and robots gates.

## Live #25: initial dialog fingerprint scope ambiguous — fixed in subsequent PR

Owner-approved [live #25](https://github.com/mozzibara/auto-daangn/actions/runs/43026448906)
ran on `main` commit `26c53c7986cecedde18586a2f40b0e3737433eec`.
The original dialog node disappeared after an actual trusted click, while a
visible dialog remained; `REPLACED_DIALOG_UNCLASSIFIED` was the correct
fail-closed diagnostic classification. The independent server region ID,
selected region control and request query still did not match the target,
and there were zero detail visits.

**Observation error in the new stage probe:** the first visible
`[role=dialog]` had zero visible buttons/inputs at all three checkpoints,
while the actual clicked candidate was a `BUTTON` inside a dialog.
The probe selected the **first** visible dialog in document order, without
establishing that it contained the clicked candidate. These zero counts
cannot be interpreted as an empty choice step.

The corrected read-only probe enumerates a bounded set of dialogs,
including wrappers whose own CSS box is absent but whose children are
visible. It deduplicates controls in nested dialogs and first selects
the *nearest dialog ancestor* of the unique visible target candidate;
otherwise the nearest dialog of the unique visible region search input;
otherwise a uniquely most-interactive dialog as a marked fallback.
It reports the fixed-enum `dialog_scope` so results can be interpreted
according to provenance. If multiple candidates remain, `AMBIGUOUS`
prevents the probe from inventing structural certainty. It never adds
a click or promotes locality.

**The live #25 logs remain valid for clicking, DOM replacement and
lack of region commit, but its dialog-internal zero counts are not
valid evidence that a separate stage lacks any controls.**
