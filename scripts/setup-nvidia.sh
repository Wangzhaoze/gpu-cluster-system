#!/usr/bin/env bash
# Host setup from NVIDIA's official Ubuntu/Docker installation instructions:
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
# Run with sudo in a maintenance window: this restarts the host Docker engine.
set -euo pipefail
if [[ $EUID != 0 ]]; then
    echo 'Run: sudo ./scripts/setup-nvidia.sh (installs the toolkit and restarts Docker).' >&2
    exit 1
fi
nvidia-smi -L
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg
LAB_NVIDIA_TMP=$(mktemp -d)
trap 'rm -rf "$LAB_NVIDIA_TMP"' EXIT
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor > "$LAB_NVIDIA_TMP/keyring.gpg"
install -m 0644 "$LAB_NVIDIA_TMP/keyring.gpg" /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > "$LAB_NVIDIA_TMP/toolkit.list"
install -m 0644 "$LAB_NVIDIA_TMP/toolkit.list" /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update
LAB_NVIDIA_VERSION=1.20.1-1
apt-get install -y \
    "nvidia-container-toolkit=$LAB_NVIDIA_VERSION" \
    "nvidia-container-toolkit-base=$LAB_NVIDIA_VERSION" \
    "libnvidia-container-tools=$LAB_NVIDIA_VERSION" \
    "libnvidia-container1=$LAB_NVIDIA_VERSION"
if [[ -f /etc/docker/daemon.json ]]; then
    cp -a /etc/docker/daemon.json "/etc/docker/daemon.json.lab-backup-$(date +%Y%m%d-%H%M%S)"
fi
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker
echo 'NVIDIA Container Toolkit configured. Next: ./scripts/lab.sh gpu-test'
