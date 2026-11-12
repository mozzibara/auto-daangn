# Windows owner Chrome and hosted Linux Chrome: locality contrast

## Evidence available on 2026-11-12

A disposable, ordinary Google Chrome launched on the owner's Windows PC
selected the expected Cheonan locality with one manual trusted option click.
Its fresh post-click search Route provided matching expected `searchRegion.id`
and `currentFilters.regionId`, and the visible selection became EXPECTED
between the +800ms and +2000ms checkpoints. The URL omitted the `in`
query parameter even when server and UI were correct.

PR #44's owner-approved GitHub Ubuntu 24.04 (headed Xvfb) live comparison
produced one trusted target click and one fresh Route in each mode, but both
FILL and SEQUENTIAL_KEYS finished with OTHER server + filter + UI regions.

The owner then ran PR #45's same comparison on the **same local Windows PC**.
Both FILL and SEQUENTIAL_KEYS returned
`TARGET_REGION_CONFIRMED_DIAGNOSTIC`, with matching expected server
search, server filters and final visible region, one fresh Route and a
trusted click. Neither mode produced keydown/keyup or Korean
composition events. Thus these event types are **not a necessary
condition** of region commitment in that Windows session.

These results **do not** isolate OS as causal: the local PC differs from
GitHub-hosted Ubuntu in network egress, IP/geolocation, image policies,
browser-version details, graphics/session runtime, and potentially timing.
Do not infer anti-automation blocking or any specific root cause from
these contrasts alone.

## Next discriminating environment comparison

A new, separately owner-approved workflow
`.github/workflows/chrome-stable-windows-hosted-compare.yml` uses
`windows-2025` (GitHub-hosted Windows Server 2025). It runs the exact
existing privacy-limited offline headed Google Chrome fixture first,
and only if it passes performs a **single bounded two-mode** public
region comparison with the script's existing robots-first checks.
It cannot be initiated by issue comments or routine CI, and the
workflow has no repository write permissions, secrets, artifacts,
browser download, profile reuse, or OCI operations.

The regular Python offline CI also runs the exact local HTML fixture
on the Windows-hosted image. A new hosted GUI or Chrome launch failure
is an **environment/fixture issue**, not a locality failure; the live
step must not run after such a failure.

Manual dispatch requirements:
- Open GitHub Actions > "Owner-approved Windows-hosted Chrome Stable region comparison".
- Select **Run workflow** on main.
- Enter exactly `I_APPROVE_WINDOWS_HOSTED_REGION_COMPARE_V1` as the approval input.
- Read only sanitized Actions logs; no raw HTTP or seller/listing data.

Interpretation:

| Hosted Windows result | Meaning |
| --- | --- |
| Both modes TARGET_REGION_CONFIRMED_DIAGNOSTIC | Windows-hosted Chrome is compatible, increasing attention to Linux runner/runtime effects. Network/session confounders remain. |
| Both modes REGION_NOT_COMMITTED | Both hosted runner environments differ from owner Windows, increasing attention to hosted network, default locality and session state. Still not causal proof. |
| One succeeds | Compare identical local event classes and independent fresh Route/UI outcomes, then investigate timing/state transitions. |
| Fixture fails / baseline invalid / site restricts | Insufficient evidence. Do not retry or bypass access controls. |

Safety: `authorizes_listings=false` throughout. Issue #11 remains open;
no live listing collector, OCI import, or disabled backup timer is
activated as part of this experiment.

See [CHROME_STABLE_INPUT_COMPARISON.md](CHROME_STABLE_INPUT_COMPARISON.md)
and [FRESH_REGION_AUTHORITY.md](FRESH_REGION_AUTHORITY.md).
