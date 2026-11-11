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
