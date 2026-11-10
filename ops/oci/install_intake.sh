#!/usr/bin/env bash
# Only enable AFTER offsite backup+offline recovery test and API token are ready.
# Installer never creates tokens or modifies existing server private keys.
set -Eeuo pipefail
if [[ "${EUID}" -ne 0 ]]; then echo "SUDO_REQUIRED" >&2; exit 2; fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
if [[ "$ROOT" != "/opt/auto-daangn" ]]; then
  echo "REPO_EXPECTED_AT_OPT_AUTO_DAANGN" >&2; exit 2
fi
if [[ "${1:-}" != "--enable" ]]; then
  echo "RUN_WITH_EXPLICIT_ENABLE_AFTER_VERIFIED_BACKUP" >&2; exit 2
fi
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
STATE=/var/lib/auto-daangn
runuser -u daangn -- "$PY" -m ops.oci.backup gate --state-dir "$STATE"
runuser -u daangn -- "$PY" -m ops.oci.actions_intake poll --state-dir "$STATE" --dry-run

install -m 0644 -o root -g root \
  "$ROOT/ops/oci/systemd/daangn-actions-intake.service" \
  /etc/systemd/system/daangn-actions-intake.service
install -m 0644 -o root -g root \
  "$ROOT/ops/oci/systemd/daangn-actions-intake.timer" \
  /etc/systemd/system/daangn-actions-intake.timer
systemctl daemon-reload
systemctl enable --now daangn-actions-intake.timer
echo "OCI_ACTIONS_INTAKE_TIMER_ENABLED"
echo "NOTE: new signed imports require refreshing offsite backup before next import"
