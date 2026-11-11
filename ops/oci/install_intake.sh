#!/usr/bin/env bash
# Backups are disabled by owner policy. Enable only after validating GitHub Actions token and signed import checks.
# Installer never creates tokens or modifies existing server private keys.
set -Eeuo pipefail
if [[ "${EUID}" -ne 0 ]]; then echo "SUDO_REQUIRED" >&2; exit 2; fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
if [[ "$ROOT" != "/opt/auto-daangn" ]]; then
  echo "REPO_EXPECTED_AT_OPT_AUTO_DAANGN" >&2; exit 2
fi
if [[ "${1:-}" != "--enable" ]]; then
  echo "RUN_WITH_EXPLICIT_ENABLE_AFTER_SIGNED_IMPORT_VALIDATION" >&2; exit 2
fi
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
STATE=/var/lib/auto-daangn
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
echo "NOTE: backups disabled; signed GitHub provenance and sealed payload validation remain required"
