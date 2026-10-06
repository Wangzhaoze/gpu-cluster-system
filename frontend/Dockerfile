ARG LOCAL_NODE_IMAGE=node:20.20.2-bookworm-slim
ARG LAB_BASE_IMAGE=lab-base-dev:2026.10-poc
FROM ${LOCAL_NODE_IMAGE} AS build
WORKDIR /lab-build
COPY frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build
FROM ${LAB_BASE_IMAGE}
WORKDIR /portal
COPY --from=build /lab-build/dist ./
ENTRYPOINT ["python3", "-m", "http.server", "8000"]
