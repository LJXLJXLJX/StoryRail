# SeedVR2 7B Sharp FP8 Provider

模型级视频超分插件，标识为 `seedvr2.7b-sharp-fp8`。Core 按 `source_video` 和 `seed` 角色构造 recipe；插件固定短边 720、长边 1280，不知道模型目录、CUDA 或部署系统。


`manifest.py` 声明槽位与参数，`plugin.py` 提供安装工厂。实现通过 `submit_recipe` 接收 Core 校验后的通用请求，再翻译为本插件 HTTP DTO。
