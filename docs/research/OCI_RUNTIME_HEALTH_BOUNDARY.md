# OCI runtime health boundary

Status opens the existing SQLite database with mode=ro and query_only,
validates the persisted HMAC binding, and reads aggregate counts in a
single snapshot. It does not instantiate HistoryStore, initialize metadata
or migrate older schemas. SQLite may maintain WAL shared-memory sidecars;
immutable mode is not used because it can ignore committed WAL data.

Old schema or missing binding is a failure, not a repair. Migration/repair
belongs to a separately reviewed operator transaction. No service, key,
signing policy or live capture authorization changes occur from source merge.

RED: three tests reproduce the writable constructor, silent migration and
silent HMAC metadata rebind in the old health path.
