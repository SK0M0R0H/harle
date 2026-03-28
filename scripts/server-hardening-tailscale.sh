#!/usr/bin/env bash
# Optional hardening: Tailscale + UFW inbound only on tailscale0 (SSH and API via tailnet only).
# Run as root on a server that already completed server-init.sh and has a working Harle deploy.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo ./scripts/server-hardening-tailscale.sh)." >&2
  exit 1
fi

HARLE_UFW_API_PORT="${HARLE_UFW_API_PORT:-8000}"

log() {
  printf "[%s] %s\n" "$(date +%H:%M:%S)" "$*"
}

install_tailscale() {
  log "Installing Tailscale."
  curl -fsSL https://tailscale.com/install.sh | sh
  log "Bringing up Tailscale with SSH support."
  tailscale up --ssh
}

configure_ufw_tailscale_only() {
  log "Switching UFW to Tailscale-only inbound (drops public SSH and public :${HARLE_UFW_API_PORT})."
  ufw --force reset
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow in on tailscale0
  ufw --force enable
}

main() {
  install_tailscale
  log "From your laptop (Tailscale app, same tailnet), verify SSH to this host and curl :${HARLE_UFW_API_PORT}/health before continuing."
  read -r -p "Press Enter only after Tailscale SSH works from another machine... " _
  configure_ufw_tailscale_only
  log "Tailscale hardening complete. Use ~/.config/harle/cli.yaml with the server's Tailscale address."
}

main "$@"
