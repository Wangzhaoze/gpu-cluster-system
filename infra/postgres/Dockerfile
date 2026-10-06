ARG LOCAL_CUDA_IMAGE=nvidia/cuda:12.8.1-runtime-ubuntu22.04
FROM ${LOCAL_CUDA_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive NVIDIA_VISIBLE_DEVICES=void PGDATA=/var/lib/postgresql/data
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-14 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY infra/postgres/entrypoint.sh /usr/local/bin/lab-postgres
RUN chmod +x /usr/local/bin/lab-postgres
ENTRYPOINT ["/usr/local/bin/lab-postgres"]
