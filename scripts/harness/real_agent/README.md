# 真实 Agent 验收

Docker 隔离的真实外部 Agent 实验与正式 Web 构建验收。**opt-in**：真实模型请求需要
仓库所有者明确授权；无授权时只跑合成/离线部分。

## 镜像

`docker/Dockerfile` 是统一的多阶段镜像，`docker/clean_install.Dockerfile` 是无源码的
纯净安装镜像；构建命令写在各自文件头部。合成媒体 Provider 实现在
`../fixtures/synthetic_media.py`，与 `../probes` 共用，不各自维护第二份。

```bash
docker build -f scripts/harness/real_agent/docker/Dockerfile -t storyrail-r08-external:20260913 .
docker build -f scripts/harness/real_agent/docker/clean_install.Dockerfile -t storyrail-r09-clean:20260913 .
```

- `clean_install.Dockerfile` 从全新 Python 基础镜像安装 wheel、MCP 与测试工具；
  不复制 Core 源码、不安装任何 Pi/Codex CLI/Agent SDK。用于纯净安装、启动、HTTP/MCP、
  外部业务与恢复回归。测试数据只写隔离临时目录。
- `docker/Dockerfile` 是独立的真实外部 Agent 实验环境，安装原生 Pi/Kimi 客户端，
  不能作为产品安装依赖证明。Core 与 Agent 运行在独立非特权容器，各自 volume、
  只读根、无宿主 home/socket。

## 组成

- `external_core.py` 使用正式 API/单写租约和合成媒体 Provider；job/字节持久化，
  支持重启观察、未知提交与取消失败注入。
- `external_agent.py` 调用外部原生 Pi，`external_client.py` 提供固定 MCP 工具入口。
- `external_run.py` 是受信控制器：**逐命令精确 grant，绝不自动批准模型意图**。
- `run.py` 提供隔离资源工具（docker 包装、端口分配）。
- `meter_gateway.mjs` 是唯一的测试出站计量代理。`config.mode` **必填**，
  必须显式选择 `openai_responses`（Codex 预算恢复回归）或 `kimi_messages`
  （`external_run.py` 真实路径使用，与 Pi 的 `api: anthropic-messages / model: kimi-for-coding`
  一致）；缺失时网关拒绝启动，不再静默默认。认证仅在宿主持有，转发前记录消耗且不自动重试，
  不记录凭据。

  `kimi_messages` 支持可选 `maxRequests`（全局）与 `trials.<id>.maxRequests`（逐 trial），
  两者都缺省时不限次数；超限按 402 拒绝。`external_run.py` 的
  受信控制器始终写入正整数上限，取 `STORYRAIL_REAL_AGENT_MAX_REQUESTS`，未设置时默认 `40`。
  配置可在不启动服务的情况下按所选 mode 校验必需字段（exit 0/1）：

  ```bash
  node scripts/harness/real_agent/meter_gateway.mjs --validate-config <config.json>
  ```

  控制器配置与网关契约由 `tests/test_real_agent_gateway_config.py` 串起来回归。
  回归必需的原始输入保存在 `tests/fixtures/prompt_contracts/`，不依赖任务账本。
- `workspace_browser_fixture.py` 为单一导演台工作台提供正式
  Core/HTTP/dist 验收。用法：

  ```bash
  PYTHONPATH=.:tests .venv/bin/python scripts/harness/real_agent/workspace_browser_fixture.py \
      --directory /tmp/storyrail-workspace-browser --port 18766
  ```

  只允许仓库外新目录，`--resume` 可恢复本工具的隔离目录；`--add-narration` 通过正式
  Core 另建带旁白身份、参考音色与脚本的合成项目，并打印其 ID。保存三组合成项目与
  Provider 请求/字节证据，任务延迟 15 秒，提示词含“模拟失败”时产生确定失败。
  覆盖真实 Store/CAS、生成/选择与 UI 操作，不代表真实推理或成片视觉质量。

## 纪律

真实模型请求需要已有明确授权。结束回收本次 state 中的精确容器/卷/网络、停止网关并
删除私有配置；不使用全局 prune。开发验收不改变产品 human 权限，也不把合成媒体称为
真实视觉质量通过。
