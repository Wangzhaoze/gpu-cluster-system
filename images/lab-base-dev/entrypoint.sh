#!/usr/bin/env bash
set -euo pipefail
: "${LAB_USERNAME:?}" "${LAB_UID:?}" "${LAB_GID:?}"

getent group "$LAB_GID" >/dev/null || groupadd -g "$LAB_GID" "$LAB_USERNAME"
id "$LAB_USERNAME" >/dev/null 2>&1 || useradd -m -u "$LAB_UID" -g "$LAB_GID" -s /bin/bash "$LAB_USERNAME"
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$LAB_USERNAME" > "/etc/sudoers.d/lab-$LAB_USERNAME"
chmod 440 "/etc/sudoers.d/lab-$LAB_USERNAME"

export HOME="/home/$LAB_USERNAME"
mkdir -p \
    /workspace/.lab/code-server \
    /results \
    /scratch/xdg-cache \
    /opt/user-env \
    /opt/user-state
chown "$LAB_UID:$LAB_GID" /workspace /results /scratch /scratch/xdg-cache /opt/user-env
chown -R "$LAB_UID:$LAB_GID" /workspace/.lab

# One persistent per-user state volume is shared by Workspace/Debug/Train.
# It carries IDE extensions/settings, Codex credentials/config, shell history,
# XDG config/data, SSH state, git config and user-level npm installs.
exec 8>/opt/user-state/.init.lock
flock 8
mkdir -p \
    /opt/user-state/code-server/user-data \
    /opt/user-state/code-server/extensions \
    /opt/user-state/codex \
    /opt/user-state/xdg/config \
    /opt/user-state/xdg/local/share \
    /opt/user-state/xdg/local/state \
    /opt/user-state/shell \
    /opt/user-state/git \
    /opt/user-state/ssh \
    /opt/user-state/npm/bin

if [ ! -f /opt/user-state/.initialized ]; then
    # Migrate the previous persistent code-server layout on first start.
    # Prefer the long-lived workspace state; otherwise use an existing debug state.
    if [ ! -e /opt/user-state/code-server/user-data/User ]; then
        for candidate in /workspace/.lab/code-server/workspace-* /workspace/.lab/code-server/debug-*; do
            if [ -d "$candidate" ]; then
                cp -a "$candidate/." /opt/user-state/code-server/user-data/
                break
            fi
        done
    fi
    if [ -d /workspace/.lab/extensions ]; then
        cp -an /workspace/.lab/extensions/. /opt/user-state/code-server/extensions/
    fi

    if [ ! -f /opt/user-state/shell/bashrc ]; then
        if [ -f /etc/skel/.bashrc ]; then
            cp /etc/skel/.bashrc /opt/user-state/shell/bashrc
        else
            touch /opt/user-state/shell/bashrc
        fi
    fi
    grep -qxF 'source /opt/user-env/venv/bin/activate' /opt/user-state/shell/bashrc \
        || printf '\nsource /opt/user-env/venv/bin/activate\n' >> /opt/user-state/shell/bashrc

    if [ ! -f /opt/user-state/shell/bash_profile ]; then
        printf 'source "$HOME/.bashrc"\n' > /opt/user-state/shell/bash_profile
    fi
    touch /opt/user-state/shell/bash_history /opt/user-state/git/config

    # A migrated code-server data directory may contain the old shared-volume IPC socket.
    rm -f /opt/user-state/code-server/user-data/code-server-ipc.sock
    touch /opt/user-state/.initialized
    chown -R "$LAB_UID:$LAB_GID" /opt/user-state
fi

chmod 700 /opt/user-state/ssh
# Seed image-provided extensions as the student so later starts do not need a
# recursive chown over a potentially large extension directory.
# Recover containers made from older pinned images whose seed tree was root-only.
if ! runuser -u "$LAB_USERNAME" -- test -r /opt/lab/extensions; then
    chmod -R a+rX /opt/lab
fi
runuser -u "$LAB_USERNAME" --preserve-environment -- \
    cp -r -n /opt/lab/extensions/. /opt/user-state/code-server/extensions/
flock -u 8

# Persist common HOME-level configuration paths even though the container HOME itself
# remains disposable. Existing files from this fresh container are replaced by links
# into the private per-user state volume.
rm -rf "$HOME/.config" "$HOME/.local" "$HOME/.codex" "$HOME/.ssh"
rm -f "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.gitconfig"
ln -s /opt/user-state/xdg/config "$HOME/.config"
ln -s /opt/user-state/xdg/local "$HOME/.local"
ln -s /opt/user-state/codex "$HOME/.codex"
ln -s /opt/user-state/ssh "$HOME/.ssh"
ln -s /opt/user-state/shell/bashrc "$HOME/.bashrc"
ln -s /opt/user-state/shell/bash_profile "$HOME/.bash_profile"
ln -s /opt/user-state/git/config "$HOME/.gitconfig"
chown -h "$LAB_UID:$LAB_GID" \
    "$HOME/.config" "$HOME/.local" "$HOME/.codex" "$HOME/.ssh" \
    "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.gitconfig"

ensure-user-env
export VIRTUAL_ENV=/opt/user-env/venv
export CODEX_HOME=/opt/user-state/codex
export XDG_CONFIG_HOME=/opt/user-state/xdg/config
export XDG_DATA_HOME=/opt/user-state/xdg/local/share
export XDG_STATE_HOME=/opt/user-state/xdg/local/state
export XDG_CACHE_HOME=/scratch/xdg-cache
export HISTFILE=/opt/user-state/shell/bash_history
export GIT_CONFIG_GLOBAL=/opt/user-state/git/config
export NPM_CONFIG_PREFIX=/opt/user-state/npm
export PATH="/opt/user-state/npm/bin:$VIRTUAL_ENV/bin:$PATH"

if [[ ${1:-} == code-server ]]; then
    arguments=("$@")
    user_data=""
    for ((index=0; index<${#arguments[@]}; index++)); do
        if [[ ${arguments[index]} == --user-data-dir ]]; then
            user_data="${arguments[index+1]}"
            break
        fi
    done
    if [ -n "$user_data" ]; then
        flock 8
        if ! runuser -u "$LAB_USERNAME" -- test -r /usr/local/bin/configure-lab-editor; then
            chmod 0755 /usr/local/bin/configure-lab-editor
        fi
        runuser -u "$LAB_USERNAME" --preserve-environment -- configure-lab-editor "$user_data"
        flock -u 8
    fi
fi

exec runuser -u "$LAB_USERNAME" --preserve-environment -- "$@"
