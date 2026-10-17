---
name: storyrail-reference-library
description: 在 StoryRail 首次进入结构化导演台时，从已确认材料中提取需要保持视觉或声音一致的角色及其造型；之后按用户要求增改造型、生成造型设定图。造型是角色图的唯一单位。不复述剧情、表演、场景或镜头信息。
---

# StoryRail 角色与声音引用准备

先读 read_workflow_state，以 required_next_actions 为主流程依据。提交后等待用户在 Web 确认引用；不能用地点规划代替角色与声音引用。

提取需要跨镜头保持身份的画面角色，以及故事内稳定的非出镜声音（广播、电话等）。卡片是媒体生成引用，不是剧本摘要：不要写故事作用、人物关系、
表演动作、场景环境、叙事 Scene 或其它已由剧本表达的内容。画外旁白不是角色；如果材料需要旁白，必须
单独返回 narrator 音色身份，绝不能把“解说员”放进 characters。

角色卡是 proposal。不要生成 ID，不要声称已保存，不要创建 `project.json`、Scene、Shot、Prompt、参考图或
音频。画面角色必须给出简洁的稳定视觉描述；只有上游明确声音方向时才填写角色音色描述。
非出镜声音仍在 characters 中分配稳定身份，visual_description 必须为 null，voice_description 必须非空；
不伪造外貌或参考图片，不能放进 Shot/Keyframe 的 visible_character_ids。故事内声音可参与对白和 Ref2VA，
不同于叙事旁白；没有叙事旁白时 narrator 必须为 null。
不要用通用“电影感”细节填满卡片。

每个出镜角色至少规划一套造型（look）：同一角色在不同时期、服装或身体状态下的外观各成一套，
并写清这套造型用在故事的什么时期或场合。

生成卡片前读取 [references/card-contract.md](references/card-contract.md)。引用库建立后增改造型、生成造型设定图时
读取 [references/look-sheets.md](references/look-sheets.md)。
