ARG PYTORCH_SOURCE_IMAGE=pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel
FROM ${PYTORCH_SOURCE_IMAGE}
ARG CODE_SERVER_VERSION=4.140.0
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        sudo git curl ca-certificates tmux htop procps build-essential tini util-linux \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir uv==0.6.17 json5==0.12.1 \
    && curl -fL --retry 3 "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server_${CODE_SERVER_VERSION}_amd64.deb" -o /tmp/code-server.deb \
    && dpkg -i /tmp/code-server.deb && rm /tmp/code-server.deb
COPY images/lab-base-dev/entrypoint.sh /usr/local/bin/lab-entrypoint
COPY images/lab-base-dev/ensure-user-env.sh /usr/local/bin/ensure-user-env
COPY images/lab-base-dev/configure-editor.py /usr/local/bin/configure-lab-editor
RUN chmod +x /usr/local/bin/lab-entrypoint /usr/local/bin/ensure-user-env /usr/local/bin/configure-lab-editor \
    && code-server --extensions-dir /opt/lab/extensions --install-extension ms-python.python \
    && nvcc --version \
    && python -c "import torch; assert torch.version.cuda == '12.8'; assert 'sm_120' in torch.cuda.get_arch_list() or torch.backends.cuda.is_built(); print(torch.__version__)"
# This image's preinstalled torch belongs to its own Python interpreter.
# Fresh student venvs inherit its packages; existing Python 3.10 users retain
# their previous pinned template and are never migrated automatically.
ENV LAB_PYTHON=/opt/conda/bin/python
ENV LAB_REQUIRE_TORCH=true
ENV NVIDIA_VISIBLE_DEVICES=void
ENV CUDA_HOME=/usr/local/cuda
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/lab-entrypoint"]
CMD ["bash"]
