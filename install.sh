#!/usr/bin/env bash
# Install mk321-remap for the current user:
#   - the Python package (pipx if available, otherwise a private venv)
#   - the udev rule giving your desktop session access to the keypad (sudo)
#   - an example config, if you don't have one yet
#   - a systemd user service that starts with your desktop session
#
# Usage: ./install.sh [--no-udev] [--no-service] [--udev-only] [--uninstall]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP=mk321-remap
BIN_DIR="${HOME}/.local/bin"
VENV_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/${APP}/venv"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/${APP}"
UNIT_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
UDEV_RULE=/etc/udev/rules.d/70-mk321-remap.rules

do_udev=1
do_service=1
do_package=1
uninstall=0

for arg in "$@"; do
  case "$arg" in
    --no-udev) do_udev=0 ;;
    --no-service) do_service=0 ;;
    --udev-only) do_package=0; do_service=0 ;;
    --uninstall) uninstall=1 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

as_root() {
  if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi
}

reload_udev() {
  as_root udevadm control --reload-rules
  as_root udevadm trigger --subsystem-match=input --action=change
  as_root udevadm trigger --subsystem-match=misc --sysname-match=uinput --action=change
}

if [[ $uninstall -eq 1 ]]; then
  log "Removing ${APP}"
  systemctl --user disable --now "${APP}.service" 2>/dev/null || true
  rm -f "${UNIT_DIR}/${APP}.service"
  systemctl --user daemon-reload 2>/dev/null || true
  if command -v pipx >/dev/null && pipx list --short 2>/dev/null | grep -q "^${APP} "; then
    pipx uninstall "${APP}"
  fi
  rm -rf "$(dirname "${VENV_DIR}")"
  [[ -L "${BIN_DIR}/${APP}" ]] && rm -f "${BIN_DIR}/${APP}"
  if [[ -f "${UDEV_RULE}" ]]; then
    as_root rm -f "${UDEV_RULE}"
    reload_udev
  fi
  log "Done. Your config in ${CONFIG_DIR} was left in place."
  exit 0
fi

if [[ $do_package -eq 1 ]]; then
  if command -v pipx >/dev/null; then
    log "Installing package with pipx"
    pipx install --force "${REPO_DIR}"
  else
    log "Installing package into ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
    "${VENV_DIR}/bin/pip" install --quiet --upgrade pip
    "${VENV_DIR}/bin/pip" install --quiet "${REPO_DIR}"
    mkdir -p "${BIN_DIR}"
    ln -sf "${VENV_DIR}/bin/${APP}" "${BIN_DIR}/${APP}"
  fi

  if [[ ! -f "${CONFIG_DIR}/config.yaml" ]]; then
    log "Creating ${CONFIG_DIR}/config.yaml from the example"
    mkdir -p "${CONFIG_DIR}"
    cp "${REPO_DIR}/config.example.yaml" "${CONFIG_DIR}/config.yaml"
  fi
fi

if [[ $do_udev -eq 1 ]]; then
  log "Installing udev rule to ${UDEV_RULE} (needs sudo)"
  as_root install -m 0644 "${REPO_DIR}/udev/70-mk321-remap.rules" "${UDEV_RULE}"
  reload_udev
fi

if [[ $do_service -eq 1 ]]; then
  log "Installing systemd user service"
  mkdir -p "${UNIT_DIR}"
  install -m 0644 "${REPO_DIR}/systemd/${APP}.service" "${UNIT_DIR}/${APP}.service"
  systemctl --user daemon-reload
  systemctl --user enable "${APP}.service"
  systemctl --user restart "${APP}.service" || true
fi

log "Installed."
cat <<EOF

Next steps:
  ${APP} listen                       # press each button, note the names
  \$EDITOR ${CONFIG_DIR}/config.yaml  # map them
  ${APP} check
  systemctl --user restart ${APP}
  journalctl --user -u ${APP} -f      # logs
EOF
