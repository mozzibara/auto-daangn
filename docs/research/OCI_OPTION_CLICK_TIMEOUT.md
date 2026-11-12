# OCI region-choice click timeout diagnostic — 2026-11-12

## Owner-run verified discovery on main 05419d6

The operator ran Chrome Stable on isolated OCI Ubuntu x86_64 with
`scripts.chrome_stable_input_compare --live --headed` under exact approval
and robots-first checks. The real public-site evidence (NOT the offline
fixture) differs by input mode:

| Signal | FILL | SEQUENTIAL_KEYS |
|---|---|---|
| initial header action Playwright timeout | yes | yes |
| independently proven *single* trusted header click | yes | yes |
| keyword API 200; uniquely matched target candidate | 1, yes | 1, yes |
| input ready | READY | READY |
| target option click command returned | yes | **no** |
| core progress | AFTER_SUGGESTION_CLICK | **BEFORE_SUGGESTION_CLICK** |
| core error | NONE | STEP_EXCEPTION |
| visible selected region | EXPECTED | EXPECTED |
| fresh post-option Route | **ONE_FRESH** | NONE_FRESH |
| server search/filter region | **EXPECTED/EXPECTED** | UNOBSERVABLE/UNOBSERVABLE |
| classified status | **TARGET_REGION_CONFIRMED_DIAGNOSTIC** | CLICK_NOT_TRUSTED |

This **establishes success for the FILL diagnostic** on this particular
OCI run, without authorizing product/listing collection. It does NOT
establish region confirmation for sequential keyboard input. The latter
produced the target visible header but had **no observed, unique,
postclick route response** and no `on_after_select` trusted-click
checkpoint because its `locator.click` action did not return. We
must not infer a working server filter from UI alone.

For SEQUENTIAL_KEYS the passive exact region API observer recorded **one
unrelated keyword request** and one expected target keyword response.
This is consistent with intermediate text entry, not evidence of
an injected or blocked request. Neither the browser's outgoing IP nor
its user identity was part of this experiment.

## New diagnostic-only reconciliation for the *option* click

The shared `ui_select_region` retains its default: a Playwright
TimeoutError on the region option click aborts and stays fail-closed.
Only the explicit `on_option_click_timeout` callback (used by this
research script) can reconcile that timeout **without another click**.

This callback must independently show:
- Original approved public-search URL remains the active page;
- The trusted option observer was previously armed on the **unique
  visible, exact-city candidate**;
- A single strictly ordered `POINTER_DOWN`, `POINTER_UP`,
  `CLICK_TARGET`, `CLICK_DOCUMENT` sequence was observed on that
  actual option, with `click_trusted=YES`, document bubble YES,
  target BUTTON or DESCENDANT, and one in-memory browser event epoch;
- No duplicate event or replay was seen.

Any absent witness, lost page, generic exception, unknown region-option
identity, duplicate/untrusted event or missing click epoch causes the
original exception to abort. No forced click, synthetic event,
re-navigation, extra API request, browser fingerprint change, proxy or
retry is performed.

If and only if the single existing click is independently proven,
the existing observation callback records the click epoch and the
original **fresh postclick Route + expected server search/filter
region + visible UI** gates still decide `TARGET_REGION_CONFIRMED_DIAGNOSTIC`.
If the Route was absent, status must remain `INCONCLUSIVE` rather
than be promoted to confirmed. If the exception was not reconciled,
`REGION_OPTION_ACTION_EXCEPTION` describes the exact stage.
`authorizes_listings=false` in all outputs.

The new fixed fields are:
`picker_phase_diagnostics.option_click_returned`,
`option_click_verified_after_timeout` and
`option_click_exception_kind`, plus
`core_progress_stage=AFTER_SUGGESTION_CLICK_VERIFIED` for reconciled
timeouts. Diagnostic results may classify a click as verified but
cannot themselves authorize persistence/production runtime.

Playwright's locator.click documentation explains the actionability,
mouse click, initiated navigation wait and potential timeout:
https://playwright.dev/python/docs/api/class-locator#locator-click
We do **not** disable actionability or automatic wait.

## Operator commands after CI and main merge

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate

# Offline fixture first, no public traffic:
xvfb-run -a python -m scripts.chrome_stable_input_compare --headed

# Optional approved one-shot live comparison, under robots and site
# access rules, never after a denied request or challenge:
set -o pipefail
xvfb-run -a python -m scripts.chrome_stable_input_compare --live --headed --owner-approval I_APPROVE_CHROME_INPUT_COMPARISON_V1 | tee "$HOME/daangn_oci_option_click_result.json"
```

Inspect both `public_site` rows and the route/server fields.
The test is bounded to two owner-approved region-selection attempts.
Do not reuse private browser profiles or read/upload raw listing links,
cookies, location histories or account material.
