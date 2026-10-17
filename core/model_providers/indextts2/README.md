# IndexTTS2.5 Provider

实例 ID 为 `indextts2`，recipe 与历史句柄 ID 为 `indextts2.synthesize`。实现 `speech.synthesize`，使用参考 WAV
克隆音色；朗读文本、语言与 seed 来自领域角色，`duration_factor`（0.5–2）和 `emotion_vector`（八维，各维 −1–1）
是按 recipe 保存的机制参数。向量分量顺序为高兴、愤怒、悲伤、害怕、厌恶、低落、惊讶、平静。

`submit_recipe` 翻译为独立 HTTP 服务的 `POST /indextts2/speech`：`content`、`voice_sample`、`randomness`、`pace`、
`emotion`、`language`（auto/zh/en）。接受后保存 `speech_id`；GET 观察、PATCH 取消、GET `/audio/{artifact}` 回收音频。插件严格校验响应和句柄，
不持有项目状态、模型目录、GPU 或安装信息。默认 Windows 私有服务提供该 HTTP 协议；外部服务也可独立实现。

安装后可用 `--provider-plugin indextts2=http://模型服务地址` 装配，在 Provider 设置页绑定“声音克隆”。
旁白、资产中心和 Playground 使用现有通用控件渲染语速与向量；项目同语言音色、文字稿与候选审核规则仍由 Core 校验。

默认部署的 auto 映射 IndexTTS2.5 的中英混合语言 zhen；中文/英文轨道分别提交 zh/en。
