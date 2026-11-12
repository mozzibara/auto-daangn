# OCI region-header action exception — 2026-11-12

## Evidence from user's second OCI run (PR #54 instrumentation)

Owner's `~/code/auto-daangn-region-diagnostic` fast-forwarded from
`0de628b` to `f82eaaa` and completed the **offline** region-input
Chrome fixture successfully. A single owner-approved bounded live
comparison was then performed with FILL and SEQUENTIAL_KEYS.

| Signal | FILL | SEQUENTIAL_KEYS |
|---|---|---|
| result | API_OR_DOM_NOT_READY | API_OR_DOM_NOT_READY |
| picker_phase_diagnostics.step_error | STEP_EXCEPTION | STEP_EXCEPTION |
| picker_phase_diagnostics.picker_opened | false | false |
| phase AFTER_PICKER_OPEN_500MS | UNOBSERVABLE -1 | UNOBSERVABLE -1 |
| phase AFTER_CORE_RETURN inputs | 0 | 1 |
| phase AFTER_SETTLE_4200MS visible_inputs | 0 | 1 |
| focus after settle | BODY | REGION_INPUT |
| browser-observed target keyword requests | 0 | 0 |
| native region option click | NO | NO |
| fresh search Route | NONE_FRESH | NONE_FRESH |
| region selector header transition | OTHER → OTHER unchanged | OTHER → OTHER unchanged |

**Updated diagnosis:** The core helper calls `selector.first.click(timeout=5000)`
before its 500ms sleep and `on_after_open` callback. Both live rows
show `picker_opened=false` and `STEP_EXCEPTION`; the 500ms
sampling callback was **never invoked**, so the previous hypothesis
that the input was absent at exactly 500ms was **not proven**. In the
second attempt an input was visible later despite the early exception.

A Playwright click call may fail to **complete** after the browser
already dispatched a real click event (for example while waiting for
navigation/event settlement). Conversely, it may time out before any
click. The current evidence cannot choose between those possibilities.

Also, `egress.state=DISABLED` here reflects the omitted opt-in
`--egress-context`, **not** an OCI network outage. Earlier independent
OCI baseline classified outbound as KR/ORACLE_CLOUD; that does not
prove marketplace endpoint availability.

## Follow-on implementation

PR #55 adds:
1. `daangn_v4_1_core.ui_select_region` **finite** progress markers:
   `BEFORE_REGION_BUTTON_CLICK`, `AFTER_REGION_BUTTON_CLICK`,
   `AFTER_500MS_WAIT`, `AFTER_OPEN_CALLBACK`, etc, retained on
   exception. No click/sleep/input logic change.
2. `app_v5/region_header_activation.py`: passive, capture-phase
   document event listeners for `pointerdown`, `mousedown`,
   `pointerup`, `mouseup`, and `click`, **only** when the event
   target is the first-party header's `aria-label` starting with
   `지역 선택`. Fixed counts and trusted counts, plus visible/enabled
   header button counts; **never** captures actual text, raw DOM,
   event target, coordinates, IPs, URLs or timestamps.
3. `picker_phase_diagnostics.core_progress_stage`,
   `core_header_click_returned`, `header_activation`, all
   whitelist sanitized and idempotent.
4. A distinct top-level status `REGION_HEADER_ACTION_EXCEPTION` when
   the core's initial header click call did not complete. It does
   not assert why, and is **not** authorization to collect.

### Interpretation

| Core progress + observed click event | Meaning |
|---|---|
| `BEFORE_REGION_BUTTON_CLICK`, trusted CLICK = 0 | No witnessed header click; inspect selector visibility/interception/timeout using safer bounded diagnostics |
| `BEFORE_REGION_BUTTON_CLICK`, trusted CLICK = 1 | Browser did dispatch header click but `locator.click()` did not complete; investigate Playwright post-action wait, page navigation behavior, and DOM transition |
| `AFTER_REGION_BUTTON_CLICK`, `core_header_click_returned=true`, picker opened false | Failure in subsequent wait or callback, **not** the initial click action |
| `AFTER_OPEN_CALLBACK`, `REGION_INPUT_NOT_FOUND` | Input was genuinely absent at the original 500ms discovery point; compare with 4.2s visible-input count |
| `NO_TARGET_REQUEST` and no input witness | No browser evidence of a target lookup; do not accuse network filtering |
| `ACCESS_RESTRICTED` | Stop; do not use proxies/stealth/login/IP rotation to evade service limits |

A zero witnessed click event is not categorical proof that no click was
emitted: the page may have navigated or the DOM observer may have
missed/remounted the button. A trusted click with an incomplete
Playwright call is a stronger discriminator. No screenshot or trace is
uploaded to the public repo.

## Owner-only next run, only after merged CI

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only
source .venv/bin/activate

# One offline fixture first.
xvfb-run -a python -m scripts.chrome_stable_input_compare --headed

# At most two approved public region attempts in fresh temporary Chrome,
# no listed item/detail visit, profile reuse or region admission.
set -o pipefail
xvfb-run -a python -m scripts.chrome_stable_input_compare \
  --live --headed \
  --owner-approval I_APPROVE_CHROME_INPUT_COMPARISON_V1 \
  | tee "$HOME/daangn_oci_region_header_activation.json"
```

Never run additional live requests after robots denial or access
restriction. The file contains enums/counts only; review
`public_site[*].status` and `picker_phase_diagnostics`.
Even if diagnostics pass, the existing independently verified search
region, filter region, selected UI and fresh Route gates remain
required; `REGION_MISMATCH` stays fail closed.

The host shell is not connected to GitHub tools, so the assistant
cannot install, run or inspect the OCI process directly. Only the
owner can execute that command on the instance.
