# S1 read-only Issue gateway preparation

The administrator-only preparation tool verifies the staged source release
against the independently authenticated manifest digest and pins the four
exact tested payload files. Default mode reviews the payload; explicit apply
creates or validates a dedicated non-login account and installs only new
control files in the fixed paths. Existing mismatched files are rejected,
not overwritten. Partial preparation may leave newly created files or an
account, but does not request any service start or enable operation.

The token, cursor initialization, real GitHub API smoke test, and timer
activation require a later reviewed administrator session. No new token,
sudo delegation, service activation or production modifications are performed
by this development checkpoint. Do not run bootstrap code from an unreviewed
mutable checkout. Use an independently verified source bundle.

34 synthetic tests passed under root and nobody. Actual useradd, service
activation, distinct production UIDs, network access and complete project CI
remain unverified. GitHub Actions required checks must not be bypassed.
