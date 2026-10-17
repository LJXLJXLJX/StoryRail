# Qwen Image 2.1（NoctQ V4）

备选图片插件，实现 `image.generate`（`qwen_image.generate`）与 `image.edit`（`qwen_image.edit`）。
由人类在全局 Provider 设置中绑定；Codex 先安装，未显式绑定时仍是默认图片实现。

插件把 recipe 请求翻译后提交到私有 Windows 模型服务的 `/qwen-image/renders`，观察状态并取回 PNG。
服务端用固定 Comfy Core 节点图执行，基础模型固定为 Qwen Image 2.1 的社区微调 NoctQ V4，不提供模型选择。
生图和改图走同一张图：输入图按传入顺序进入文本编码器，改图时第一张是底图；画布始终由宽高决定，
不跟随第一张图的尺寸。

## 参数与设置

| 项 | 类型 | 说明 |
|---|---|---|
| `prompt` / `aspect_ratio` / `seed` | Core 按领域事实填写 | 项目图片提交由 Core 为每次提交分配 seed，重试沿用原 seed |
| `width` / `height` | recipe 参数，默认留空 | 留空时长边取分辨率档位、短边按比例取整到 32；填写时须同时填写，为 256–2048 内 32 的倍数，优先于档位 |
| `resolution` | 全局设置，默认 `2k` | `1k` / `1_5k` / `2k` 对应长边 1024 / 1536 / 2048 |
| `cfg` | 全局设置，默认 3 | 1–8；大于 1 时启用负向提示词，耗时约翻倍 |
| `steps` | 全局设置，默认 25 | 4–60 的整数 |
| `negative_prompt` | 全局设置，默认空 | CFG 为 1 时不生效 |

全局设置由人类在 Provider 设置中修改，项目与 Playground 共用，每次提交记入 `provider_snapshot`。
采样器 euler / simple、参考图像素预算 1024 与模型文件由服务端固定。

## 提示词约定

manifest 声明 `image_prompt`：输入图标签为 `<image{n}>`，只有一张输入图时称“图片”，画幅不写进提示词。
Core 按这一约定编译 Keyframe 的输入图映射头。随插件发布的
`skills/qwen-image-prompt-writing/` 通过 Keyframe 规划工作集的 `image_prompt.plugin_skills`
交付给 Agent，`references/` 下是 Qwen 官方文生图与编辑提示词模板原文。

`manifest.py` 声明槽位、参数与提示词约定，`plugin.py` 提供安装工厂与 Skill 交付，`provider.py`
把 Core 校验后的通用请求翻译为本插件 HTTP DTO。
