# Model Providers

本目录保存 Core 侧的具体模型插件。每个子目录对应一个明确模型及用法，并自行适配该外部 HTTP API。
同一模型如果“重新生成”和“基于底图编辑”的请求语义或 endpoint 不同，也必须使用不同的严格请求类型和
插件标识；不能塞进一个可选字段参数袋后让 Provider 猜测。

- `manifest.py`：Core 拥有的语义能力、语义角色与 Widget 词汇，以及插件声明 recipe、槽位、参数与实例设置的 manifest DSL；
  图片插件可声明 `image_prompt` 约定（输入图标签 namespace、单图自然指代、画幅是否写进提示词），Core 据此提供实际输入标签，不自动补写引用说明；
  `ProviderSnapshot` 记录一次提交实际使用的插件、recipe 与设置；
- `registry.py`：已安装插件实例、全局能力绑定与插件设置。`prepare_recipe` 按当前绑定解析 recipe并生成快照；历史 Generation 按
  plugin_id 回到原实现；Core 确定性工具直接注册；
- `settings.py`：`.runtime/providers.json` 的严格读写；
- `image_prompt_skill.py`、`skills/`：项目与 Playground 共用的全局图片写作 Skill，以及 Playground 能力目录的 `audio_prompt`（当前文生音频 recipe 与随插件 Skill 全文）；图片工作集通过 `global_skills` 交付，当前插件的标签、画幅和专业 Skill 由 `image_prompt_guide` 汇总。有参考图时按真实标签逐图说明用途、正文逐图引用，不写文件名；无参考图时只写正文；
- `recipe.py`：语义输入与机制参数构成 `RecipeRequest`，按 manifest 校验；模型插件用 `submit_recipe` 接收异步请求，ASR 用 `execute_recipe` 同步返回文字；
- `contracts.py`：Core 确定性工具的请求值对象，由 `core/media_tools/` 在本机执行；模型的 HTTP DTO 与 `to_request` 翻译位于插件包；
- `boundary.py`：Core 消化调用句柄、进度和 Artifact 所需的最小内部类型；视频插件可在
  `ArtifactDescriptor.duration_seconds` 返回实测时长，Core 优先将它写入 Asset，不能用提交时预估值
  冒充媒体事实；
- `http.py`：插件可复用的低级 HTTP 传输，不是公共 Provider RPC；
- `observation_wait.py`：项目 `generation.wait` 与 Playground `wait_runs` 共用的有界观察：等待预算环境变量、单轮截止与后台续跑的刷新复用；
- `bundle.py`：Provider bundle SDK：Provider 目录清单名 `slatehand-provider.toml`、`create_bundle(context)` 工厂签名、
  `ProviderBundle`（插件 + 随 Core 启停的服务）与 `BundleContext`。具体插件不在 Core 内，作者的实现是独立仓库
  slatehand-providers-example。

插件不拥有 Project、Shot、审核或生产流程。跨边界只能传受控字段和媒体字节，不能传本地路径、工作
目录或任意命令。外部响应必须按插件自己的严格规则校验。
