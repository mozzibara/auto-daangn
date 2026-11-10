#!/usr/bin/env bash
# Manually invoked on Ubuntu 24.04 OCI host; no inbound listener or GitHub secret.
set -Eeuo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "RUN_AS_ROOT_USING_SUDO" >&2
  exit 2
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "UNSUPPORTED_OS_EXPECT_UBUNTU_24_04" >&2
  exit 2
fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
if [[ "$ROOT" != "/opt/auto-daangn" || ! -f "$ROOT/keys/v434/ed25519_trusted_public.bin" ]]; then
  echo "REPOSITORY_MUST_BE_AT_OPT_AUTO_DAANGN" >&2
  exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends git ca-certificates python3-venv sqlite3

if ! id daangn >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/auto-daangn --shell /usr/sbin/nologin daangn
fi
install -d -o daangn -g daangn -m 0700 /var/lib/auto-daangn
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --no-cache-dir \
  -r "$ROOT/ops/oci/requirements-runtime.txt"

cd "$ROOT"
runuser -u daangn -- "$ROOT/.venv/bin/python" -m ops.oci.runtime init \
  --state-dir /var/lib/auto-daangn

install -m 0644 -o root -g root "$ROOT/ops/oci/systemd/daangn-status.service" \
  /etc/systemd/system/daangn-status.service
install -m 0644 -o root -g root "$ROOT/ops/oci/systemd/daangn-status.timer" \
  /etc/systemd/system/daangn-status.timer
systemctl daemon-reload
systemctl enable --now daangn-status.timer
systemctl start daangn-status.service
echo "OCI_PHASE1_INSTALL_SUCCESS"
echo "PUBLIC_KEY_COMMAND: sudo -u daangn /opt/auto-daangn/.venv/bin/python -m ops.oci.runtime public-key --state-dir /var/lib/auto-daangn"
echo "HEALTH_COMMAND: sudo systemctl status daangn-status.service --no-pager"
