#!/usr/bin/env bash
# One-time root-only migration from the original /opt/newsday layout to
# versioned releases. Run only during a maintenance window.
set -euo pipefail

readonly app_root=/opt/newsday
readonly service_user=newsdigest
readonly deploy_user=newsday-deploy
readonly runtime_dir=/var/lib/newsday/runtime
readonly release_id="legacy-$(date -u +%Y%m%dT%H%M%SZ)"
readonly legacy_dir="$app_root/releases/$release_id"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi
if [[ ! -x /usr/local/bin/uv ]] || ! UV_PYTHON_INSTALL_DIR=/opt/newsday/python /usr/local/bin/uv python find 3.12 >/dev/null 2>&1; then
  echo "Install uv at /usr/local/bin/uv and its managed Python 3.12 in /opt/newsday/python before running this migration." >&2
  exit 1
fi
if [[ -e "$app_root/current" ]]; then
  echo "$app_root/current already exists; this migration has already run." >&2
  exit 1
fi

id -u "$service_user" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$service_user"
id -u "$deploy_user" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$deploy_user"
install -d -o "$service_user" -g "$service_user" -m 0750 "$app_root/releases" "$runtime_dir/data" "$runtime_dir/output"
install -d -o "$deploy_user" -g "$deploy_user" -m 0730 /var/lib/newsday/incoming

systemctl stop news-web.service news-ingest.timer news-schedule.timer news-dispatch.timer news-retention.timer news-backup.timer
mkdir -m 0750 "$legacy_dir"
tar --create --file=- --exclude=.venv --exclude=data --exclude=output --exclude=releases --exclude=current --exclude=current.next -C "$app_root" . | tar --extract --file=- --directory="$legacy_dir"
rsync -a --delete "$app_root/data/" "$runtime_dir/data/"
rsync -a --delete "$app_root/output/" "$runtime_dir/output/"
ln -s "$runtime_dir/data" "$legacy_dir/data"
ln -s "$runtime_dir/output" "$legacy_dir/output"
chown -R "$service_user:$service_user" "$legacy_dir" "$runtime_dir"

for unit in "$app_root"/ops/systemd/news-*; do
  install -o root -g root -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done
install -o root -g root -m 0750 "$app_root/ops/deploy/newsday-deploy" /usr/local/sbin/newsday-deploy
printf '%s\n' "$deploy_user ALL=(root) NOPASSWD: /usr/local/sbin/newsday-deploy [0-9a-f]*" > /etc/sudoers.d/newsday-deploy
chmod 0440 /etc/sudoers.d/newsday-deploy
visudo -cf /etc/sudoers.d/newsday-deploy

ln -s "releases/$release_id" "$app_root/current"
systemctl daemon-reload
systemctl start news-web.service news-ingest.timer news-schedule.timer news-dispatch.timer news-retention.timer news-backup.timer
echo "Bootstrap complete. Add the GitHub Actions public key to /home/$deploy_user/.ssh/authorized_keys before the first CI deployment."
