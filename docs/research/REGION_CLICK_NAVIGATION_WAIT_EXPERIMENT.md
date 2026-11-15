# REGION_MISMATCH: native click navigation-wait experiment (diagnostic only)

## Established independent evidence

1. Owner manual Chrome: one visible Cheonan Buldang-dong target click successfully committed a first-party search Route with matching server locality.
2. Automated GitHub-hosted Chrome: an independently trusted region click sometimes produced an OTHER server locality and OTHER selected UI after settlement. This is a REAL failure to commit a region, not a cosmetic URL mismatch.
3. OCI headed precollection FILL: selected locality and immediate Route could be EXPECTED, but after filter Apply the page URL omitted the region query parameter. The dynamic response showed EXPECTED region/category/available, but the back-end maximum price enforcement was not independently proven. This must not be silently promoted to a real listing.

The original REGION_MISMATCH, the post-Apply regionless URL and backend price-enforcement uncertainty are independent blockers.

## Hypothesis: Playwright click waits after native dispatch

Playwright locator.click may wait for initiated navigations even after a native pointer click was delivered. A timeout does NOT prove the site missed the click. The official reference https://playwright.dev/python/docs/api/class-locator#locator-click describes the no_wait_after flag (note it is deprecated and may not affect every release).

This opt-in experiment changes only the locator.click navigation-wait setting for ONE normal region-header pointer click and ONE normal unique-visible region-option pointer click. No forced click, repeated click, direct dispatchEvent, synthetic input, region parameter fabrication, headless stealth, login, proxy or robots bypass. All existing native click event/Route request-start/UI locality witnesses and filters are retained. Default capture and production behavior are unchanged.

## Owner-run one-shot OCI diagnostic

Work ONLY from the separate nonroot OCI research checkout, not the production checkout.

~~~bash
cd "$HOME/code/auto-daangn-region-diagnostic"
git pull --ff-only origin main
source .venv/bin/activate

# No marketplace access in tests or preflight
python -m unittest discover -s tests -p 'test_region_click_navigation_wait_experiment.py' -v
python -m scripts.oci_region_preflight --strict

# Precisely approved one-shot test: still requires robots-first and isolated path.
xvfb-run -a python -m ops.oci.precollection \
  --live --headed --no-wait-region-click \
  --owner-approval I_APPROVE_OCI_REGION_CLICK_NO_WAIT_V1
~~~

The command outputs sanitized finite enums only, never listings, URLs, titles, seller profiles, cookies or raw response bodies. The one-shot run never enables live capture, accesses a detail page, writes the production database or sends a Telegram message. The CLI rejects other approvals and also rejects simultaneous dynamic-metadata or changed-loader modes.

## Outcomes

- STOP_REGION_NOT_VERIFIED: native action/Route/UI still does not prove correct locality. STOP; do not synthesize a query or click again.
- STOP_FILTERS_NOT_VERIFIED: locality confirmed but strict post-Apply filter URL, server price/category/availability metadata or UI still insufficient; no listing events.
- PRECOLLECTION_EVIDENCE_COMPLETE: all existing strict locality/filter proofs passed for the bounded session; still authorizes_listings=false. A separate signed full-capture approval and item-level locality/price/status verification are required before any live event becomes eligible.
- ROBOTS_NOT_ALLOWED or ACCESS_RESTRICTED: stop without retry/proxy/login/stealth measures.

The flag is a diagnostic candidate, not a claimed REGION_MISMATCH fix or proof that a live Telegram event exists. Once the new approved capture verifies the hypothesis, the next PR can wire a separately approved v4.34 full capture arm without relaxing its encrypted signer/import gates.
