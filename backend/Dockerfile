ARG LAB_BASE_IMAGE=lab-base-dev:2026.10-poc
FROM ${LAB_BASE_IMAGE}
ARG LAB_BUILD_FINGERPRINT=development
LABEL lab.application="gpu-cluster-system" lab.service="backend" lab.build.fingerprint="${LAB_BUILD_FINGERPRINT}"
WORKDIR /app
COPY backend/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY tests/backend/ ./tests/
COPY tests/integration/ ./integration/
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-c", "alembic upgrade head && python3 -m app.seed && exec uvicorn app.server:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
