# Google Chrome Stable: fill vs sequential input event comparison

The owner-operated normal Chrome manual experiment confirmed a target-region
selection with a genuinely new first-party search response and two matching
region IDs. The Actions Playwright Chromium environment failed the same
region commitment. This experiment separates **input event modality**
from a separate browser (Chrome Stable rather than Playwright Chromium).

## Stages

1. **Offline real Chrome fixture (default):** start the *installed branded
   Google Chrome Stable* (Playwright `channel="chrome"`). Use a local HTML
   input created with `page.set_content` and compare `locator.fill` against
   `locator.press_sequentially("불당동", delay=80)`. No network requests,
   marketplace pages, cookies, user login, or personal Chrome profile.
2. **Owner-only public UI experiment (separately approved):** after checking
   robots.txt for the exact public HDD search and known region-picker
   endpoint, run at most two **fresh, isolated Chrome contexts** under the
   same Chrome Stable **headed virtual display** (`xvfb-run` on Ubuntu).
   Both open the same public search and use the identical guarded public
   region selector with a unique matching API candidate and stable DOM.
   First uses `FILL` + one normal pointer click; second uses
   `SEQUENTIAL_KEYS` + one normal pointer click.
3. Passively observe DOM input event types, trusted counts and the first
   48 event-type labels; never store characters, keys, input values,
   account identifiers, timestamps or network response bodies in reports.
4. For each run require independent unique API/DOM readiness, a *trusted
   first option click*, one fresh search GET started after the click,
   and target-region IDs matching in the server response and visible
   final selected control after ~4 seconds. Missing or inconsistent
   evidence remains `INCONCLUSIVE`, not authorization.

Neither method triggers an additional confirm click, replayed API call,
listing detail visit, login, account/session copy, anti-bot stealth or
fingerprint change. A blocked/rejected first comparison stops the
remaining comparison. All output is a tightly sanitized set of enums,
counted events and boolean evidence with `authorizes_listings=false`.
This is not a replacement for the signed v4.34 strict capture flow.

The old ordinary human Chrome result came from the owner's Windows Chrome
with actual human keyboard/mouse and a private disposable profile. The
new headed Chrome Stable result will be from a **GitHub-hosted Linux
runner controlled by Playwright**. They are not identical environments:
a success/failure is evidence about input behavior under that runner,
not proof that manual and automated sessions are equivalent.

## How to run the offline local fixture

```powershell
cd C:\kmj-ai-agent\auto-daangn-public
git pull --ff-only
.\.venv\Scripts\Activate.ps1

python -m scripts.chrome_stable_input_compare
```

Google Chrome Stable must be installed. This fixture does **not** visit
Daangn. The GitHub offline CI additionally executes this fixture on
the GitHub-hosted Ubuntu 24.04 runner's preinstalled Chrome Stable,
independently of the Python-only tests.

## How to authorize exactly one public UI comparison

On GitHub issue #11 (repository owner only), comment the exact command:

`/run-daangn-chrome-input-compare-v1`

Alternatively manually dispatch the `Owner-approved Chrome Stable public
region input comparison` workflow with the exact approval input
`I_APPROVE_CHROME_INPUT_COMPARISON_V1`.

The new workflow is disabled for all non-owner comments and never receives
secrets, keys or access tokens. It uses trusted `main` and runs a single
robots-first pair of non-logged-in public region UI sessions; if the site
disallows either URL, it fails closed without loading any marketplace page.
The job prints **only** the sanitized JSON to Actions logs. It does not
upload an artifact or transmit anything to OCI.

## Output interpretation

- `fixture[mode].input_events.counts.KEYDOWN/KEYUP/INPUT` and
  `sequence`: actual event differences on local HTML in real Chrome Stable.
  For non-ASCII text, Playwright's keyboard insertion may not generate
  ordinary hardware-key events, which is exactly what the witness tests.
- `public_site[mode].input_events`: the same event categories on the
  site's actual region search input; useful to compare event handlers.
- `api_ready=true` and `api_candidate_matches_expected=true`:
  verified resolver and stable one-target dropdown; **not** final region proof.
- `native_click=YES`: browser-generated trusted first target click,
  independently witnessed on the intended option.
- `route_status=ONE_FRESH`: one first-party GET started after that trusted
  click, verified by request-start timing.
- `server_search/server_filter/selected_ui=EXPECTED`: final locality
  corroborated on independent server and UI surfaces.
- `TARGET_REGION_CONFIRMED_DIAGNOSTIC`: one diagnostic run's locality
  consistent; no marketplace listing approval.
- `REGION_NOT_COMMITTED`: one fresh Route and final UI both OTHER.
- `API_OR_DOM_NOT_READY`, `CLICK_NOT_TRUSTED`, `INCONCLUSIVE`:
  insufficient proof to infer the cause.
- `ACCESS_RESTRICTED`: stop all further tests. No attempt to bypass.

If both live variants return OTHER, the input mode difference is
insufficient in this Chrome Stable CI environment. The follow-up would
be to compare *manual human interactions* on the same host or inspect
site-controlled application state through allowed UI-only witnesses,
not to fake events or weaken locality gates.

References:

- [Playwright Python branded Chrome support](https://playwright.dev/python/docs/browsers)
- [GitHub Ubuntu 24.04 included software](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
- [Playwright Python headed Linux execution with Xvfb](https://playwright.dev/python/docs/ci)


## Manual Chrome IME contrast: subsequent diagnostic

A passive document-delegated witness now attaches **before** the owner opens
the region selector in ordinary Chrome. The region input may be mounted
after the dialog opens, so arming a locator on an already-existent text
field was not sufficient for the owner/manual session.

Compare the manual output \`manual_input_events.AT_CLICK\` with the two
automated \`public_site[].input_events\` records. The exact comparison is
on fixed event-kind counts, trusted counts, first 48 event-kind labels,
and classified \`InputEvent.inputType\`/boolean \`isComposing\` counts only.
The manual \`AT_CLICK\` snapshot includes any blur triggered by the user's
click; the automated \`input_events\` snapshot is taken **before**
candidate selection. Therefore inspect pre-click keyboard and composition
patterns primarily, not aggregate blur-count equality.

Additionally inspect \`input_focus.AT_CLICK/AFTER_4000MS\` in manual
output against \`input_focus.BEFORE_SELECT/AFTER_CLICK/AFTER_4000MS\`
in the automated output. These are structural classes, not element IDs
or hidden React state.

The offline Chrome fixture also creates a synthetic region dialog **after**
arming the delegated observer and types into a local HTML input to
verify dynamic listener attachment and teardown. This is not evidence of
human Korean IME behavior and contacts no marketplace endpoint.

Do not convert differing events into spoofed trusted events, browser
fingerprint modifications, authentication changes, forced clicks or
relaxed region gates. Follow the repository's existing one-shot owner
approval for any further live comparison.
