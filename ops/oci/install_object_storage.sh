#!/usr/bin/env bash
# Run only through sudo bash; no interactive 'set -e' in SSH.
# --prepare: install SDK without any Object Storage API access or timer.
# --enable: only after independently downloaded offsite recovery succeeds.
set -Eeuo pipefail
if [[ "${EUID}" -ne 0 ]]; then echo "SUDO_REQUIRED" >&2; exit 2; fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
if [[ "$ROOT" != "/opt/auto-daangn" ]]; then
  echo "REPO_EXPECTED_AT_OPT_AUTO_DAANGN" >&2; exit 2
fi
ACTION="${1:-}"
if [[ "$ACTION" != "--prepare" && "$ACTION" != "--enable" ]]; then
  echo "CHOOSE_EXPLICIT_PREPARE_OR_ENABLE" >&2; exit 2
fi
"$ROOT/.venv/bin/python" -m pip install --no-cache-dir \
  -r "$ROOT/ops/oci/requirements-object-storage.txt"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
STATE="/var/lib/auto-daangn"
if [[ "$ACTION" == "--prepare" ]]; then
  echo "OCI_OBJECT_STORAGE_SDK_PREPARED_TIMER_NOT_ENABLED"
  exit 0
fi
runuser -u daangn -- "$PY" -m ops.oci.object_storage status --state-dir "$STATE"
runuser -u daangn -- "$PY" -m ops.oci.backup gate --state-dir "$STATE"
runuser -u daangn -- "$PY" -m ops.oci.object_storage probe --state-dir "$STATE"
install -m 0644 -o root -g root \
  "$ROOT/ops/oci/systemd/daangn-object-storage-backup.service" \
  /etc/systemd/system/daangn-object-storage-backup.service
install -m 0644 -o root -g root \
  "$ROOT/ops/oci/systemd/daangn-object-storage-backup.timer" \
  /etc/systemd/system/daangn-object-storage-backup.timer
systemctl daemon-reload
systemctl enable --now daangn-object-storage-backup.timer
echo "OCI_OBJECT_STORAGE_BACKUP_TIMER_ENABLED"
echo "OFFLINE_RESTORE_BASELINE_EXPIRES_AFTER_30_DAYS"
