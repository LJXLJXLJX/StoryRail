# 统一 harness 镜像：真实 Agent 验收（external_core.py / external_agent.py）与
# OS 隔离探针（../probes/core_fixture.py）共用同一个多阶段文件，避免两代重复。
# 构建（仓库根目录）：
#   docker build -f scripts/harness/real_agent/docker/Dockerfile -t storyrail-r08-external:20260913 .
#   docker build -f scripts/harness/real_agent/docker/Dockerfile -t storyrail-t07-isolation:20260912 .
# 两个标签共用同一层；差异只在容器 CMD（探针显式传 core_fixture.py）。
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g @earendil-works/pi-coding-agent@0.85.0 \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir mcp==2.2.0 pytest==9.0.2
WORKDIR /app
COPY core core
COPY server server
COPY storyrail_contracts storyrail_contracts
COPY integrations integrations
COPY tests tests
COPY scripts/harness scripts/harness
ENV PYTHONPATH=/app:/app/tests PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
CMD ["python", "/app/scripts/harness/real_agent/external_core.py"]
