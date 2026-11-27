# Independent CI execution — scope correction and pre-install candidate

The owner explicitly limited this milestone to an Actions-independent execution
and result channel. Marketplace collection, Telegram and application service
management are not completion criteria.

A standalone package was built and tested in an independent Linux container:
oci_ci_alternative_preinstall.zip
SHA-256: 04c3db6f8a0b5de917ac3b05819f54085440aa5c71cbbaa9f37f11bcbf848b05
Runtime payload.json SHA-256:
dbcd7f7e71bacc48a7ac236b8e0dccdd0dcde375097c79044851f809252a4309

Commands: /ci health, /ci test PROFILE COMMIT_SHA,
 /ci run PROFILE COMMIT_SHA, /ci result JOB_ID.
Public repository profiles support Python unittest and fixed reviewed Python
or shell entrypoints. Controller and worker use distinct non-root UIDs;
the worker has no control token, and systemd units specify network isolation.
Exact commit fetch and Git tree/blob verification are implemented; API polling,
bounded result feedback, replay/interruption handling, preparation and explicit
activation are implemented. No root delegation or protected-main bypass.

Observed offline evidence: 21/21 tests passed as root and nobody in the local
container; synthetic cross-UID end-to-end run passed; all four systemd unit
files passed systemd-analyze verify. Live GitHub fetch/API, OCI systemd
isolation and real execution on OCI remain installation acceptance tests.
The package does not implement all GitHub Actions features, private source
fetch, arbitrary commands, hosted OS matrices, or required GitHub CI checks.
Only reviewed code is appropriate for this worker.

Source delivery limitation: the container cannot resolve github.com, and the
available GitHub connector does not accept a local file reference for upload.
The exact source is delivered as the conversation's downloadable ZIP, not
committed in this checkpoint. This commit records the verified source hashes,
not a source-code merge or deployable GitHub branch. Do not install the older
read-only gateway as a substitute for this package.

No OCI changes, token issuance, Actions dispatch, PR creation, or main merge
were performed. The existing private Issue #28 is the intended command channel
after explicit operator installation. No installation is authorized by this
checkpoint.

Git blob SHA-1 of the exact tested package files:
- bridge.py f013e1ce289e5cb0d27832e20e1719569719be85
- prepare.py 4d4688c6ca4dcce26ec07c0c7bec07bbeb3e02ac
- activate.py 21850fc09f30d8e0bb719081efb8e474a7788122
- test_bridge.py 7d678a093e7759f9de7237b7f73623f74101fbef
- test_prepare.py 306693897e828d106bd8753adee48ab696feb889
- config.example.json be0b619f0fd30b5c6ab55af511096bda7fa42254
- payload.json 1c26db646c7a100f7d32c8042820afa9db4b17d5
- README.md 98fb3b35093e47859c612ee0552d3aa775d2cecb
- oci-ci-alt-poll.service 830111701cf8fe20301aa138a3e3f73cada80003
- oci-ci-alt-worker.service d3393feca3e18fe7909961c867ee129264d459a6
- oci-ci-alt-poll.timer 28b4cdd7fa76a1853ca39d0ba937ecfb433e2b64
- oci-ci-alt-worker.timer 859526f363bebaa6df84f31ee0ef6626a62c8e79
