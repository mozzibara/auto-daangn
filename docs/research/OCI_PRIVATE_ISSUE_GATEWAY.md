# Independent private Issue control (development only)

OCI polls a dedicated private GitHub Issue via HTTPS REST. Only exact
/local health and /local doctor from the configured numeric owner ID with
OWNER association, created after initialization and not visibly edited, are
accepted. The cursor binds to repository, issue and owner configuration.
One command per tick; bounded batches; fixed endpoint, no redirects or
proxies. The response is persisted before POST; on retry, the exact visible
owner reply is reconciled. This mitigates duplicates but cannot guarantee
exactly-once delivery under remote eventual consistency.

The systemd timer is a two-minute polling design, not enabled. The service
uses a dedicated daangn-control non-root account, a separate private state
directory, no Linux capabilities, fixed commands and inaccessible production
paths. Its token must be a separately provisioned least-privilege credential
for the private control repository with Issues read/write and Metadata read.
Do not use the existing Actions-read token or put a token in repository text.

28 synthetic tests passed as root and nobody; systemd-analyze verify passed
in a local Linux container. No real token, API calls, service activation or
OCI installation has been tested. No capture, deploy, restart, pause,
resume or Telegram operation is authorized through this channel.
A reviewed administrator installer and full regression remain required.
