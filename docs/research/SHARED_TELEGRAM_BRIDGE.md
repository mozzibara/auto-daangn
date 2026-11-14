# Daangn → private shared Telegram bot

The public mozzibara/auto-daangn repository **never** receives a Telegram token or personal chat ID. The private mozzibara/oci-control-private repository owns the common Telegram sender for both Runner network alerts and Daangn price-drop alerts.

## Current alert scope

Only authenticated REVIEWABLE PRICE_DROPPED events selected by the existing app_v5.telegram_outbox.signed_price_drops gate. The signed latest AND baseline price must agree. Messages explicitly say seller-confirmed availability and SMART data are unverified. New-listing alerts are not activated: the current v5 event schema has no authenticated NEW_LISTING event.

## Processing stages

1. Existing owner-approved signed capture and strict OCI import succeed; this integration does **not** enable automated marketplace collection or relax REGION_MISMATCH.
2. If and only if the operator has created the private telegram-export directory, the successful signed intake invokes the exporter after the SQLite commit. Any export failure is reported as alert_export=REVIEW_REQUIRED and does not roll back the authenticated import.
3. The daangn-owned exporter writes 0600 JSON records containing only authenticated price events, canonical links and explicit uncertainty. No Bot Token, Chat ID, Telegram HTTP call or GitHub output. Local exports expire after 96 hours; the active event window is 72 hours.
4. The private OCI self-hosted Runner reads only those files through specific POSIX ACLs and validates owner UID, strict filename, schema, event id, price and URL.
5. The private delivery ledger baselines historical exports without sending. New events are deduplicated and sent through the **same Telegram bot and personal chat** used for OCI network incidents.

## Owner-controlled activation (NOT executed by PR or CI)

Requires existing daangn/oci-runner Unix accounts, production source updated to this version, and the setfacl program. Execute on the OCI host as the operator:

~~~bash
STATE=/var/lib/auto-daangn
sudo install -d -o daangn -g daangn -m 0700 "$STATE/telegram-export"
sudo setfacl -m u:oci-runner:--x "$STATE"
sudo setfacl -m u:oci-runner:r-x "$STATE/telegram-export"
~~~

The exporter (running as daangn) grants u:oci-runner:r-- to **each export file only** using setfacl. The OCI Runner retains no read permission for the production DB, HMAC key, recipient private key or artifact inbox. No sudo is given to the Runner.

If the deployed source and venv exist, check the local producer without Telegram access:

~~~bash
cd /opt/auto-daangn-public-stage
sudo -u daangn .venv/bin/python -m ops.oci.telegram_export --state-dir /var/lib/auto-daangn
~~~

Expected output has only counts: verified_price_drops_in_window, created, unchanged and pruned_expired. Never paste private JSON contents into GitHub issues.

Then post /oci daangn on private control Issue #1. The first scheduled private sender invocation baselines existing export files. A later new verified price drop may trigger a Telegram message. Source merges alone do NOT deploy to the production checkout or create ACLs.

## Risk and limits

- Telegram Bot API has no sender-provided idempotency key. Remote acceptance followed by an OCI crash before local ACK can duplicate an alert.
- No new market capture, login, region bypass, or backup is enabled here.
- The public exporter code never runs while Bot API credentials are present. The private sender never imports public repository Python with credentials.
- This is a price-history alert, not proof that the item is currently purchasable. Actual new-listing alerts require a separately authenticated candidate-event gate.
- Source files are local transient notification projections, not offsite backups. Disable the export opt-in to stop creating new files without impacting existing Runner alerts.
