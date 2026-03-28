#!/usr/bin/env bash
# Baseline VPS bootstrap for Harle: Docker, SSH hardening, UFW (SSH + API port),
# deploy key for GitHub. Does NOT install Tailscale — see server-hardening-tailscale.sh.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo ./scripts/server-init.sh)." >&2
  exit 1
fi

DEPLOY_USER="${HARLE_DEPLOY_USER:-harle}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
SSHD_CONFIG="/etc/ssh/sshd_config"
HARLE_UFW_API_PORT="${HARLE_UFW_API_PORT:-8000}"
# Set HARLE_UFW_OPEN_API=0 to skip opening the API port (use SSH tunnel + HARLE_PUBLISH_HOST=127.0.0.1).
HARLE_UFW_OPEN_API="${HARLE_UFW_OPEN_API:-1}"

log() {
  printf "[%s] %s\n" "$(date +%H:%M:%S)" "$*"
}

ensure_deploy_user() {
  if id "${DEPLOY_USER}" >/dev/null 2>&1; then
    log "Deploy user ${DEPLOY_USER} already exists."
  else
    log "Creating deploy user ${DEPLOY_USER}."
    useradd --create-home --shell /bin/bash "${DEPLOY_USER}"
    usermod -aG sudo "${DEPLOY_USER}"
  fi
}

harden_sshd() {
  log "Applying SSH hardening settings."
  cp "${SSHD_CONFIG}" "${SSHD_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' "${SSHD_CONFIG}"
  sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "${SSHD_CONFIG}"
  if ! grep -q '^PermitRootLogin no$' "${SSHD_CONFIG}"; then
    echo 'PermitRootLogin no' >> "${SSHD_CONFIG}"
  fi
  if ! grep -q '^PasswordAuthentication no$' "${SSHD_CONFIG}"; then
    echo 'PasswordAuthentication no' >> "${SSHD_CONFIG}"
  fi
  systemctl restart ssh || systemctl restart sshd
}

configure_ufw() {
  log "Configuring UFW (SSH always allowed on the public interface)."
  apt-get update
  apt-get install -y ufw
  ufw --force reset
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow OpenSSH
  if [[ "${HARLE_UFW_OPEN_API}" == "1" ]]; then
    log "Allowing Harle API ${HARLE_UFW_API_PORT}/tcp on the public interface (set HARLE_UFW_OPEN_API=0 to skip)."
    ufw allow "${HARLE_UFW_API_PORT}/tcp"
  else
    log "Skipping public API port (HARLE_UFW_OPEN_API=0); use an SSH tunnel or optional Tailscale hardening."
  fi
  ufw --force enable
  log "After optional Tailscale hardening, see docs/runbooks/remote-setup.md."
}

enable_security_updates() {
  log "Installing unattended-upgrades."
  apt-get install -y unattended-upgrades
  dpkg-reconfigure -f noninteractive unattended-upgrades
}

install_docker() {
  log "Installing Docker CE from official Docker repository."
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  usermod -aG docker "${DEPLOY_USER}"
}

setup_github_deploy_key() {
  log "Generating GitHub deploy key for private repo pulls."
  sudo -u "${DEPLOY_USER}" mkdir -p "${DEPLOY_HOME}/.ssh"
  sudo -u "${DEPLOY_USER}" chmod 700 "${DEPLOY_HOME}/.ssh"
  if [[ ! -f "${DEPLOY_HOME}/.ssh/harle_deploy" ]]; then
    sudo -u "${DEPLOY_USER}" ssh-keygen -t ed25519 -f "${DEPLOY_HOME}/.ssh/harle_deploy" -N ""
  fi
  sudo -u "${DEPLOY_USER}" touch "${DEPLOY_HOME}/.ssh/config"
  if ! sudo -u "${DEPLOY_USER}" grep -q 'IdentityFile ~/.ssh/harle_deploy' "${DEPLOY_HOME}/.ssh/config"; then
    cat <<'EOF' | sudo -u "${DEPLOY_USER}" tee -a "${DEPLOY_HOME}/.ssh/config" >/dev/null
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/harle_deploy
  IdentitiesOnly yes
EOF
  fi
  sudo -u "${DEPLOY_USER}" chmod 600 "${DEPLOY_HOME}/.ssh/config"

  echo
  echo "Add this deploy key to GitHub repo Settings > Deploy keys (read-only):"
  cat "${DEPLOY_HOME}/.ssh/harle_deploy.pub"
  echo
}

main() {
  ensure_deploy_user
  harden_sshd
  configure_ufw
  enable_security_updates
  install_docker
  setup_github_deploy_key
  log "Server initialization complete (baseline; no Tailscale)."
}

main "$@"
