# Read-only deployment preflight

This operator-local tool records only finite booleans and status codes for
the existing OCI host. It checks account separation, private state metadata,
ancestor ownership, Runner identity positive control and access denial, Telegram spool read-only ACL,
status timer, inactive backup and absent/disabled intake. It reads neither
database contents nor key/token values. It neither installs nor enables any
service. It does not verify sudoers/Polkit or full source integrity.

Run only from a reviewed, independently pinned source copy, as part of the
future consolidated administrator installation session. Do not delegate
root execution of a mutable Git checkout to the Runner. The existing
operator audit is useful but not equivalent to this new preflight.
READY_FOR_REVIEW is not deployment approval. A blocked or unknown result
must remain blocked, and privileged delegation requires its own audit.

The current migration baseline expects /opt/auto-daangn as the status unit
working directory. Intake is deliberately not activated. The offsite backup
policy remains disabled. No repository change activates real collection.
