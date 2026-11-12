# Controlled hosted timezone comparison — 2026-11-12

## Local baseline received and compared

The owner ran the previously merged read-only local Windows Chrome Stable
baseline on a fresh disposable context with explicit coarse egress opt-in.

| First-load signal | Local Windows | GitHub Windows | GitHub Ubuntu |
|---|---|---|---|
| Initial header family | SEOUL | SEOUL | SEOUL |
| Public search HTTP | 200 | 200 | 200 |
| Browser language | KO | KO | KO |
| Browser timezone | ASIA_SEOUL | OTHER | OTHER |
| Coarse network country | KR | NON_KR | NON_KR |
| Coarse egress operator hint | OTHER | MICROSOFT_AZURE | MICROSOFT_AZURE |
| Cookie before / after ~1.6 s | false / true | false / true | false / true |
| localStorage count | 0 → 9 | 0 → 9 | 0 → 9 |
| sessionStorage count | 0 → 7 | 0 → 7 | 0 → 7 |
| URL requested-region parameter | MISSING | MISSING | MISSING |
| Initial first-party fetch Route | NOT_OBSERVED | NOT_OBSERVED | NOT_OBSERVED |

GitHub evidence:
- [Initial region + coarse egress Run #43165068012](https://github.com/mozzibara/auto-daangn/actions/runs/43165068012)
- [Trusted click + exact header identity Run #43166222890](https://github.com/mozzibara/auto-daangn/actions/runs/43166222890)

All 4 hosted attempts in the second run returned `REGION_NOT_COMMITTED`;
original initial header was category `SEOUL` and stayed **UNCHANGED**
despite expected suggestion, trusted click and one new Route. The local
comparison previously committed to the target successfully under both
FILL and SEQUENTIAL_KEYS, but the owner has supplied only a *no-click*
baseline from the new instrumentation so far.

**Do not infer that the initial Seoul state caused failure**; both
environments started in that state. The local/network/timezone differences
are correlated and still confounded. Browser store counts being identical
do not prove identical cookies, storage contents or internal state.

## New experiment: one variable per GitHub runner

Use the same GitHub Windows-2025 or Ubuntu-24.04 machine, branded Chrome
binary, search page, fresh context, exact input mode `FILL`, locale ko-KR
and hosted egress for **two** sequential arms:

1. `DEFAULT`: inherit actual hosted browser system timezone, expected OTHER.
2. `ASIA_SEOUL`: set only Playwright context `timezone_id=Asia/Seoul`.

The second arm is an *explicit disclosed timezone simulation* on an
experiment-only **new** Chrome context. This is not a stealth browser patch,
proxy/IP shift, authentication transfer or site-access workaround.
Actual egress does not change deliberately. If the hosted environment's
default timezone already is Asia/Seoul, the experiment is invalid
`TIMEZONE_NOT_SEPARATED`.

**Live boundaries**: existing public search and region-suggestion robots
checks are mandatory; no login, listings, seller details, profile reuse,
capture/OCI imports, rate-limit bypass or repeated attempts after an access
denial. At most two region attempts per runner. The third-party coarse
egress estimate is optional and never exports raw IP, city, coordinates or
ASN. Timezone fixture on local-only HTML must pass before any site request.

Outputs remain only fixed enums: initial visible region family, UI, server
search region, filter region, trusted click, route freshness, and
`DEFAULT_FAILED_SEOUL_CONFIRMED`, `BOTH_REGION_NOT_COMMITTED` or a
noncausal inconclusive status. **No result alone proves causality.**
Sequential visits and site variation remain possible confounders.

## Owner-only trigger

Once the pull request is merged and ordinary CI passes, either:
- GitHub owner comments exact `/run-daangn-timezone-control-v1` on Issue #11, or
- owner manually dispatches workflow `region-timezone-control.yml`
  with approval `I_APPROVE_TIMEZONE_REGION_CONTRAST_V1`.

This manual job operates independently from normal PR CI. No raw
network captures, HTML/JSON responses, account credentials or private
artifacts are exported.

### Decision logic for interpretation

- `BOTH_REGION_NOT_COMMITTED` with verified timezone switch and similar
  initial state: timezone-only explanation is **weakened**; investigate
  network egress vs different site bootstrap/region-state handling.
- `DEFAULT_FAILED_SEOUL_CONFIRMED` with otherwise consistent conditions:
  timezone effect **suggested** but not established; a reversed order or
  local follow-up could assess temporal confounding if authorized.
- `TIMEZONE_NOT_SEPARATED` or `STARTING_REGION_DIFFERENT`: invalid
  control comparison, do not infer cause.
- Restriction/challenge/robots denial: **stop**, do not evade.

Given non-KR Azure egress and failure on both OS, a **user-owned OCI
instance** is an optional independent reference environment, not a
guaranteed remedy. Before trying OCI, compare ordinary unmodified Chrome
baseline first; don't route traffic through a different IP to defeat
platform restrictions.

Known public listing URLs and authorized account login remain separate
design discussions. A direct URL does not prove a sale region or inventory
status, and no credential/session export to GitHub Actions is permitted.
