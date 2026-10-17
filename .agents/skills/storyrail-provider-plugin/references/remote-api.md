# 接入云端 API

适用于厂商托管模型：调用需要 API Key，任务异步执行，结果以下载链接返回。

## 凭据

`--provider-plugin <package>=<endpoint>` 只传 endpoint，不传凭据。插件在 `plugin_instance` 里从环境变量读取
自己的 Key，变量名固定为 `STORYRAIL_<PACKAGE 大写>_API_KEY`：

```python
def plugin_instance(endpoint: str, transport: HttpTransport | None = None) -> PluginInstance:
    if transport is None:
        key = os.environ.get("STORYRAIL_MY_VIDEO_API_KEY", "").strip()
        if not key:
            raise ValueError("my_video 插件缺少 STORYRAIL_MY_VIDEO_API_KEY。")
        transport = UrllibTransport({"Authorization": f"Bearer {key}"})
    provider = MyVideoProvider(endpoint, transport)
    ...
```

用户把 Key 写进 Git 忽略的 `start.local.env`（`start.sh` 会以 `set -a` 读入并导出给 Core）：

```text
STORYRAIL_MY_VIDEO_API_KEY=sk-...
```

启动：`./start.sh --provider-plugin my_video=https://api.example.com/v1`。

- 认证头格式（`Authorization: Bearer`、`X-API-Key` 等）按厂商文档写在 `UrllibTransport` 的固定头里。
- Key 不进 manifest、插件设置、日志、异常信息或测试；测试用 `transport` 参数注入假传输，绕过读取。
- 厂商要求请求签名（HMAC、时间戳）时，在插件里实现一个满足 `HttpTransport` 协议的签名传输，仍从环境变量取密钥。

## 媒体输入

插件拿到的是字节（`MediaInput.content`），不是 URL。按厂商支持的方式上传：

1. 首选请求体内联：base64 或 data URI（注意厂商的单请求大小上限）；
2. 厂商只接受 URL 时，先调用厂商自己的文件上传接口拿到文件 ID 或临时 URL，再提交任务；
3. 不要把字节上传到第三方图床或你自己的公网服务器来“变出”一个 URL。

`UrllibTransport` 只发 JSON。厂商要求 multipart 上传时，在插件里实现一个满足 `HttpTransport` 协议的
传输方法，或像 `whisper_asr/provider.py` 那样单独构造 multipart 请求；继续只用标准库。

## 异步任务映射

- `submit_recipe`：创建任务，返回 `ProviderHandle(plugin_id, plugin_version, 厂商任务 ID)`。厂商任务 ID
  必须能在 Core 重启后继续查询；同步返回结果的 API 见下文“同步 API”。
- `observe`：查询任务，把厂商状态逐一映射到 `queued` / `running` / `succeeded` / `failed` / `cancelled`；
  未知状态按 `invalid_response` 拒绝，不要默认归为成功或失败。
- `cancel`：厂商支持取消就调用；不支持时返回当前观察，并在 README 写明“取消只停止 StoryRail 等待，
  厂商侧仍可能计费”。
- 限流（HTTP 429）与 5xx：`ModelProviderError(..., retryable=True)`；参数错误、余额不足、内容审核拒绝等 4xx：
  `retryable=False`，`message` 用中文说明原因（不要原样透传含请求细节的厂商报错）。

## 结果下载

`ArtifactDescriptor` 在 `succeeded` 时就要给出准确的字节数和 SHA-256，所以插件必须先拿到字节：

```python
def observe(self, handle):
    data = ...  # 查询任务
    if status == "succeeded":
        content = self._download(data["video_url"])
        self._cache[handle.external_id] = content  # 进程内缓存，供紧接着的 read_artifact
        artifact = ArtifactDescriptor(
            handle.external_id, "video/mp4", len(content), hashlib.sha256(content).hexdigest()
        )
        return GenerationObservation(GenerationPhase.SUCCEEDED, 1.0, "视频已生成。", artifact)


def read_artifact(self, handle, artifact_id):
    content = self._cache.pop(handle.external_id, None)
    if content is None:  # Core 重启后缓存丢失：重新查询并下载
        content = self._download(self._result_url(handle))
    return content
```

- 下载链接只接受 `https`，并校验主机属于厂商文档列出的域名，拒绝其它主机，避免被响应引导去访问任意地址。
- 下载链接会过期时，`read_artifact` 重新查询任务拿新链接；厂商不再保留结果时抛
  `ModelProviderError("artifact_unavailable", ...)`。
- 厂商返回的格式必须是 Core 接受的类型（PNG/JPEG/WebP、WAV、MP4）。只能拿到 MP3、WebM、PCM 裸流时，
  优先在请求里指定输出格式；做不到就改用本地适配服务转换（见 local-service.md），插件本身不调用 FFmpeg。
- 能从响应拿到真实时长时填 `duration_seconds`；拿不到就留空，不要用请求时长冒充。

## 同步 API

有的 API 一次请求直接返回结果，没有可再次查询的任务 ID。按耗时选择：

- 几秒内返回的（多数 TTS、部分生图）：在 `submit_recipe` 里完成调用，以 `uuid4().hex` 作为 `external_id`，
  把字节放进进程内缓存；`observe` 从缓存给出 `succeeded`。缓存丢失（Core 在提交与取回之间重启）时，
  `observe` 返回 `failed`、`error_code="result_lost"`、`retryable=True`，由人决定是否重试；
- 耗时较长的：写一个本地适配服务（见 local-service.md），由它在后台调用厂商 API 并提供异步任务接口，
  插件只对接这个服务。不要让 `submit_recipe` 阻塞几分钟。

## 费用与审核

- 价格、计费单位和内容审核策略写进插件 README，并在第一次真实调用前告诉用户。
- 不在插件里自动重试提交、不偷偷提高分辨率或时长、不在失败后换别的模型；这些都会产生用户没有同意的费用。
