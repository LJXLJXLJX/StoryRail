# Demucs Audio Separation Provider

本插件把一个受控 MP4 和目标 stem（`voice` / `background`）提交给外部 Demucs 服务。Core 只处理
经 manifest 校验的 recipe 请求、持久句柄和单个 WAV Artifact；模型、权重、Torch、设备与缓存均属于 Provider 部署。

`manifest.py` 声明槽位与参数，`plugin.py` 提供安装工厂。实现通过 `submit_recipe` 接收 Core 校验后的通用请求，再翻译为本插件 HTTP DTO。
