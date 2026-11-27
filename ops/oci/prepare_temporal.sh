#!/usr/bin/env bash
# Local administrator; reviewed root-owned checkout only. Default: dry-run.
# Never starts services, writes an approval, installs packages or touches live DB.
set -Eeuo pipefail
umask 077
export GIT_OPTIONAL_LOCKS=0
[[ "$EUID" -eq 0 ]] || { echo ROOT_REQUIRED; exit 2; }
[[ $# -eq 2 || $# -eq 3 ]] || { echo 'usage: prepare_temporal.sh ROOT_CHECKOUT EXACT_SHA [--apply]'; exit 2; }
ROOT="$(realpath -e "$1")"
SHA="$2"
MODE=--dry-run
if [[ $# -eq 3 ]]; then MODE="$3"; fi
[[ "$MODE" == --dry-run || "$MODE" == --apply ]]
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]]
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]]
trusted_tree() {
    local p="$1"
    [[ -d "$p" && ! -L "$p" ]]
    while [[ "$p" != / ]]; do
        [[ ! -L "$p" && "$(stat -c %u "$p")" == 0 ]]
        [[ -z "$(find "$p" -maxdepth 0 -perm /022 -print -quit)" ]]
        p="$(dirname "$p")"
    done
}
trusted_tree "$ROOT"
[[ -z "$(find "$ROOT" ! -type l \( ! -user root -o -perm /022 \) -print -quit)" ]]
[[ "$(git -C "$ROOT" rev-parse HEAD)" == "$SHA" ]]
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)" ]]
git -C "$ROOT" ls-tree -r "$SHA" | awk '$1!="100644" && $1!="100755" {bad=1} END {exit bad}'
VENV=/opt/daangn-temporal-venv
trusted_tree "$VENV"
[[ -z "$(find "$VENV" ! -type l \( ! -user root -o -perm /022 \) -print -quit)" ]]
[[ -x "$VENV/bin/python" ]]
for cmd in git tar systemctl systemd-analyze runuser useradd install /usr/bin/xvfb-run /usr/bin/xauth; do
    command -v "$cmd" >/dev/null
done
command -v google-chrome >/dev/null || command -v google-chrome-stable >/dev/null
systemd-analyze calendar '*-*-* 00,12:17:00 UTC' >/dev/null
H=/var/lib/daangn-temporal-home
S=/var/lib/daangn-temporal-state
C=/etc/daangn-temporal
U=/etc/systemd/system
for p in "$H" "$S" "$C" "$U/daangn-temporal.service" "$U/daangn-temporal.timer" "$U/daangn-temporal.service.d" "$U/daangn-temporal.timer.d"; do
    [[ ! -e "$p" && ! -L "$p" ]] || { echo EXISTING_INSTALL_REVIEW_REQUIRED; exit 2; }
done
! getent passwd daangn-temporal >/dev/null || { echo EXISTING_ACCOUNT_REVIEW_REQUIRED; exit 2; }
! getent group daangn-temporal >/dev/null || { echo EXISTING_GROUP_REVIEW_REQUIRED; exit 2; }
for unit in daangn-temporal.service daangn-temporal.timer; do
    [[ "$(systemctl show "$unit" -p LoadState --value)" == not-found ]] || { echo EXISTING_UNIT_REVIEW_REQUIRED; exit 2; }
    [[ -z "$(systemctl show "$unit" -p DropInPaths --value)" ]] || exit 2
done
echo "PREINSTALL_READY source=$SHA no_approval=true"
[[ "$MODE" == --apply ]] || exit 0
useradd --system --user-group --home-dir "$H" --shell /usr/sbin/nologin --no-create-home daangn-temporal
install -d -o root -g root -m 0755 "$H" "$H/code" "$H/code/auto-daangn-region-diagnostic" "$C"
install -d -o daangn-temporal -g daangn-temporal -m 0700 "$S" "$S/results"
DEST="$H/code/auto-daangn-region-diagnostic"
git -C "$ROOT" archive --format=tar "$SHA" | tar --no-same-owner --no-same-permissions -xf - -C "$DEST"
chown -R root:root "$DEST"
chmod -R a+rX,go-w "$DEST"
printf '%s\n' "$SHA" > "$C/source.sha"
chmod 0644 "$C/source.sha"
# Offline dependencies check as dedicated user. No browser start.
runuser -u daangn-temporal -- env -i PATH=/usr/bin:/bin HOME="$H" "$VENV/bin/python" -I -B -c 'import playwright, cryptography'
cd "$DEST"
runuser -u daangn-temporal -- env -i PATH=/usr/bin:/bin HOME="$H" "$VENV/bin/python" -s -B -m ops.oci.temporal_scheduler init
install -m 0644 -o root -g root "$DEST/ops/oci/systemd/daangn-temporal.service" "$U/daangn-temporal.service"
install -m 0644 -o root -g root "$DEST/ops/oci/systemd/daangn-temporal.timer" "$U/daangn-temporal.timer"
systemd-analyze verify "$U/daangn-temporal.service" "$U/daangn-temporal.timer"
systemctl daemon-reload
[[ "$(systemctl is-enabled daangn-temporal.timer || true)" == disabled ]]
[[ "$(systemctl is-active daangn-temporal.timer || true)" == inactive ]]
echo PREPARED_DISABLED_NO_APPROVAL
