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
