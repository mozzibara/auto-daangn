# OCI one-dispatched-click diagnostic continuation (2026-11-12)

## New direct evidence from owner-run PR #55 experiment

On Ubuntu 24.04 x86_64, OCI Chrome Stable with Xvfb, **both** owner-approved
public search comparisons (`FILL` and `SEQUENTIAL_KEYS`) showed:

- `status=REGION_HEADER_ACTION_EXCEPTION`
- `core_progress_stage=BEFORE_REGION_BUTTON_CLICK`
- `core_header_click_returned=false`, `step_error=STEP_EXCEPTION`
- `header_activation.armed=true`, exactly **one trusted**
  `POINTERDOWN`, `POINTERUP`, `MOUSEDOWN`, `MOUSEUP`, and `CLICK`
- exactly one region-header candidate, visible and enabled
- exactly one region dialog input still visible 4.2 seconds later,
  focused (`REGION_INPUT`)
- **no keyword request**, typing, region option selection, or postclick
  search Route; header region family `OTHER → OTHER` unchanged

This establishes **one real region-header click was dispatched**, but
Playwright's `locator.click(timeout=5000)` **did not return**. The modal
opened, so the previous hypothesis “the site did not receive a click”
is falsified for these two attempts. An automatic post-click wait,
navigation/route behavior, or other Playwright action timeout is
plausible, but the precise error subtype remains unobserved in the
previous categorical schema. The country of egress was **not**
measured in this command (`egress.state=DISABLED`).

Playwright's official `locator.click` API documents that a click
requires actionability checks, a mouse event and potentially waiting
for initiated navigations to finish. Its `no_wait_after` behavior is
subject to deprecation/change, so this revision **does not rely on**
disabling Playwright checks.

Reference: https://playwright.dev/python/docs/api/class-locator#locator-click

## Changes in this PR

The original core remains unchanged for all callers except those
providing a **new explicit diagnostic-only callback**:
`on_header_click_timeout`. Only a genuine
`playwright.async_api.TimeoutError` at the **initial region-header**
click can invoke the callback. Other failures and the default/no
callback behavior still abort.

The diagnostic callback is **read-only**. It requires every condition:
1. The current page still matches the approved public-search URL.
2. The existing observer was armed and registered exactly **one trusted
   pointer/mouse/click event each**, and exactly one total each.
3. Exactly one region-header button remains visible and enabled.
4. Exactly **one visible** region-input candidate exists, it is
   enabled/empty and within a visible region picker dialog.

If any observation fails, return `False`, re-raise the original
timeout to the existing fail-closed handler, **never click a second time**.
No website-specific bypass, session/state injection or network request
is added. After passing all predicates, the original UI routine
continues at its existing 500ms wait, input value entry, first-party
API+stable-DOM gate, one exact native region-option click, and
independent fresh Route/UI/server-region verification.

The result separately reports:
- `core_header_click_returned=false`, even when the diagnostic
  reconciled one delivered click
- `header_click_verified_after_timeout=true` only for the strict
  one-event/one-dialog proof
- `header_click_exception_kind` one of `NONE`,
  `PLAYWRIGHT_TIMEOUT`, `OTHER_EXCEPTION`
- `core_progress_stage`, e.g. `AFTER_REGION_BUTTON_CLICK_VERIFIED`
  after the recovered stage, or `AFTER_INPUT_ENTRY` later.

**A successful timeout reconciliation is not successful region
selection and never authorizes listings.** The only locality admission
path continues to require exact first-party API candidate ID, one
fresh post-click Route with expected search and filter region, and
matching visible region control. The `REGION_MISMATCH` fail-closed
barrier stays in place.

## Regression requirements

- Default core caller still fails on Playwright timeout.
- Synthetic actual Playwright TimeoutError followed by proof callback
  calls the original region-header click **exactly once**.
- Generic exceptions, missing/untrusted/duplicate clicks, hidden or
  disabled buttons, ambiguous or non-empty dialog inputs, observer
  failure or callback error all fail closed, with **no repeat click**.
- Fixed enum/boolean privacy sanitization and idempotent result
  formatting, no raw exception messages or input values.
- Zero public marketplace requests in CI; separate local real-Chrome
  HTML fixtures remain mandatory.

## Owner-only OCI command after CI and main merge

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate

# Offline real Chrome Stable/local HTML first:
xvfb-run -a python -m scripts.chrome_stable_input_compare --headed

# Only if normal robots/access approval still holds; one bounded
# owner-approved A/B comparison, no persistent profile:
set -o pipefail
xvfb-run -a python -m scripts.chrome_stable_input_compare \
  --live --headed \
  --owner-approval I_APPROVE_CHROME_INPUT_COMPARISON_V1 \
  | tee "$HOME/daangn_oci_click_continuation.json"
```

Inspect `public_site[*].picker_phase_diagnostics` and the strict
`status`, `api_response_count`, `native_click`,
`server_search`, `server_filter`, `route_status` and
`selected_ui`. Stop on restrictions; no automated retry.
