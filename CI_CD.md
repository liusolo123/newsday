# Newsday GitHub Actions deployment

This project deploys a reviewed `main` commit as an immutable release. GitHub
Actions runs `make check`, uploads a Git archive over SSH, and then invokes a
root-owned server script with only the commit SHA. Secrets, PostgreSQL data,
backups, `data/`, and `output/` never enter Git or a release archive.

## One-time GitHub setup

1. Create a private GitHub repository, then add it as this repository's
   `origin` remote and push `main`.
2. In GitHub, create the protected `production` environment and require manual
   approval if a person should approve every production release.
3. Generate a dedicated Ed25519 key pair for CI. Store its private half in the
   repository's `DEPLOY_SSH_PRIVATE_KEY` Actions secret. Do not reuse a personal
   SSH key.
4. Add these repository Secrets:

   - `DEPLOY_HOST`: production server hostname or IP.
   - `DEPLOY_USER`: `newsday-deploy`.
   - `DEPLOY_SSH_PRIVATE_KEY`: CI deployment key.
   - `DEPLOY_KNOWN_HOSTS`: the exact `ssh-keyscan -H <host>` result collected
     and verified during server setup.

## One-time server setup

The server must provide `uv` at `/usr/local/bin/uv` and its managed **Python
3.12** at `/opt/newsday/python` before any deployment. This is a deliberate
hard check: the existing Python 3.10 is not a supported production runtime for
this project. It remains untouched; uv supplies a project-specific Python 3.12.
Install and verify the runtime in a maintenance window:

```bash
curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL=/usr/local/bin sh
/usr/local/bin/uv --version
install -d -o newsdigest -g newsdigest -m 0750 /opt/newsday/python
install -d -o newsdigest -g newsdigest -m 0750 /var/lib/newsday/cache
UV_PYTHON_INSTALL_DIR=/opt/newsday/python /usr/local/bin/uv python install 3.12
UV_PYTHON_INSTALL_DIR=/opt/newsday/python /usr/local/bin/uv python find 3.12
```

During the same maintenance window, upload this committed revision to the
server and run `bash /opt/newsday/ops/deploy/bootstrap-server.sh` as root. The script
migrates the current application into `/opt/newsday/releases/`, preserves
runtime data under `/var/lib/newsday/runtime/`, installs the restricted release
activator, and switches systemd to `/opt/newsday/current`.

Then authorize only the CI public key for `newsday-deploy`:

```bash
install -d -o newsday-deploy -g newsday-deploy -m 0700 /home/newsday-deploy/.ssh
install -o newsday-deploy -g newsday-deploy -m 0600 /path/to/ci-deploy-key.pub /home/newsday-deploy/.ssh/authorized_keys
```

Verify `sudo -l -U newsday-deploy`: it must allow only
`/usr/local/sbin/newsday-deploy <SHA>`, not arbitrary root commands.

## Day-to-day release and rollback

Pushing a reviewed commit to `main` runs the workflow in
`.github/workflows/deploy.yml`. A successful deploy creates
`/opt/newsday/releases/<commit SHA>` and atomically points
`/opt/newsday/current` at it.

To roll back application code, push or manually dispatch a known-good commit.
Database migrations are intentionally not automatically downgraded; restore the
pre-migration PostgreSQL backup if a rollback requires it.
