# 第三方来源说明

StoryRail 自身代码与文档以 Apache License 2.0 发布（见根目录 `LICENSE`）。下列第三方材料按各自许可证使用，
不因随本仓库分发而改为 Apache-2.0。

## Pannellum 全景查看器

- 上游项目：https://github.com/mpetroff/pannellum
- 固定版本：2.5.7（npm `pannellum`）
- 上游许可证：MIT License
- 使用范围：Web 室内地点的实时全景机位预览

StoryRail 不修改 Pannellum 上游源码；`web/src/director_workspace/PanoramaCameraEditor.tsx` 是独立编写的 React 生命周期与
StoryRail 机位字段适配层。上游许可证全文与集成说明见 `web/third_party/pannellum/`。

## OpenMontage Creative Intake 思想参考

- 上游项目：OpenMontage
- 上游仓库：https://github.com/calesthio/OpenMontage
- 上游许可证：GNU Affero General Public License v3.0 only

本仓库不包含 OpenMontage 的文字或其衍生文件。StoryRail 只采用过渐进式访谈、区分已确认与未决定信息等通用
产品思想，相关能力已按 StoryRail 的产品边界独立重写，没有复制 OpenMontage 的文字、字段 schema、Reviewer
流程或 Pipeline 结构。

## MiniMax H3 官方 Prompt Skill

- 上游仓库：https://github.com/MiniMax-AI/MiniMax-H3（`skills/h3-prompt-writing/`）
- 固定版本：`a107547fa669c509b8e6363fe18378d46ab3066c`
- 上游许可证：MiniMax H3 Community License Agreement（全文见 StoryRail 路径下的 `LICENSE`）
- StoryRail 路径：`core/model_providers/minimax_h3/skills/h3-prompt-writing/`

`references/base-en.txt`、`references/ref-en.txt` 与 `SKILL.md` 在上游基础上做了修改（正文语言跟随用户、
音效必写、默认不生成非画内配乐，以及 StoryRail 的导演边界与旁白隔离规则），`agents/openai.yaml` 未修改，
`references/cinematic-video-prompting.md` 为 StoryRail 独立编写。逐文件修改说明与上游要求的版权声明见同目录
`NOTICE`。该协议对适用地区、使用限制和高收入商用另有约定，使用者须自行遵守。

## SeedVR2 私有部署依赖

- 上游实现：https://github.com/itontonpi/seedvr2
- 上游许可证：Apache License 2.0
- 权重镜像：https://www.modelscope.cn/models/numz/SeedVR2_comfyUI
- 使用范围：私有 Windows 默认模型服务的外部运行时

StoryRail 仓库不包含 SeedVR2 上游源码或模型权重，只包含独立编写的模型级 HTTP 插件、严格请求构造和
常驻 worker 启动适配。部署者仍须分别遵守上游实现与模型权重页面声明的许可证和使用条件。

## whisper.cpp 本机 ASR 依赖

- 上游实现：https://github.com/ggml-org/whisper.cpp
- 上游许可证：MIT License
- 默认模型：`ggml-large-v3-turbo-q5_0.bin`
- 模型来源：https://huggingface.co/ggerganov/whisper.cpp
- 使用范围：本机 Apple Silicon Reference Voice 中英文转写服务

StoryRail 仓库不包含 whisper.cpp 源码、二进制或模型权重，只包含独立 HTTP Provider adapter、
人类 UI 触发入口与启动配置。识别文字是可编辑候选，不作为未经确认的项目事实。

## Qwen Image 2.1 官方提示词模板与 NoctQ V4 权重

- 上游仓库：https://github.com/QwenLM/Qwen-Image-2.1
- 上游文件：`prompt_rewrite/prompts/system_prompt_t2i.txt`、`prompt_rewrite/prompts/system_prompt_edit.txt`
- 固定版本：`7307809d2c9d582be700a1b9b04d393fc9cdf865`
- 上游许可证：Qwen RESEARCH LICENSE AGREEMENT（仅限非商业的研究与评估用途；分发须附协议副本、NOTICE 与修改说明）
- StoryRail 路径：`core/model_providers/qwen_image/skills/qwen-image-prompt-writing/references/t2i-en.txt`、`edit-en.txt`
- SHA-256：`t2i-en.txt` `a77c9a06c59b120741141d9514b95682bb8761d02bec49ca61def7b2b3d9fb99`；
  `edit-en.txt` `e378fea686a1431581ba4c654d332ae96adad633f144ae738ec8ce9c4fd66439`

两个模板按字节原样引入，StoryRail 的适配规则写在同目录 `SKILL.md`，不修改原文；协议全文与上游要求的
版权声明见 `core/model_providers/qwen_image/skills/qwen-image-prompt-writing/` 下的 `LICENSE` 与 `NOTICE`。
这两个模板只可用于非商业用途，商用须另行取得 Qwen 授权。私有 Windows 服务使用的 NoctQ V4
（`NoctQ_V4_int8_convrot.safetensors`）是 Qwen Image 2.1 的 Civitai 社区微调权重，StoryRail 仓库不包含
任何 Qwen 权重。

## DirectorSKILL 导演方法参考

- 上游项目：DirectorSKILL（cinematic-director）
- 上游仓库：https://github.com/wuwangzhang1216/DirectorSKILL
- 固定版本：`47db7d9`
- 上游许可证：MIT
- StoryRail 路径：`core/director_proposals/skills/storyrail-structured-director-script/references/drama-scene-craft.md`

剧情戏的人际距离、权力几何、画面权重、运镜与倾听者覆盖、AI 视频对白可靠性等思想参考了该项目的
`cinematic-language.md`、`blocking-and-staging.md`、`editing-and-assembly.md`、`sound-and-dialogue.md`
与 `genre-playbooks.md`。StoryRail 文件按自身脚本字段与阶段边界用中文重新表述，示例为独立编写，
没有复制上游文字。
