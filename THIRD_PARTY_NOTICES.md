# 第三方来源说明

Slatehand 自身代码与文档以 Apache License 2.0 发布（见根目录 `LICENSE`）。下列第三方材料按各自许可证使用，
不因随本仓库分发而改为 Apache-2.0。
作者默认部署的 Provider 实现（独立仓库 `slatehand-providers-example`）随插件发布的第三方 Skill、模板与转谱脚本，
登记在该仓库自己的 `THIRD_PARTY_NOTICES.md`。

## Pannellum 全景查看器

- 上游项目：https://github.com/mpetroff/pannellum
- 固定版本：2.5.7（npm `pannellum`）
- 上游许可证：MIT License
- 使用范围：Web 室内地点的实时全景机位预览

Slatehand 不修改 Pannellum 上游源码；`web/src/director_workspace/PanoramaCameraEditor.tsx` 是独立编写的 React 生命周期与
Slatehand 机位字段适配层。上游许可证全文与集成说明见 `web/third_party/pannellum/`。

## OpenMontage Creative Intake 思想参考

- 上游项目：OpenMontage
- 上游仓库：https://github.com/calesthio/OpenMontage
- 上游许可证：GNU Affero General Public License v3.0 only

本仓库不包含 OpenMontage 的文字或其衍生文件。Slatehand 只采用过渐进式访谈、区分已确认与未决定信息等通用
产品思想，相关能力已按 Slatehand 的产品边界独立重写，没有复制 OpenMontage 的文字、字段 schema、Reviewer
流程或 Pipeline 结构。

## DirectorSKILL 导演方法参考

- 上游项目：DirectorSKILL（cinematic-director）
- 上游仓库：https://github.com/wuwangzhang1216/DirectorSKILL
- 固定版本：`47db7d9`
- 上游许可证：MIT
- Slatehand 路径：`core/director_proposals/skills/slatehand-structured-director-script/references/drama-scene-craft.md`

剧情戏的人际距离、权力几何、画面权重、运镜与倾听者覆盖、AI 视频对白可靠性等思想参考了该项目的
`cinematic-language.md`、`blocking-and-staging.md`、`editing-and-assembly.md`、`sound-and-dialogue.md`
与 `genre-playbooks.md`。Slatehand 文件按自身脚本字段与阶段边界用中文重新表述，示例为独立编写，
没有复制上游文字。
