# Whisper ASR Provider

该插件连接独立运行的 `whisper.cpp` HTTP server，只把项目内 WAV Reference Voice
提交为中英文转写请求。返回文字是可编辑候选，不会直接写入项目业务 authority；用户确认并提交
Breeze Voice Clone / Direction 时，`reference_transcript` 才随 Generation 持久化。

模型、Metal、权重和服务进程属于 Provider 部署，不进入 Core 或项目 JSON。

`manifest.py` 声明槽位与参数，`plugin.py` 提供安装工厂。实现通过 `execute_recipe` 同步返回文字。
