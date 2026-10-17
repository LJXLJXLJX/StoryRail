# Codex Image Provider

插件标识：`codex.image.generate` 与 `codex.image.edit`。

本插件故意把两种具体用法分开：

- `generate` 调用 `/codex/image-generations`，参考图只约束身份、风格或空间，模型重新生成构图；
- `edit` 调用 `/codex/image-edits`，必须提供一张 `source_image` 作为底图，其它参考图只提供附加约束。

两种请求各有严格类型和插件 ID，但共用状态观察与 Artifact 读取实现。插件把外部状态和图片产物转换为
Core 内部类型，不负责依赖调度、图片审核、候选选择或项目资产登记。

`manifest.py` 声明槽位与参数，`plugin.py` 提供安装工厂。实现通过 `submit_recipe` 接收 Core 校验后的通用请求，再翻译为本插件 HTTP DTO。
