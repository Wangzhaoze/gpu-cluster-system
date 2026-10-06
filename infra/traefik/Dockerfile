ARG LOCAL_CUDA_IMAGE=nvidia/cuda:12.8.1-runtime-ubuntu22.04
FROM ${LOCAL_CUDA_IMAGE}
ARG TRAEFIK_VERSION=3.7.13
ENV DEBIAN_FRONTEND=noninteractive NVIDIA_VISIBLE_DEVICES=void
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/* \
    && curl -fL --retry 3 "https://github.com/traefik/traefik/releases/download/v${TRAEFIK_VERSION}/traefik_v${TRAEFIK_VERSION}_linux_amd64.tar.gz" -o /tmp/traefik.tgz \
    && tar -xzf /tmp/traefik.tgz -C /usr/local/bin traefik && rm /tmp/traefik.tgz
COPY infra/traefik/traefik.yml /etc/traefik/traefik.yml
COPY infra/traefik/dynamic.yml /etc/traefik/dynamic.yml
ENTRYPOINT ["traefik"]
