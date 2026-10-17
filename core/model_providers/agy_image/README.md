# AGY 图片 Provider

本目录实现 Core 到私有 AGY 图片 HTTP 服务的窄适配器。它复用统一的图片生成/编辑请求值对象，分别以
`agy.image.generate` 与 `agy.image.edit` 标识持久化 Generation 句柄，并把提交、观察、取消和 Artifact
读取规范化为 Core Provider 语义。

这里不安装或执行 AGY CLI，不读取项目目录，也不管理能力绑定。CLI 只存在于
`default_model_providers_implement/` 私有服务；`manifest.py` 声明 `agy_image.generate/edit` 两个 recipe，
`plugin.py` 构造插件实例；绑定与历史句柄路由由 `core/model_providers/registry.py` 负责。

`manifest.py` 声明槽位与参数，`plugin.py` 提供安装工厂。实现通过 `submit_recipe` 接收 Core 校验后的通用请求，再翻译为本插件 HTTP DTO。
