# Stable Audio 3 Medium

Playground 文生音频插件。把 recipe 请求翻译后提交到私有模型服务的
`/stable-audio-3/generations`，观察阶段并取回 WAV。项目导演台不注册、不调用这个能力。

提示词最长 1000 字，时长 1 到 380 秒。采样步数、CFG 和半精度由模型服务固定，不进入 Core 请求。

`manifest.py` 声明槽位与参数，`plugin.py` 提供安装工厂。实现通过 `submit_recipe` 接收 Core 校验后的通用请求，再翻译为本插件 HTTP DTO。
