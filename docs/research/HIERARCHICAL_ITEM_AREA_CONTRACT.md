# S1 hierarchical item-area contract (offline)

The default v1 configuration is unchanged. This PR adds a v2 contract for
explicit municipality/borough/neighborhood and pinned first-party region ID.
V2 is opt-in via an explicitly supplied policy file, not a new live setting.

V2 entries have exactly key, city, borough, district, region_id.
Supported municipality labels are currently 천안시, 아산시 and 서울특별시.
서울특별시 requires a borough; other supported municipalities may use null
only for a directly verified path without a borough. Every ID must be pinned.
Use only directly verified service labels/IDs, never fabricated or inferred
IDs. Tests use fictional IDs and names.

V2 accepts an item's own region only when complete explicit fields and ID
agree with a single row. Missing, mixed-version, conflicting and partial
evidence is held. Search-region evidence, same-listing identity, price,
category and sale-state gates remain mandatory and unchanged.

This is a schema/admission primitive, not a neighborhood adjacency detector.
No new area is active. No user-specific settings are committed. Before
runtime rollout, verify the actual first-party field shapes, derive explicit
coverage per anchor, and bind the same private versioned policy to capture,
manifest generation and sealed import. Existing v1 callers still use their
original defaults. Do not switch production policy until those paths and
provenance have end-to-end tests.
