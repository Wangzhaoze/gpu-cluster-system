#!/usr/bin/env bash
set -euo pipefail
: "${LAB_USERNAME:?}" "${LAB_UID:?}" "${LAB_GID:?}"
getent group "$LAB_GID" >/dev/null || groupadd -g "$LAB_GID" "$LAB_USERNAME"
id "$LAB_USERNAME" >/dev/null 2>&1 || useradd -m -u "$LAB_UID" -g "$LAB_GID" -s /bin/bash "$LAB_USERNAME"
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$LAB_USERNAME" > "/etc/sudoers.d/lab-$LAB_USERNAME"
chmod 440 "/etc/sudoers.d/lab-$LAB_USERNAME"
mkdir -p /workspace/.lab/code-server /results /scratch /opt/user-env
chown "$LAB_UID:$LAB_GID" /workspace /results /scratch /opt/user-env
chown -R "$LAB_UID:$LAB_GID" /workspace/.lab
ensure-user-env
export VIRTUAL_ENV=/opt/user-env/venv
export PATH="$VIRTUAL_ENV/bin:$PATH"
export HOME="/home/$LAB_USERNAME"
# Persistent VS Code settings/extensions and shell activation across replacement.
printf 'export VIRTUAL_ENV=/opt/user-env/venv\nexport PATH=/opt/user-env/venv/bin:$PATH\n' >> "$HOME/.bashrc"
exec runuser -u "$LAB_USERNAME" --preserve-environment -- "$@"
