---
name: storyrail-narration-review
description: 在集中旁白审核阶段，根据用户反馈用自然语言调整已有旁白 Cue 某一语言（中文或英文）的表演指示（语气、情绪、语速、停顿）与 seed，并提出是否重新生成。
---

# StoryRail 旁白审核

协助用户比较和调整旁白表演。旁白语言由项目创建时的 `narration_languages` 决定。每条 Cue 只包含所选语言，未选语言字段为 null；仅调整所选语言，各自合成、试听与选择。
只操作输入中已有 Cue 某一语言的 `recipe_params`（按工作集 `speech_recipe.editable_params`） 与 `seed`；不要改旁白正文、Scene、Shot、Segment
或角色对白。不要直接调用 Provider、选择候选或批准旁白。

先读取 [references/parameter-contract.md](references/parameter-contract.md)。只更新用户明确要求的 Cue 与语言；
用户没有指明语言时，按其描述判断指的是哪一版，无法判断时调整项目所选语言。用户要求试听、重做或
“按这个方向来一版”时才把 `regenerate` 设为 true。
