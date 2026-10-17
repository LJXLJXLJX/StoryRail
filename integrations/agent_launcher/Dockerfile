FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl socat xvfb xclip && rm -rf /var/lib/apt/lists/*
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g @earendil-works/pi-coding-agent@latest @openai/codex@latest @deepseek-ai/dsh@latest @xai-official/grok@latest \
    && curl --compressed -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy-install.sh \
    && bash /tmp/agy-install.sh --dir /usr/local/bin \
    && rm /tmp/agy-install.sh \
    && curl --compressed -fsSL https://code.kimi.com/kimi-code/install.sh -o /tmp/kimi-install.sh \
    && KIMI_INSTALL_DIR=/usr/local KIMI_NO_MODIFY_PATH=1 bash /tmp/kimi-install.sh \
    && rm /tmp/kimi-install.sh \
    && pip install --no-cache-dir mcp==2.2.0
WORKDIR /workspace
COPY --chmod=0755 integrations /app/integrations
# 共享 wire 契约（零依赖）：MCP adapter 的错误信封来自这里，不进 Core 业务代码。
COPY --chmod=0755 storyrail_contracts /app/storyrail_contracts
# MCP server instructions 引用的一致性规则原文（单一事实源在 Core skills）。
COPY --chmod=0755 core /app/core
COPY --chmod=0644 client.py gateway.py clipboard_input.py PROMPT.md PLAYGROUND_PROMPT.md dsh-storyrail.cordis.yml /app/
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PI_CODING_AGENT_DIR=/pi NODE_USE_ENV_PROXY=1 NO_PROXY=gateway,localhost,127.0.0.1
ENV CODEX_HOME=/codex
ENV KIMI_CODE_HOME=/kimi-code
ENV GROK_HOME=/grok
ENV DSH_HOME=/dsh DSH_PERMISSION_MODE=danger-full-access DSH_TELEMETRY_MODE=DISABLED
ENV npm_config_cache=/tmp/npm-cache
USER 10002:10002
