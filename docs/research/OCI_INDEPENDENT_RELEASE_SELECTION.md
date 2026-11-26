# Independent OCI release selection (S1, offline)

This is a release verification and atomic selection primitive, not a live
installer, service launcher or privileged remote gateway. It requires an
administrator-local invocation from separately trusted code. It does not
download or execute release code.

The fixed future managed layout is /opt/auto-daangn-managed/releases/<commit>,
with a root-owned release-manifest.json and an independently authenticated
expected SHA-256 of that manifest. The manifest maps relative source paths to
their SHA-256 digests. All files and directories must be trusted-owner,
non-group/world-writable, ordinary files/directories, with no symlinks or
hardlinked files. Dot paths, unlisted content and oversized input fail closed.
Virtualenvs and Git metadata are intentionally not release source payloads.

Selection metadata uses one locked atomic replace and records current and
previous release identities. Selecting or rolling back revalidates both
releases and requires the expected current commit. This is not DB rollback:
no state, secrets, existing deployments, timers, or services are modified.
If the current or previous tree is corrupted, manual recovery is required.
An error after atomic replace (e.g. directory fsync failure) requires reading
the resulting selection before attempting another transition.

Tested in an independent POSIX sandbox: 8 tests passed. No repository-wide
regression, GitHub CI, production installation, dependency lock verification,
service launcher, or release provenance verification is claimed. The
administrator must independently authenticate the expected manifest digest;
a self-generated digest is not provenance. Do not delegate this CLI to a
Runner via sudo. A later installer must make the launcher/code trusted and
validate schema compatibility, service health and recovery before activation.
