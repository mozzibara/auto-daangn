# Initial locality and network egress contrast — 2026-11-12

## Why the new diagnostic exists

The owner's local Windows Chrome Stable headed comparison committed the
Buldang-dong selection with both `fill()` and sequential key entry. The
Ubuntu-hosted and Windows-hosted GitHub Actions comparisons both failed to
commit that region even though an expected suggestion, trusted click and fresh
Route were observed. This is a **host/runtime correlation**, not proof that
GitHub's IP address, Linux, Korean IME, or any specific defense caused it.

The new instrument investigates **baseline state before any region click**:
selected region control, untrusted initial Remix loader region hints, any
naturally occurring initial first-party fetch Route, URL region parameter,
`ko` browser language, `Asia/Seoul` timezone, cookies-present flag, and
local/session storage entry counts. No cookie values or keys leave the page.

It optionally classifies the **outbound network** with one request to
`https://ipapi.co/json/` (country `KR/NON_KR/UNAVAILABLE`, cloud provider
hint only). ipapi.co necessarily sees the caller's public IP; its reported
country and provider are **heuristics**, not legal or exact geolocation.
The actual IP, ASN, city, coordinates, postal code and response body are
**not printed or stored**. Because the request is made through Python, not
the browser, a manually configured Chrome proxy could make the observations
diverge; no proxy is set by this project.

## Read-only local Windows baseline

Run from an activated Python 3.13 project venv with Chrome Stable installed:

```powershell
git pull --ff-only
python -m scripts.region_baseline_contrast --headed
python -m scripts.region_baseline_contrast --live --headed --egress-context --owner-approval I_APPROVE_REGION_BASELINE_V1 --output "$HOME\Downloads\daangn_local_initial_region_baseline.json"
```

The first command after `git pull` is **offline HTML only**, even without
approval. The next command requires the exact owner approval token,
checks robots.txt, navigates to one existing public search page, does not
click a region, and optionally requests coarse egress metadata.

For offline comparison once the hosted redacted JSON has been saved locally:

```powershell
python -m scripts.region_baseline_contrast --compare-local "$HOME\Downloads\daangn_local_initial_region_baseline.json" --compare-hosted "$HOME\Downloads\daangn_hosted_initial_region_baseline.json"
```

This compares categorical information only. `DIFFERENT` is a clue, not a
causal proof.

## GitHub hosted Windows + Ubuntu (owner-only live run)

The workflow
[`region-baseline-egress-contrast.yml`](../../.github/workflows/region-baseline-egress-contrast.yml)
runs two independent jobs on Windows Server 2025 and Ubuntu 24.04 with
**Google Chrome Stable**. It runs an offline HTML fixture first and then
one public search page per job. Linux uses Xvfb, both use `ko-KR` locale
and fresh disposable browser contexts.

Trigger **only when explicitly approved by owner**:
- GitHub Actions workflow dispatch on `main` with exact approval input
  `I_APPROVE_REGION_BASELINE_V1`; or
- the repository OWNER comments the exact standalone string
  `/run-daangn-region-baseline-v1` on Issue #11.

No comments from others, PRs, pushes, or scheduled events can activate the
public-site job. Results are only fixed categories in the job logs. No site
article links, raw responses, login information or artifacts are uploaded.

The existing `chrome_stable_input_compare` tool now also records the
same `initial_baseline` once **before each approved selection attempt**,
using the same page already visited; the site access pattern is unchanged.
You can add `--egress-context` explicitly to the approved Chrome A/B command.

## Interpretations and next bounded steps

| Observation | Interpretation, not proof | Next test |
| --- | --- | --- |
| GitHub baseline UI OTHER, local baseline EXPECTED | Different starting region; do not attribute click failure to input mode | Check first-party initial loader and exact fresh Route categories |
| Same UI but different initial server region | UI may be showing stale/boot state | Investigate first-party Route chronology without additional listing visits |
| Both initial states same; hosted click fails | Startup alone cannot explain failure | Compare post-click state transition only once with new baseline witness |
| Hosted `NON_KR` + Azure, local `KR` | Different network geography/ASN is plausible confounder | Try owner-approved same read-only diagnostic on OCI with a known egress; never treat proxy rotation as a bypass |
| ipapi returns UNAVAILABLE | Third-party probe inconclusive | Do not infer local/foreign region or retry across external providers |
| Page gives a login/challenge/restriction | Access restriction | Stop, no bypass, no new profiles or forced retries |

All user-owned live checks obey the existing exact-URL robots-first policy.
A successful initial region baseline **does not authorize listing capture**,
decryption, transfer to OCI, or disabling `REGION_MISMATCH`.

## Alternative architecture research

**OCI second-instance:** a low-rate systemd one-shot worker as a separately
unprivileged `daangn` account can run the identical baseline code after
independent Chrome ARM64 availability and permissions checks. OCI can have
a consistent public egress location but is still cloud infrastructure.
Host control makes debugging, filesystem permissions and encrypted transfer
simpler; it does not guarantee accepted region selection. Never attach
the public repository's `self-hosted` GitHub Actions runner to a privileged
OCI instance: GitHub strongly warns that public repositories and self-hosted
runners have persistent compromise risk. A reviewed, pinned-code read-only
local systemd service is safer. Keep the existing `ops.oci.runtime` import
scope/keys separate and do not enable collectors or timers just for this study.

**Direct known URLs:** allow owner-provided/share-sheet URLs or verified
owner-only encrypted manifest links as independent *source identity* hints.
Normalize exact public hostname/path and individually verify robots, exact
detail URL identity, title/price, sale/stock state, the item's own locality,
and capture freshness. A URL is not proof of seller location, active sale
status, or search region. A direct-link workflow would be a separate
source-specific evidence tier and must not be relabeled as
`SEARCH_ROUTE_REGION_VERIFIED` or used to excuse an unrelated failing
search route. No scraper enrichment of unrelated private data.

**Authenticated mode:** The [official Karrot PC chat FAQ](https://cs.kr.karrotmarket.com/wv/faqs/1618)
describes phone-app QR login for the account holder. A user-assisted,
local-only read-only session could in principle verify an own-account UI
permission if the service terms and robots allow it. **Do not** transfer
cookies, access tokens, QR screenshots, passcodes or Playwright storage state
to public GitHub Actions, OCI or open logs. Authentication does not establish
a valid region, and it does not permit using private APIs or bypassing rate
limits. No account-automation code, QR automation, or background login was
added.

Daangn's [operational policy](https://cs.kr.karrotmarket.com/wv/faqs/41?type=karrot)
encourages local face-to-face exchange; its
[acceptable-use guidance](https://cs.kr.karrotmarket.com/wv/faqs?from_tag=true&q=%EA%B3%BC%EC%9D%BC&type=karrot)
notes that abnormal API access, security-policy bypass, and misuse can cause
access restrictions. Continue strictly public, bounded, operator-approved
checks unless explicit platform permission for additional methods is obtained.

Official infrastructure references:
- [GitHub-hosted runner egress and dynamic network](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [GitHub self-hosted runner security](https://docs.github.com/en/actions/reference/security/secure-use)
- [ipapi.co fields and service behavior](https://ipapi.co/api/)
- [Google Chrome ARM64 Linux](https://support.google.com/chrome/answer/95346)
