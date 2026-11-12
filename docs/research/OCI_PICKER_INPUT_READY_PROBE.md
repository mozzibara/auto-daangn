# OCI pretyping failure analysis and passive phase probe (2026-11-12)

## User-run observed record

Owner ran **one** already-approved `xvfb-run -a python -m scripts.chrome_stable_input_compare --live --headed`
on `x86_64` OCI second-instance, Ubuntu 24.04, Chrome Stable,
Python 3.12, in a separate non-root diagnostic checkout.

Offline `FILL` and `SEQUENTIAL_KEYS` Chrome fixtures both completed;
the delegated manual fixture also passed.

The live `public_site` array showed:

| Signal | FILL | SEQUENTIAL_KEYS |
| --- | --- | --- |
| result | API_OR_DOM_NOT_READY | API_OR_DOM_NOT_READY |
| target API responses | 0 | 0 |
| API ready | false | false |
| region input event witness armed | false | false |
| target input value verified | false | false |
| native region option click | NO | NO |
| fresh postclick search Route | NONE_FRESH | NONE_FRESH |
| 4200ms focus | REGION_INPUT | REGION_INPUT |
| initial→final header | OTHER→OTHER, UNCHANGED | OTHER→OTHER, UNCHANGED |

This **does not** establish `REGION_NOT_COMMITTED`, because no first-party
region option click occurred. It is an **earlier pretyping/preselection**
failure. Zero matching API responses alone cannot prove the website
blocked the request: the existing code calls `on_before_search` only
**after** it sees a picker input 500ms after opening the region picker.
An input becoming focused later is consistent with a slow picker render,
but does **not** yet prove the input was missing at the 500ms check.
We must also distinguish a browser-side failed network request from a
request never initiated.

Previous initial baseline on the same OCI instance:
`HTTP_200`, coarse egress `KR/ORACLE_CLOUD`, initial header family
`OTHER`, browser timezone `OTHER`, no initial Route and no clicks.
The subsequent Chrome A/B input test **did not enable** `--egress-context`
and legitimately returned egress `DISABLED/UNAVAILABLE`. Do not treat
that as a network outage or change of country.

## Read-only instrumentation now added

The existing controlled region-selector helper has an optional
`on_after_open` **passive callback** at the same original 500ms
input-discovery boundary. It does not change clicks, delays or input mode.

In the existing Chrome input comparison, additional **finite fields**:
- `picker_phase_diagnostics.step_error`: known core return class
  (`REGION_INPUT_NOT_FOUND`, `REGION_SUGGESTION_NOT_READY`,
  `STEP_EXCEPTION`, etc.), never an exception message
- `picker_phase_diagnostics.readiness_state`: existing readiness gate
  `NOT_RUN`, `API_TIMEOUT`, `DOM_NOT_FOUND`, etc.
- `picker_phase_diagnostics.phases.AFTER_PICKER_OPEN_500MS`,
  `AFTER_CORE_RETURN`, `AFTER_SETTLE_4200MS`: fixed counts of
  visible/hidden region-input candidates, dialog inputs, and focus class
- `delayed_input_observed`: true if no visible candidate at 500ms but
  one became visible by 4200ms; purely observational, no automatic retry
- `api.state`: only **browser-emitted** first-party region-keyword
  request / response / requestfailed categories, including
  `NO_TARGET_REQUEST`, `REQUEST_WITHOUT_RESPONSE`, `RESPONSE_200`,
  `REQUEST_FAILED`, `ACCESS_RESTRICTED`, `RESPONSE_OTHER`

Never stores raw request URLs, user input, seller/article data, cookies,
headers, response bodies, failing exception text or IP addresses. It
does **not** add any public HTTP request, new navigation, hidden click,
extra typing, login or automatic retry.

### Decision table

| Next diagnostic evidence | Interpretation |
| --- | --- |
| `step_error=REGION_INPUT_NOT_FOUND` + `delayed_input_observed=true` | Picker was unavailable at old 500ms check but visible later; consider a *bounded, visible-control* wait in a separate reviewed PR |
| `step_error=REGION_INPUT_NOT_FOUND` + no later input | Picker failure or changed DOM; do not infer API/network cause |
| `step_error=REGION_SUGGESTION_NOT_READY` + `api.state=NO_TARGET_REQUEST` | Typing occurred but browser did not issue the exact expected keyword request; inspect visible input/focus and query categorization |
| `api.state=REQUEST_FAILED` | Exact first-party request failed at browser network layer; inspect non-sensitive network configuration only |
| `api.state=RESPONSE_OTHER` | Response status differed from 200 and access-denial codes |
| `api.state=ACCESS_RESTRICTED` | Stop further live testing |
| `api.state=RESPONSE_200` + `readiness_state=DOM_NOT_FOUND` | API responded but the expected visible candidate DOM is not ready |

This is a diagnostic instrument, **not permission to bypass a service
restriction**. The existing `REGION_MISMATCH` gate remains fail closed.

## Run only after four-job offline CI and main merge

From OCI's existing **non-root, isolated** checkout/venv:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate

# Existing offline local HTML first; no Daangn calls.
xvfb-run -a python -m scripts.chrome_stable_input_compare --headed

# Owner-controlled bounded public comparison: two input modes maximum.
# Invoke ONLY if site robots/access requirements permit.
set -o pipefail
xvfb-run -a python -m scripts.chrome_stable_input_compare \
  --live --headed \
  --owner-approval I_APPROVE_CHROME_INPUT_COMPARISON_V1 \
  | tee "$HOME/daangn_oci_region_picker_phases.json"
```

Do not run the same diagnostic repeatedly if a restriction/challenge
is observed. The JSON contains only safe fixed-shape bounded fields.
The script's success exit code signifies diagnostic completion, not a
successful chosen region. Compare `public_site` results and phase states.
A subsequent bounded wait for a genuinely visible picker input should be
based on the phase witness, not presumed from the previous run.

Sources: owner-provided OCI A/B log and existing
`app_v5/region_readiness.py`, `daangn_v4_1_core.py`, and
`scripts/chrome_stable_input_compare.py` runtime sequence.
