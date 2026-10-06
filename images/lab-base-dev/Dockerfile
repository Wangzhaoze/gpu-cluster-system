ARG LOCAL_CUDA_IMAGE=nvidia/cuda:12.8.1-runtime-ubuntu22.04
FROM ${LOCAL_CUDA_IMAGE}
ARG CODE_SERVER_VERSION=4.140.0
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip sudo git curl ca-certificates tmux htop procps build-essential tini util-linux \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir uv==0.6.17 json5==0.12.1 \
    && curl -fL --retry 3 "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server_${CODE_SERVER_VERSION}_amd64.deb" -o /tmp/code-server.deb \
    && dpkg -i /tmp/code-server.deb && rm /tmp/code-server.deb
# Reuse the existing CUDA runtime image and add only the CUDA compiler/dev packages.
RUN apt-get update && apt-get install -y --no-install-recommends cuda-nvcc-12-8 \
    && /usr/local/cuda/bin/nvcc --version \
    && rm -rf /var/lib/apt/lists/*
COPY images/lab-base-dev/entrypoint.sh /usr/local/bin/lab-entrypoint
COPY images/lab-base-dev/ensure-user-env.sh /usr/local/bin/ensure-user-env
COPY images/lab-base-dev/configure-editor.py /usr/local/bin/configure-lab-editor
RUN chmod +x /usr/local/bin/lab-entrypoint /usr/local/bin/ensure-user-env /usr/local/bin/configure-lab-editor \
    && code-server --extensions-dir /opt/lab/extensions --install-extension ms-python.python
ENV NVIDIA_VISIBLE_DEVICES=void
ENV CUDA_HOME=/usr/local/cuda
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/lab-entrypoint"]
CMD ["bash"]
