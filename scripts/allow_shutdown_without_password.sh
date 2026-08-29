#!/usr/bin/env bash
set -euo pipefail

SUDOERS_FILE="/etc/sudoers.d/hamsibot-shutdown"
SUDOERS_RULE="robotpi ALL=(root) NOPASSWD: /usr/sbin/shutdown, /sbin/shutdown, /bin/systemctl poweroff, /usr/bin/systemctl poweroff"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run with sudo: sudo bash scripts/allow_shutdown_without_password.sh" >&2
    exit 1
fi

printf '%s\n' "${SUDOERS_RULE}" > "${SUDOERS_FILE}"
chmod 0440 "${SUDOERS_FILE}"
visudo -cf "${SUDOERS_FILE}"

echo "HamsiBot can now run shutdown without a sudo password."
