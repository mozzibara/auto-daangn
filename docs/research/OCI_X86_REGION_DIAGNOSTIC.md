# OCI second-instance: x86_64 Ubuntu 24.04 standalone Chrome diagnostic

## Verified architecture

Owner-provided command output:
- `uname -m`: **x86_64** (NOT ARM64)
- `/etc/os-release`: Ubuntu **24.04.5 LTS** (`VERSION_ID=24.04`)
- `python3 --version`: **3.12.3**
- `command -v google-chrome` and `command -v chromium`: **not found**

This architecture is compatible with the standard Google Chrome Stable
`amd64` Debian package and Playwright Python. Use the **same branded
Chrome channel** as the GitHub-runner experiment. Chromium is not required.
The official `dl.google.com` Chrome installer enables a Google APT
repository for browser upgrades; review this before installation.

This is a **separate least-privileged diagnostic workspace**. Do NOT run
the Chrome process as root, do NOT modify or reuse
`/opt/auto-daangn-public-stage`, `/opt/auto-daangn`, or
`/var/lib/auto-daangn`; do NOT load production keys or persistent
browser login profiles. There are no systemd units, listeners, timers or
OCI imports in this procedure.

## Step A — install browser dependencies (operator on OCI)

These are the only host-wide modifications. Check adequate free disk and
memory first:

```bash
free -h
df -h / /home

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  ca-certificates curl python3-venv xvfb xauth fonts-noto-cjk

tmpdir="$(mktemp -d)"
curl -fL --retry 2 --connect-timeout 10 \
  https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
  -o "$tmpdir/google-chrome-stable_current_amd64.deb"
sudo apt-get install -y "$tmpdir/google-chrome-stable_current_amd64.deb"
rm -rf -- "$tmpdir"

google-chrome --version
command -v xvfb-run
command -v xauth
```

Do not add `--no-sandbox`, fingerprint stealth switches, proxies or
browser login. If Chrome installation fails, inspect package errors and
stop rather than switching to a different unverified browser.

## Step B — isolated research checkout

Use the existing unprivileged `ubuntu` shell, with the **public GitHub
code only**:

```bash
cd "$HOME"
mkdir -p "$HOME/code"
git clone --depth 1 --branch main \
  https://github.com/mozzibara/auto-daangn.git \
  "$HOME/code/auto-daangn-region-diagnostic"

cd "$HOME/code/auto-daangn-region-diagnostic"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt

# Runs no network and checks the host, packages and operational isolation.
python -m scripts.oci_region_preflight --strict

# Chrome is launched on a local synthetic page only, with Xvfb for headed mode.
xvfb-run -a python -m scripts.oci_region_preflight \
  --offline-browser --headed --strict
```

If the clone directory already exists, do not overwrite it:
`git -C "$HOME/code/auto-daangn-region-diagnostic" pull --ff-only`
(after reviewing the repository remote). On the server, Python 3.12 in
the dedicated venv is sufficient; GitHub CI separately tests Python 3.13.

Expected result:
- `ready_for_offline_chrome_fixture=true`
- `offline_fixture_passed=true` for the second command
- `public_site_visited=false` and `authorizes_listings=false` always.

The preflight reports only finite booleans/enums. It does not print
environment variables, hostnames, paths, IPs, cookies or credentials.

## Step C — one owner-approved initial baseline (only after offline pass)

This is optional and is **NOT automatically invoked during installation or
normal CI**. Run only on your own server and only when the one-shot public
search is permitted by current robots rules:

```bash
cd "$HOME/code/auto-daangn-region-diagnostic"
. .venv/bin/activate

xvfb-run -a python -m scripts.region_baseline_contrast \
  --live --headed --egress-context \
  --owner-approval I_APPROVE_REGION_BASELINE_V1 \
  --output "$HOME/daangn_oci_initial_region_baseline.json"
```

`--egress-context` sends one request to ipapi.co; that provider sees the
caller IP, but only `KR/NON_KR` and provider hint are included in the
sanitized report. Omit this flag if third-party lookup is not desired.
No user account, no region click, no listing page, and no output to the
operational state directory. Report status `BASELINE_OBSERVED` means
only that the initial baseline was captured, **not** that any target
region or listing passed validation.

Compare the resulting enum-only JSON with the owner's local Windows
baseline and the previously observed GitHub-hosted Windows+Ubuntu
baseline. The decisive question is whether an OCI cloud instance has
the same initial SEOUL selector and foreign egress, or an independent
environment. This is an observational comparison, not proof of a cause.

## Only after Step C: more discriminating one-shot click comparison

If an ordinary OCI baseline is observed and there is no access
restriction, the previously audited, bounded exact region-choice
instrument can be invoked by the operator. This is not part of the
offline installation:

```bash
xvfb-run -a python -m scripts.chrome_stable_input_compare \
  --live --headed \
  --owner-approval I_APPROVE_CHROME_INPUT_COMPARISON_V1
```

That script checks both public search and region-suggestion robots
permissions, performs **at most two** choices (`FILL`,
`SEQUENTIAL_KEYS`), stops on challenge/denial and publishes only
redacted region statuses. It does **not** collect listing details and
can never override `REGION_MISMATCH`.

### Decision guide

| OCI initial/click result | Interpretation |
| --- | --- |
| OCI country KR, region selection succeeds | Cloud hosting alone is not sufficient to cause failure; other environment/network differences remain |
| OCI country NON_KR, region selection fails | Consistent with GitHub failure but not proof that non-KR egress is causal |
| OCI baseline works, click fails | Review UI state, first-party Route and session transition with no access-control bypass |
| OCI site challenge/robots disallow | Stop, do not retry with fingerprint spoofing, proxies, accounts or IP rotation |
| Chrome fixture fails locally | Diagnose OS package/Chrome dependencies first; no live visit |

Alternative user-supplied public listing URL and logged-in local browser
research remain separate designs. Direct URLs do not validate search
Route locality. Avoid transferring account login or browser state from
the local PC to cloud/GitHub workers.

## Source references

- [Google Chrome official Linux download](https://www.google.com/chrome/)
- [Playwright Python installation & Ubuntu 24.04 support](https://playwright.dev/python/docs/intro)
- [Playwright Google Chrome Stable channel](https://playwright.dev/python/docs/browsers)
- [Prior GitHub hostname, region and egress measurements](HOSTED_TIMEZONE_CONTROL.md)
