# S1 independent control: development checkpoint

Base: protected main 45e584bc2d236711ad61b30660caf8370c3ab810.
The recorded baseline had 15 successful check runs. New changes are held
on feature/s1-independent-release-control while Actions is unavailable.

Implemented offline:
- release_control: verify an externally authenticated source manifest, atomic
  selection record, locked previous-release selection.
- release_stage: build a manifest on an unprivileged reviewed source export;
  create a separate managed layout and promote already root-owned incoming
  releases without activating services.
- local_gateway: local unprivileged health/doctor only, fixed systemctl show
  queries and finite metadata. Unknown input is denied. No network listener.
- run_oci_offline_tests: clean exact-commit Linux checkout, external venv,
  control/full suite, bounded result summary; no CI or merge authority.

The 21 new module tests passed under root and nobody in an independent
Linux/Python 3.13.5 sandbox; the runner itself was exercised in a synthetic
Git checkout containing these modules/tests (21 passed, dirty checkout
blocked). These are NOT the entire project tests. GitHub blob identities
were compared with the tested files. No production installation was performed.

Next gates before administrator installation:
1. Review module changes and run full regression on the exact new checkout;
   require normal Ubuntu/Windows CI and protected main merge.
2. Authenticate a release manifest from reviewed source independently; verify
   the trusted installer, source completeness and dependency environment.
3. Implement and test the service launcher, migration/rollback compatibility,
   systemd integration and consolidated installation. No arbitrary sudo,
   mutable Runner root execution, or automatic capture enablement.
4. Select an authenticated ChatGPT-to-OCI transport separately. The current
   local gateway is not remotely reachable and does not perform deploy,
   restart, pause, resume, logs or live collection.
5. Validate actual target-neighborhood coverage and existing collection
   evidence gates before any collection activation.

Do not ask the owner to execute the incomplete installer or relax main
protection. The existing /opt/auto-daangn paths, database, keys, Telegram,
Runner and backup policy remain unchanged. The new managed layout is only
a proposed separate path; no actual directories were created on OCI.
