# 合成部署验收

仅运行合成项目；不挂载真实 `.stories`、宿主 home、浏览器 profile 或 Docker socket。
与 `../real_agent` 共用 `scripts/harness/real_agent/docker/Dockerfile` 构建的同一镜像：

```bash
docker build -f scripts/harness/real_agent/docker/Dockerfile -t storyrail-t07-isolation:20260912 .
```

宿主受信控制器运行 `run.py start`，记录输出 runtime，再运行 `run.py probe --runtime <runtime>`。
`provision.py` 只初始化本次专属 volume；Core 与真实 Pi/子 Pi 使用不同非特权 UID 和各自 volume。
`native_agent.py` 的本地模型协议 fixture 只产生固定工具调用，不向真实模型发送请求。

宿主 `human_gateway.py` 使用 runtime 中两个 0600 临时 token 文件，Core URL 取 start 输出，
证据写入 `--evidence` 指定的隔离目录（默认被忽略的 `var/validation/isolation/`）。
用系统 Chrome 登录并执行修改/重放；不安装 Chromium。
不要打印 token，不保存浏览器密码。页面只用于验证人类 HTTP 身份，不能当作产品登录系统。
完成后停止自己的 gateway，关闭测试标签，运行 `run.py cleanup --runtime <runtime>`；失败时同样清理。
只清理 state.json 中登记的本次资源，不使用 Docker prune。
